"""
API Key Authentication for A2A Agents
=======================================
Shared authentication middleware used by all A2A agents.

The marketplace generates a unique API key per user per agent on purchase.
Valid keys are stored in a shared JSON file that this middleware reads.

Security model:
  - Agent Card endpoint (/.well-known/agent.json) → PUBLIC (it's metadata)
  - Task execution endpoint (/a2a) → REQUIRES API KEY
  - API key sent via header: X-API-Key: <key>

Usage in agent files:
    from a2a_auth import create_authenticated_server

    agent = MyAgent()
    app = create_authenticated_server(agent, port=5001)
    app.run(host="0.0.0.0", port=5001)
"""

import os
import json
import hmac
import logging
import functools
from flask import request, jsonify

logger = logging.getLogger("a2a_auth")

# ==============================================================================
# CONFIG
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_FILE = os.path.join(BASE_DIR, "marketplace", "api_keys.json")

# Internal master key used by the marketplace proxy when it forwards requests.
# This lets the marketplace run agents on behalf of authenticated users.
MARKETPLACE_MASTER_KEY = os.environ.get(
    "MARKETPLACE_MASTER_KEY", "mk_internal_proxy_2a9f8b3e"
)


# ==============================================================================
# KEY STORE — reads from shared file
# ==============================================================================
def _load_keys():
    """Load valid API keys from the shared keys file."""
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def is_valid_key(api_key, agent_id=None):
    """
    Check if an API key is valid.

    Args:
        api_key: The key to validate
        agent_id: Optional — if provided, also checks key is valid for this agent

    Returns:
        (is_valid, user_info_or_none)
    """
    # Master key bypasses all checks (used by marketplace proxy)
    # Use timing-safe comparison to prevent timing attacks
    if hmac.compare_digest(api_key, MARKETPLACE_MASTER_KEY):
        return True, {"user": "marketplace_proxy", "role": "internal"}

    keys = _load_keys()

    # Keys file structure: { "ak_xxx": {"user_id": 1, "agent_id": "researcher", ...} }
    # Use timing-safe lookup to prevent key enumeration
    key_data = None
    for stored_key, data in keys.items():
        if hmac.compare_digest(api_key, stored_key):
            key_data = data
            break
    if not key_data:
        logger.warning(f"Invalid API key attempt from {request.remote_addr if request else 'unknown'}")
        return False, None

    # If agent_id specified, ensure the key is valid for this specific agent
    if agent_id and key_data.get("agent_id") != agent_id:
        return False, None

    return True, key_data


def save_key(api_key, user_id, agent_id, username=""):
    """Save a new API key to the shared keys file."""
    keys = _load_keys()
    keys[api_key] = {
        "user_id": user_id,
        "agent_id": agent_id,
        "username": username,
    }
    os.makedirs(os.path.dirname(KEYS_FILE), exist_ok=True)
    with open(KEYS_FILE, "w") as f:
        json.dump(keys, f, indent=2)


def revoke_key(api_key):
    """Revoke an API key."""
    keys = _load_keys()
    if api_key in keys:
        del keys[api_key]
        with open(KEYS_FILE, "w") as f:
            json.dump(keys, f, indent=2)
        return True
    return False


def get_keys_for_user(user_id, agent_id=None):
    """Get all API keys for a specific user (optionally filtered by agent)."""
    keys = _load_keys()
    result = {}
    for k, v in keys.items():
        if v.get("user_id") == user_id:
            if agent_id is None or v.get("agent_id") == agent_id:
                result[k] = v
    return result


