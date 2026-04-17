"""
AI Agent Marketplace -- Flask API Server
==========================================
REST API with JWT auth, Redis rate limiting, security hardening,
agent purchasing, tool APIs, and pipeline workflows.

Run:
    python -m marketplace.app

Then open: http://localhost:8080
"""

import sys
import subprocess

def _ensure(pkg, import_name=None):
    import importlib
    try:
        importlib.import_module(import_name or pkg)
    except ImportError:
        print(f"[setup] Installing {pkg} ...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

_ensure("flask")
_ensure("flask_sqlalchemy", "flask_sqlalchemy")
_ensure("flask_jwt_extended", "flask_jwt_extended")
_ensure("flask_cors", "flask_cors")
_ensure("python-a2a", "python_a2a")
_ensure("redis")

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)

from .models import db, User, Agent, Purchase, ToolApiKey, Pipeline, PipelineRun, seed_agents
from .agent_proxy import proxy
from .pipeline_engine import execute_pipeline, validate_pipeline_access
from .tools import get_tools_public, execute_tool, TOOLS
from .config import cfg
from .security import (
    sanitize_input, sanitize_output, sanitize_string_field,
    validate_request_middleware, add_security_headers,
)
from .rate_limiter import init_redis, get_limiter

# Import auth helpers for syncing API keys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from a2a_auth import save_key, revoke_key

# ==============================================================================
# LOGGING
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("marketplace")

# ==============================================================================
# APP FACTORY
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SQLALCHEMY_DATABASE_URI"] = cfg.DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = cfg.SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=cfg.JWT_TOKEN_EXPIRES_HOURS)
app.config["MAX_CONTENT_LENGTH"] = cfg.MAX_REQUEST_SIZE_BYTES

CORS(app, origins=cfg.CORS_ORIGINS.split(",") if cfg.CORS_ORIGINS != "*" else "*")
db.init_app(app)
jwt = JWTManager(app)

# Initialize Redis for rate limiting
init_redis(cfg.REDIS_URL)

# Initialize DB + seed agents on first run
with app.app_context():
    db.create_all()
    seed_agents()
    logger.info("[db] Database initialized and agents seeded.")


# ==============================================================================
# SECURITY MIDDLEWARE
# ==============================================================================
@app.before_request
def before_request_hook():
    """Validate requests + add request ID for tracing."""
    # Add request ID for tracing (useful for CloudWatch)
    request.request_id = str(uuid.uuid4())[:8]

    # Validate request size/type
    error_response = validate_request_middleware()
    if error_response:
        return error_response

    # Check global rate limit for authenticated users
    try:
        from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity as _get_id
        verify_jwt_in_request(optional=True)
        identity = _get_id()
        if identity:
            limiter = get_limiter()
            allowed, resp = limiter.check_global(identity)
            if not allowed:
                return resp
    except Exception:
        pass

    return None


@app.after_request
def after_request_hook(response):
    """Add security headers + request ID to all responses."""
    response = add_security_headers(response)
    response.headers["X-Request-ID"] = getattr(request, "request_id", "unknown")
    return response


# ==============================================================================
# STATIC FILES -- Serve the SPA
# ==============================================================================
@app.route("/")
def serve_index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    # Block any attempt to access Python/config files
    blocked_extensions = {".py", ".pyc", ".db", ".env", ".json", ".csv", ".log", ".conf"}
    ext = os.path.splitext(path)[1].lower()
    if ext in blocked_extensions:
        return jsonify({"error": "Not found."}), 404

    if path.startswith("api/"):
        return jsonify({"error": "Not found."}), 404

    full_path = os.path.join(STATIC_DIR, path)
    # Prevent path traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(STATIC_DIR)):
        return jsonify({"error": "Not found."}), 404

    if os.path.isfile(full_path):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


