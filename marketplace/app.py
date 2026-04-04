"""
AI Agent Marketplace -- Flask API Server
==========================================
REST API for the AI Agent Marketplace with JWT authentication,
agent purchasing, individual agent execution, and pipeline workflows.

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

import os
import json
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity
)

from .models import db, User, Agent, Purchase, Pipeline, PipelineRun, seed_agents
from .agent_proxy import proxy
from .pipeline_engine import execute_pipeline, validate_pipeline_access

# ==============================================================================
# APP FACTORY
# ==============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(BASE_DIR, "marketplace.db")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET", "marketplace-dev-secret-change-in-prod")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)

CORS(app)
db.init_app(app)
jwt = JWTManager(app)

# Initialize DB + seed agents on first run
with app.app_context():
    db.create_all()
    seed_agents()
    print("[db] Database initialized and agents seeded.")


# ==============================================================================
# STATIC FILES -- Serve the SPA
# ==============================================================================
@app.route("/")
def serve_index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    # Never intercept API routes -- let Flask handle them
    if path.startswith("api/"):
        return jsonify({"error": "Not found."}), 404
    full_path = os.path.join(STATIC_DIR, path)
    if os.path.isfile(full_path):
        return send_from_directory(STATIC_DIR, path)
    return send_from_directory(STATIC_DIR, "index.html")


# ==============================================================================
# AUTH ENDPOINTS
# ==============================================================================
@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
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
    username = (data.get("username") or "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({"error": "Username and password required."}), 400

    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
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
    agent_id = data.get("agent_id")

    if not agent_id:
        return jsonify({"error": "agent_id is required."}), 400

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    # Check if already purchased
    existing = Purchase.query.filter_by(user_id=user.id, agent_id=agent_id).first()
    if existing:
        return jsonify({"error": "You already own this agent."}), 409

    # Check credits
    if user.credits < agent.price:
        return jsonify({
            "error": f"Not enough credits. You have {user.credits}, need {agent.price}.",
        }), 402

    # Process purchase
    user.credits -= agent.price
    purchase = Purchase(user_id=user.id, agent_id=agent_id)
    db.session.add(purchase)
    db.session.commit()

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
            # --- Purchased users get the Agent Card URL + hosted endpoint ---
            agent_dict["a2a_url"] = agent.a2a_url
            agent_dict["agent_card_url"] = agent.a2a_url + "/.well-known/agent.json"
            agents.append(agent_dict)

    return jsonify({"agents": agents}), 200


@app.route("/api/agents/<agent_id>/card", methods=["GET"])
@jwt_required()
def get_agent_card(agent_id):
    """Fetch the live Agent Card for a purchased agent."""
    user_id = int(get_jwt_identity())

    # Only purchased agents expose their card
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    # Fetch live Agent Card from the A2A server
    try:
        import requests as http_requests
        card_url = agent.a2a_url + "/.well-known/agent.json"
        resp = http_requests.get(card_url, timeout=5)
        resp.raise_for_status()
        card_data = resp.json()
    except Exception as e:
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


# ==============================================================================
# AGENT EXECUTION ENDPOINTS
# ==============================================================================
@app.route("/api/agents/<agent_id>/run", methods=["POST"])
@jwt_required()
def run_agent(agent_id):
    user_id = int(get_jwt_identity())

    # Verify purchase
    purchase = Purchase.query.filter_by(user_id=user_id, agent_id=agent_id).first()
    if not purchase:
        return jsonify({"error": "You haven't purchased this agent."}), 403

    agent = Agent.query.get(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404

    data = request.get_json() or {}
    user_input = (data.get("input") or "").strip()

    if not user_input:
        return jsonify({"error": "Input text is required."}), 400

    # Execute via proxy -- hides all internals
    result = proxy.run_agent(agent.a2a_url, user_input, agent.agent_type)
    return jsonify({"result": result}), 200


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

    name = (data.get("name") or "").strip()
    description = (data.get("description") or "").strip()
    config = data.get("config", {})

    if not name:
        return jsonify({"error": "Pipeline name is required."}), 400
    if not config.get("steps"):
        return jsonify({"error": "Pipeline must have at least one step."}), 400

    # Validate access
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

    return jsonify({
        "message": "Pipeline created!",
        "pipeline": pipeline.to_dict(),
    }), 201


@app.route("/api/pipelines/<int:pipeline_id>", methods=["DELETE"])
@jwt_required()
def delete_pipeline(pipeline_id):
    user_id = int(get_jwt_identity())
    pipeline = Pipeline.query.get(pipeline_id)

    if not pipeline or pipeline.user_id != user_id:
        return jsonify({"error": "Pipeline not found."}), 404

    # Delete associated runs
    PipelineRun.query.filter_by(pipeline_id=pipeline_id).delete()
    db.session.delete(pipeline)
    db.session.commit()

    return jsonify({"message": "Pipeline deleted."}), 200


@app.route("/api/pipelines/<int:pipeline_id>/run", methods=["POST"])
@jwt_required()
def run_pipeline(pipeline_id):
    user_id = int(get_jwt_identity())
    data = request.get_json() or {}
    input_text = (data.get("input") or "").strip()

    if not input_text:
        return jsonify({"error": "Input text is required."}), 400

    run, error = execute_pipeline(pipeline_id, user_id, input_text)

    if error:
        return jsonify({"error": error}), 400

    output = json.loads(run.output_text) if run.output_text else {}
    return jsonify({
        "run": run.to_dict(),
        "results": output,
    }), 200


@app.route("/api/pipelines/<int:pipeline_id>/runs", methods=["GET"])
@jwt_required()
def get_pipeline_runs(pipeline_id):
    user_id = int(get_jwt_identity())
    pipeline = Pipeline.query.get(pipeline_id)
    if not pipeline or pipeline.user_id != user_id:
        return jsonify({"error": "Pipeline not found."}), 404

    runs = PipelineRun.query.filter_by(
        pipeline_id=pipeline_id, user_id=user_id
    ).order_by(PipelineRun.started_at.desc()).limit(20).all()

    return jsonify({"runs": [r.to_dict() for r in runs]}), 200


# ==============================================================================
# MAIN
# ==============================================================================
def main():
    port = int(os.environ.get("MARKETPLACE_PORT", 8080))
    print(f"\n{'='*60}")
    print(f"  AI Agent Marketplace")
    print(f"  URL  : http://localhost:{port}")
    print(f"  API  : http://localhost:{port}/api")
    print(f"  DB   : {DB_PATH}")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
