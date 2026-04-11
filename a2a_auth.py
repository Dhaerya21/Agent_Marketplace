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
import functools
from flask import request, jsonify

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
    if api_key == MARKETPLACE_MASTER_KEY:
        return True, {"user": "marketplace_proxy", "role": "internal"}

    keys = _load_keys()

    # Keys file structure: { "ak_xxx": {"user_id": 1, "agent_id": "researcher", ...} }
    key_data = keys.get(api_key)
    if not key_data:
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

    Args:
        agent: A2AServer instance
        agent_id: Agent ID string (e.g., "researcher")
        port: Port number (for logging)

    Returns:
        Flask app with auth middleware applied
    """
    # Get the internal create_flask_app function from python_a2a
    from python_a2a import run_server
    create_flask_app = run_server.__globals__["create_flask_app"]

    # Create the base Flask app
    app = create_flask_app(agent)

    # Store the original /a2a route handler
    original_a2a_view = None
    for rule in app.url_map.iter_rules():
        if rule.rule == "/a2a":
            original_a2a_view = app.view_functions.get(rule.endpoint)
            break

    if original_a2a_view:
        # Replace with an authenticated version
        @require_api_key(agent_id=agent_id)
        def authenticated_a2a():
            return original_a2a_view()

        # Replace the view function
        for rule in app.url_map.iter_rules():
            if rule.rule == "/a2a":
                app.view_functions[rule.endpoint] = authenticated_a2a
                break

    print(f"  [auth] API key authentication enabled on /a2a")
    print(f"  [auth] Agent card (/.well-known/agent.json) remains public")
    print(f"  [auth] Keys file: {KEYS_FILE}")

    return app