# ==============================================================================
# HEALTH CHECK (for ALB / monitoring)
# ==============================================================================
@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint for load balancers and monitoring."""
    return jsonify({
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }), 200


# ==============================================================================
# AUTH ENDPOINTS
# ==============================================================================
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = sanitize_string_field(data.get("username", ""), 80)
    email = sanitize_string_field(data.get("email", ""), 120).lower()
    password = data.get("password", "")

    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required."}), 400
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400
    if "@" not in email:
        return jsonify({"error": "Invalid email address."}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({"error": "Username already taken."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered."}), 409

    user = User(username=username, email=email, credits=100)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    token = create_access_token(identity=str(user.id))
    return jsonify({
        "token": token,
        "user": user.to_dict(),
        "message": f"Welcome {username}! You've received 100 free credits.",
    }), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json() or {}
    username = sanitize_string_field(data.get("username", ""), 80)
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required."}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        logger.warning(f"Failed login attempt for '{username}' from {request.remote_addr}")
        return jsonify({"error": "Invalid username or password."}), 401

    token = create_access_token(identity=str(user.id))
    return jsonify({
        "token": token,
        "user": user.to_dict(),
    }), 200


@app.route("/api/auth/me", methods=["GET"])
@jwt_required()
def get_me():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found."}), 404
    return jsonify({"user": user.to_dict()}), 200


# ==============================================================================
# MARKETPLACE ENDPOINTS
# ==============================================================================
@app.route("/api/marketplace", methods=["GET"])
def get_marketplace():
    """List all agents -- public info only, no internals."""
    agents = Agent.query.all()
    result = []
    for agent in agents:
        agent_dict = agent.to_public_dict()
        health = proxy.check_health(agent.a2a_url)
        agent_dict["online"] = health.get("online", False)
        result.append(agent_dict)
    return jsonify({"agents": result}), 200


@app.route("/api/marketplace/<agent_id>", methods=["GET"])
def get_agent_details(agent_id):
    """Get single agent details -- public info only."""
    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404
    agent_dict = agent.to_public_dict()
    health = proxy.check_health(agent.a2a_url)
    agent_dict["online"] = health.get("online", False)
    return jsonify({"agent": agent_dict}), 200


# ==============================================================================
# PURCHASE ENDPOINTS
# ==============================================================================
@app.route("/api/purchase", methods=["POST"])
@jwt_required()
def purchase_agent():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return jsonify({"error": "User not found."}), 404

    data = request.get_json() or {}
    agent_id = sanitize_string_field(data.get("agent_id", ""), 50)

    if not agent_id:
        return jsonify({"error": "agent_id is required."}), 400

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    existing = Purchase.query.filter_by(user_id=user.id, agent_id=agent_id).first()
    if existing:
        return jsonify({"error": "You already own this agent."}), 409

    if user.credits < agent.price:
        return jsonify({
            "error": f"Not enough credits. You have {user.credits}, need {agent.price}.",
        }), 402

    user.credits -= agent.price
    purchase = Purchase(user_id=user.id, agent_id=agent_id)
    db.session.add(purchase)
    db.session.commit()

    # Sync the API key to the shared keys file for A2A agents
    try:
        save_key(purchase.api_key, user.id, agent_id, user.username)
    except Exception as e:
        logger.warning(f"Could not sync API key to keys file: {e}")

    return jsonify({
        "message": f"Successfully purchased {agent.name}!",
        "purchase": purchase.to_dict(),
        "remaining_credits": user.credits,
    }), 200


@app.route("/api/my-agents", methods=["GET"])
@jwt_required()
def get_my_agents():
    user_id = int(get_jwt_identity())
    purchases = Purchase.query.filter_by(user_id=user_id).all()

    agents = []
    for p in purchases:
        agent = Agent.query.get(p.agent_id)
        if agent:
            agent_dict = agent.to_public_dict()
            agent_dict["purchased_at"] = p.purchased_at.isoformat() if p.purchased_at else None
            health = proxy.check_health(agent.a2a_url)
            agent_dict["online"] = health.get("online", False)
            agent_dict["a2a_url"] = agent.a2a_url
            agent_dict["agent_card_url"] = agent.a2a_url + "/.well-known/agent.json"
            agent_dict["api_key"] = p.api_key
            agents.append(agent_dict)

    return jsonify({"agents": agents}), 200


@app.route("/api/agents/<agent_id>/regenerate-key", methods=["POST"])
@jwt_required()
def regenerate_api_key(agent_id):
    """Regenerate the API key for a purchased agent."""
    user_id = int(get_jwt_identity())

    # Rate limit key regeneration
    limiter = get_limiter()
    from .rate_limiter import check_rate
    rate_key = f"rl:key_regen:{user_id}"
    regen_cfg = cfg.RATE_LIMITS.get("key_regen", {"limit": 3, "window": 3600})
    allowed, _, _, retry = check_rate(rate_key, regen_cfg["limit"], regen_cfg["window"])
    if not allowed:
        return jsonify({"error": "Too many key regeneration attempts. Try again later."}), 429

    user = User.query.get(user_id)
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    # Revoke old key
    old_key = purchase.api_key
    try:
        revoke_key(old_key)
    except Exception:
        pass

    # Generate new key
    import secrets
    new_key = "ak_" + secrets.token_hex(16)
    purchase.api_key = new_key
    db.session.commit()

    try:
        save_key(new_key, user_id, agent_id, user.username if user else "")
    except Exception as e:
        logger.warning(f"Could not sync new API key: {e}")

    return jsonify({
        "api_key": new_key,
        "message": "API key regenerated. Your old key is now invalid.",
    }), 200


@app.route("/api/agents/<agent_id>/card", methods=["GET"])
@jwt_required()
def get_agent_card(agent_id):
    """Fetch the live Agent Card for a purchased agent."""
    user_id = int(get_jwt_identity())
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    try:
        import requests as http_requests
        card_url = agent.a2a_url + "/.well-known/agent.json"
        resp = http_requests.get(card_url, timeout=5)
        resp.raise_for_status()
        card_data = resp.json()
    except Exception:
        return jsonify({
            "error": "Agent is currently offline. Cannot fetch Agent Card.",
            "a2a_url": agent.a2a_url,
            "agent_card_url": agent.a2a_url + "/.well-known/agent.json",
        }), 503

    return jsonify({
        "agent_card": card_data,
        "a2a_url": agent.a2a_url,
        "agent_card_url": agent.a2a_url + "/.well-known/agent.json",
    }), 200


@app.route("/api/agents/<agent_id>/snippets", methods=["GET"])
@jwt_required()
def get_agent_snippets(agent_id):
    """Generate integration code snippets for a purchased agent."""
    user_id = int(get_jwt_identity())
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    snippets = proxy.generate_snippets(agent.a2a_url, agent.name, agent.agent_type, api_key=purchase.api_key)
    return jsonify({
        "snippets": snippets,
        "agent_type": agent.agent_type or "a2a",
        "a2a_url": agent.a2a_url,
        "agent_card_url": agent.a2a_url + "/.well-known/agent.json",
    }), 200


@app.route("/api/agents/<agent_id>/skills", methods=["GET"])
def get_agent_skills(agent_id):
    """Get skills preview for any agent (public endpoint)."""
    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404
    skills = proxy.get_skills_preview(agent.a2a_url)
    return jsonify({"skills": skills}), 200


# ==============================================================================
# AGENT EXECUTION ENDPOINTS
# ==============================================================================
@app.route("/api/agents/<agent_id>/run", methods=["POST"])
@jwt_required()
def run_agent(agent_id):
    user_id = int(get_jwt_identity())

    # Rate limit agent execution
    limiter = get_limiter()
    from .rate_limiter import check_rate
    rate_key = f"rl:agent_run:{user_id}"
    agent_cfg = cfg.RATE_LIMITS.get("agent_run", {"limit": 10, "window": 60})
    allowed, _, _, retry = check_rate(rate_key, agent_cfg["limit"], agent_cfg["window"])
    if not allowed:
        return jsonify({
            "error": f"Rate limit exceeded. Max {agent_cfg['limit']} agent runs per minute.",
            "retry_after": retry,
        }), 429

    # Verify purchase
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    data = request.get_json() or {}
    user_input = (data.get("input") or "").strip()

    # Input validation + sanitization
    clean_input, input_err = sanitize_input(user_input, cfg.MAX_INPUT_LENGTH)
    if input_err:
        return jsonify({"error": input_err}), 400

    # Execute via proxy -- hides all internals
    result = proxy.run_agent(agent.a2a_url, clean_input, agent.agent_type)

    # Sanitize output — strip internal URLs/paths, escape HTML
    safe_result = sanitize_output(result)

    return jsonify({"result": safe_result}), 200


# ==============================================================================
# PIPELINE ENDPOINTS
# ==============================================================================
@app.route("/api/pipelines", methods=["GET"])
@jwt_required()
def get_pipelines():
    user_id = int(get_jwt_identity())
    pipelines = Pipeline.query.filter_by(user_id=user_id).all()
    return jsonify({"pipelines": [p.to_dict() for p in pipelines]}), 200


@app.route("/api/pipelines", methods=["POST"])
@jwt_required()
def create_pipeline():
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}

    name = sanitize_string_field(data.get("name", ""), 120)
    description = sanitize_string_field(data.get("description", ""), 500)
    config = data.get("config", {})

    if not name:
        return jsonify({"error": "Pipeline name is required."}), 400
    if not config.get("steps"):
        return jsonify({"error": "Pipeline must have at least one step."}), 400

    valid, error = validate_pipeline_access(user_id, config)
    if not valid:
        return jsonify({"error": error}), 403

    pipeline = Pipeline(
        user_id=user_id,
        name=name,
        description=description,
        config=json.dumps(config),
    )
    db.session.add(pipeline)
    db.session.commit()
    return jsonify({"pipeline": pipeline.to_dict()}), 201


@app.route("/api/pipelines/<int:pipeline_id>", methods=["DELETE"])
@jwt_required()
def delete_pipeline(pipeline_id):
    user_id = int(get_jwt_identity())
    pipeline = Pipeline.query.filter_by(id=pipeline_id, user_id=user_id).first()
    if not pipeline:
        return jsonify({"error": "Pipeline not found."}), 404

    PipelineRun.query.filter_by(pipeline_id=pipeline_id).delete()
    db.session.delete(pipeline)
    db.session.commit()
    return jsonify({"message": "Pipeline deleted."}), 200


@app.route("/api/pipelines/<int:pipeline_id>/run", methods=["POST"])
@jwt_required()
def run_pipeline(pipeline_id):
    user_id = int(get_jwt_identity())
    pipeline = Pipeline.query.filter_by(id=pipeline_id, user_id=user_id).first()
    if not pipeline:
        return jsonify({"error": "Pipeline not found."}), 404

    data = request.get_json() or {}
    user_input = (data.get("input") or "").strip()

    clean_input, input_err = sanitize_input(user_input, cfg.MAX_INPUT_LENGTH)
    if input_err:
        return jsonify({"error": input_err}), 400

    config = json.loads(pipeline.config) if pipeline.config else {}

    run = PipelineRun(
        pipeline_id=pipeline_id,
        user_id=user_id,
        input_text=clean_input,
        total_steps=len(config.get("steps", [])),
    )
    db.session.add(run)
    db.session.commit()

    try:
        result = execute_pipeline(config, clean_input, proxy)
        run.status = "completed"
        run.output_text = json.dumps(sanitize_output(result))
        run.steps_completed = len(config.get("steps", []))
        run.completed_at = datetime.now(timezone.utc)
    except Exception as e:
        run.status = "failed"
        run.output_text = json.dumps({"error": str(e)})
        run.completed_at = datetime.now(timezone.utc)

    db.session.commit()

    return jsonify({
        "run": run.to_dict(),
        "result": sanitize_output(json.loads(run.output_text)) if run.output_text else None,
    }), 200


@app.route("/api/pipelines/<int:pipeline_id>/runs", methods=["GET"])
@jwt_required()
def get_pipeline_runs(pipeline_id):
    user_id = int(get_jwt_identity())
    pipeline = Pipeline.query.filter_by(id=pipeline_id, user_id=user_id).first()
    if not pipeline:
        return jsonify({"error": "Pipeline not found."}), 404

    runs = PipelineRun.query.filter_by(
        pipeline_id=pipeline_id, user_id=user_id
    ).order_by(PipelineRun.started_at.desc()).limit(20).all()

    return jsonify({"runs": [r.to_dict() for r in runs]}), 200


# ==============================================================================
# HOSTED TOOLS ENDPOINTS
# ==============================================================================
@app.route("/api/tools", methods=["GET"])
def list_tools():
    """List all available tools — public."""
    tools = get_tools_public()
    # Add pricing info
    for t in tools:
        t["price"] = cfg.TOOL_PRICES.get(t["id"], 2)
    return jsonify({"tools": tools}), 200


@app.route("/api/tools/<tool_id>/run", methods=["POST"])
@jwt_required()
def run_tool(tool_id):
    """Execute a tool — requires auth + credits."""
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404

    if tool_id not in TOOLS:
        return jsonify({"error": "Tool not found."}), 404

    # Rate limit tool execution
    from .rate_limiter import check_rate
    rate_key = f"rl:tool_run:{user_id}"
    tool_cfg = cfg.RATE_LIMITS.get("tool_run", {"limit": 15, "window": 60})
    allowed, _, _, retry = check_rate(rate_key, tool_cfg["limit"], tool_cfg["window"])
    if not allowed:
        return jsonify({
            "error": f"Rate limit exceeded. Max {tool_cfg['limit']} tool runs per minute.",
            "retry_after": retry,
        }), 429

    # Check credits
    price = cfg.TOOL_PRICES.get(tool_id, 2)
    if user.credits < price:
        return jsonify({
            "error": f"Not enough credits. You have {user.credits}, need {price}.",
        }), 402

    data = request.get_json() or {}
    text = (data.get("input") or "").strip()
    options = data.get("options", {})

    # Sanitize input
    clean_text, input_err = sanitize_input(text, cfg.MAX_INPUT_LENGTH)
    if input_err:
        return jsonify({"error": input_err}), 400

    result, error = execute_tool(tool_id, user_id, clean_text, options)

    if error:
        return jsonify({"error": error}), 400

    # Deduct credits
    user.credits -= price
    db.session.commit()

    # Sanitize output
    safe_result = sanitize_output(result)

    return jsonify({
        "result": safe_result,
        "tool": tool_id,
        "credits_used": price,
        "credits_remaining": user.credits,
    }), 200


@app.route("/api/tools/<tool_id>/api-key", methods=["GET"])
@jwt_required()
def get_tool_api_key(tool_id):
    """Get or create an API key for a tool."""
    user_id = int(get_jwt_identity())

    if tool_id not in TOOLS:
        return jsonify({"error": "Tool not found."}), 404

    # Get or create the key
    key_record = ToolApiKey.query.filter_by(user_id=user_id, tool_id=tool_id).first()
    if not key_record:
        key_record = ToolApiKey(user_id=user_id, tool_id=tool_id)
        db.session.add(key_record)
        db.session.commit()

    return jsonify({
        "api_key": key_record.api_key,
        "tool_id": tool_id,
    }), 200


@app.route("/api/tools/<tool_id>/regenerate-key", methods=["POST"])
@jwt_required()
def regenerate_tool_api_key(tool_id):
    """Regenerate the API key for a tool."""
    user_id = int(get_jwt_identity())

    # Rate limit
    from .rate_limiter import check_rate
    rate_key = f"rl:key_regen:{user_id}"
    regen_cfg = cfg.RATE_LIMITS.get("key_regen", {"limit": 3, "window": 3600})
    allowed, _, _, retry = check_rate(rate_key, regen_cfg["limit"], regen_cfg["window"])
    if not allowed:
        return jsonify({"error": "Too many key regeneration attempts. Try again later."}), 429

    key_record = ToolApiKey.query.filter_by(user_id=user_id, tool_id=tool_id).first()
    if not key_record:
        return jsonify({"error": "No API key found for this tool."}), 404

    import secrets
    key_record.api_key = "ak_" + secrets.token_hex(16)
    db.session.commit()

    return jsonify({
        "api_key": key_record.api_key,
        "message": "Tool API key regenerated.",
    }), 200


@app.route("/api/tools/<tool_id>/snippets", methods=["GET"])
@jwt_required()
def get_tool_snippets(tool_id):
    """Generate integration snippets for a tool."""
    user_id = int(get_jwt_identity())

    if tool_id not in TOOLS:
        return jsonify({"error": "Tool not found."}), 404

    tool = TOOLS[tool_id]

    # Get or create API key
    key_record = ToolApiKey.query.filter_by(user_id=user_id, tool_id=tool_id).first()
    if not key_record:
        key_record = ToolApiKey(user_id=user_id, tool_id=tool_id)
        db.session.add(key_record)
        db.session.commit()

    api_key = key_record.api_key
    base_url = request.host_url.rstrip("/")

    snippets = {
        "python": (
            f'import requests, json\n'
            f'\n'
            f'# {tool["name"]} — API Integration\n'
            f'API_URL = "{base_url}/api/tools/{tool_id}/run"\n'
            f'TOKEN = "YOUR_JWT_TOKEN"  # From /api/auth/login\n'
            f'\n'
            f'resp = requests.post(API_URL, json={{\n'
            f'    "input": "Your text here",\n'
            f'    "options": {{}}\n'
            f'}}, headers={{\n'
            f'    "Authorization": f"Bearer {{TOKEN}}",\n'
            f'    "Content-Type": "application/json"\n'
            f'}})\n'
            f'print(json.dumps(resp.json(), indent=2))\n'
        ),
        "curl": (
            f'# Run {tool["name"]}\n'
            f'curl -X POST {base_url}/api/tools/{tool_id}/run \\\n'
            f'  -H "Content-Type: application/json" \\\n'
            f'  -H "Authorization: Bearer YOUR_JWT_TOKEN" \\\n'
            f'  -d \'{{"input":"Your text here","options":{{}}}}\'\n'
        ),
        "javascript": (
            f'// {tool["name"]} — API Integration\n'
            f'const res = await fetch("{base_url}/api/tools/{tool_id}/run", {{\n'
            f'  method: "POST",\n'
            f'  headers: {{\n'
            f'    "Content-Type": "application/json",\n'
            f'    "Authorization": `Bearer ${{token}}`\n'
            f'  }},\n'
            f'  body: JSON.stringify({{\n'
            f'    input: "Your text here",\n'
            f'    options: {{}}\n'
            f'  }})\n'
            f'}});\n'
            f'console.log(await res.json());\n'
        ),
    }

    return jsonify({
        "snippets": snippets,
        "api_key": api_key,
        "endpoint": f"{base_url}/api/tools/{tool_id}/run",
        "rate_limit": cfg.RATE_LIMITS.get("tool_run", {}),
        "price_per_use": cfg.TOOL_PRICES.get(tool_id, 2),
    }), 200


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    port = int(os.environ.get("MARKETPLACE_PORT", 8080))
    print(f"\n{'='*60}")
    print(f"  AI Agent Marketplace v2.0")
    print(f"  URL    : http://localhost:{port}")
    print(f"  API    : http://localhost:{port}/api")
    print(f"  Health : http://localhost:{port}/api/health")
    print(f"  Redis  : {cfg.REDIS_URL}")
    print(f"  DB     : {cfg.DATABASE_URL}")
    print(f"  Env    : {cfg.ENV}")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