# ==============================================================================
# FLASK MIDDLEWARE
# ==============================================================================
def require_api_key(agent_id=None):
    """
    Flask decorator that requires a valid API key in the X-API-Key header.

    Usage:
        @app.route("/a2a", methods=["POST"])
        @require_api_key(agent_id="researcher")
        def handle_task():
            ...
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            api_key = request.headers.get("X-API-Key", "").strip()

            if not api_key:
                return jsonify({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32001,
                        "message": "Authentication required. Provide your API key in the X-API-Key header.",
                    },
                    "id": None,
                }), 401

            valid, info = is_valid_key(api_key, agent_id)
            if not valid:
                return jsonify({
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32002,
                        "message": "Invalid API key. Purchase this agent from the marketplace to get a valid key.",
                    },
                    "id": None,
                }), 403

            return f(*args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# AUTHENTICATED SERVER FACTORY
# ==============================================================================
def create_authenticated_server(agent, agent_id, port=5000):
    """
    Create a Flask app from an A2A agent with API key authentication
    on the /a2a endpoint. The agent card remains public.

    Fixes the python_a2a library's issue where JSON-RPC tasks/send requests
    are incorrectly handled by the legacy Message route. We intercept /a2a,
    validate the API key, and dispatch to handle_task directly.

    Args:
        agent: A2AServer instance
        agent_id: Agent ID string (e.g., "researcher")
        port: Port number (for logging)

    Returns:
        Flask app with auth middleware applied
    """
    import json as _json
    import uuid as _uuid
    from flask import Flask, request as flask_request, jsonify as flask_jsonify

    # Create a fresh Flask app with just the agent card route
    app = Flask(__name__)

    # --- Public: Agent Card endpoint ---
    @app.route("/.well-known/agent.json", methods=["GET"])
    def agent_card():
        """Serve the Agent Card (public, no auth needed)."""
        card = agent.agent_card
        card_dict = {
            "name": card.name,
            "description": card.description,
            "version": card.version,
            "url": f"http://localhost:{port}",
        }
        if hasattr(card, "skills") and card.skills:
            card_dict["skills"] = []
            for s in card.skills:
                skill_dict = {"name": s.name}
                if hasattr(s, "description") and s.description:
                    skill_dict["description"] = s.description
                if hasattr(s, "tags") and s.tags:
                    skill_dict["tags"] = s.tags
                card_dict["skills"].append(skill_dict)
        if hasattr(card, "capabilities") and card.capabilities:
            card_dict["capabilities"] = card.capabilities
        return flask_jsonify(card_dict)

    # --- Protected: A2A task execution endpoint ---
    @app.route("/a2a", methods=["POST"])
    def handle_a2a():
        """Handle A2A JSON-RPC requests with API key authentication."""
        # 1. Validate API key
        api_key = flask_request.headers.get("X-API-Key", "").strip()
        if not api_key:
            return flask_jsonify({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32001,
                    "message": "Authentication required. Provide your API key in the X-API-Key header.",
                },
                "id": None,
            }), 401

        valid, info = is_valid_key(api_key, agent_id)
        if not valid:
            return flask_jsonify({
                "jsonrpc": "2.0",
                "error": {
                    "code": -32002,
                    "message": "Invalid API key. Purchase this agent from the marketplace to get a valid key.",
                },
                "id": None,
            }), 403

        # 2. Parse the incoming request
        data = flask_request.get_json(force=True, silent=True) or {}
        rpc_id = data.get("id")
        method = data.get("method", "")
        params = data.get("params", {})

        # 3. Handle JSON-RPC tasks/send
        if method == "tasks/send":
            try:
                from python_a2a import TaskStatus, TaskState
                from python_a2a.models.task import Task

                # Create task from params
                task = Task.from_dict(params)

                # Extract text from the message for agents that expect it
                msg = params.get("message", {})
                content = msg.get("content", {})
                if isinstance(content, dict):
                    text = content.get("text", "")
                elif isinstance(content, str):
                    text = content
                else:
                    text = str(content)

                # Ensure task.message is in the format the agent expects
                task.message = {
                    "role": msg.get("role", "user"),
                    "content": {"type": "text", "text": text},
                }

                # Run the agent's handle_task
                result_task = agent.handle_task(task)

                # Serialize the result
                result_dict = result_task.to_dict()

                return flask_jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": result_dict,
                })

            except Exception as e:
                import traceback
                traceback.print_exc()
                return flask_jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32603,
                        "message": f"Agent execution failed: {str(e)}",
                    },
                }), 500

        # 4. Handle tasks/get
        elif method == "tasks/get":
            task_id = params.get("id")
            task = agent.tasks.get(task_id) if hasattr(agent, "tasks") else None
            if task:
                return flask_jsonify({
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": task.to_dict(),
                })
            return flask_jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32000, "message": f"Task not found: {task_id}"},
            }), 404

        # 5. Unknown method
        else:
            return flask_jsonify({
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"},
            }), 400

    # --- Health check ---
    @app.route("/a2a/health", methods=["GET"])
    def health():
        return flask_jsonify({"status": "ok"})

    print(f"  [auth] API key authentication enabled on /a2a")
    print(f"  [auth] Agent card (/.well-known/agent.json) remains public")
    print(f"  [auth] Keys file: {KEYS_FILE}")

    return app

