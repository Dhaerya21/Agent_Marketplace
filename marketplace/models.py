"""
Database Models for AI Agent Marketplace
==========================================
SQLAlchemy models for users, agents, purchases, pipelines, and run history.
"""

import os
import json
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    credits = db.Column(db.Integer, default=100, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    purchases = db.relationship("Purchase", backref="user", lazy=True)
    pipelines = db.relationship("Pipeline", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "credits": self.credits,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Agent(db.Model):
    __tablename__ = "agents"

    id = db.Column(db.String(50), primary_key=True)           # e.g. "researcher"
    name = db.Column(db.String(120), nullable=False)
    tagline = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Integer, nullable=False)              # credits
    icon = db.Column(db.String(10), nullable=False)            # emoji icon
    category = db.Column(db.String(50), nullable=False)
    tags = db.Column(db.Text, default="[]")                    # JSON array
    color = db.Column(db.String(20), default="#00d4ff")        # accent color
    # --- HIDDEN from users ---
    a2a_url = db.Column(db.String(200), nullable=False)        # internal URL
    skill_id = db.Column(db.String(100), nullable=False)       # internal skill name
    agent_type = db.Column(db.String(20), default="a2a")       # "a2a" or future "mcp"

    purchases = db.relationship("Purchase", backref="agent", lazy=True)

    def to_public_dict(self):
        """Public info only -- no internals exposed."""
        return {
            "id": self.id,
            "name": self.name,
            "tagline": self.tagline,
            "description": self.description,
            "price": self.price,
            "icon": self.icon,
            "category": self.category,
            "tags": json.loads(self.tags) if self.tags else [],
            "color": self.color,
        }


class Purchase(db.Model):
    __tablename__ = "purchases"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    agent_id = db.Column(db.String(50), db.ForeignKey("agents.id"), nullable=False)
    purchased_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("user_id", "agent_id", name="unique_user_agent"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "purchased_at": self.purchased_at.isoformat() if self.purchased_at else None,
        }


class Pipeline(db.Model):
    __tablename__ = "pipelines"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, default="")
    config = db.Column(db.Text, nullable=False)                # JSON pipeline config
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    runs = db.relationship("PipelineRun", backref="pipeline", lazy=True,
                           order_by="PipelineRun.started_at.desc()")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "config": json.loads(self.config) if self.config else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PipelineRun(db.Model):
    __tablename__ = "pipeline_runs"

    id = db.Column(db.Integer, primary_key=True)
    pipeline_id = db.Column(db.Integer, db.ForeignKey("pipelines.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(20), default="running")       # running, completed, failed
    input_text = db.Column(db.Text, default="")
    output_text = db.Column(db.Text, default="")               # JSON results
    steps_completed = db.Column(db.Integer, default=0)
    total_steps = db.Column(db.Integer, default=0)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "input_text": self.input_text,
            "output_text": self.output_text,
            "steps_completed": self.steps_completed,
            "total_steps": self.total_steps,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ==============================================================================
# SEED DATA -- Agent catalog
# ==============================================================================
def seed_agents():
    """Insert the three A2A agents into the database if they don't exist."""
    agents = [
        Agent(
            id="researcher",
            name="Research & Analysis Agent",
            tagline="Deep-dive research powered by BM25 + LLM",
            description=(
                "Performs comprehensive research on any topic using intelligent document "
                "retrieval (BM25) and a powerful language model. Retrieves relevant passages "
                "from a curated knowledge base, synthesizes key findings with evidence, and "
                "returns a structured research report complete with source citations and "
                "confidence scores. Perfect for investigative analysis, fact-gathering, "
                "and knowledge extraction."
            ),
            price=20,
            icon="R",
            category="Research",
            tags=json.dumps(["research", "analysis", "retrieval", "knowledge", "investigation"]),
            color="#00d4ff",
            a2a_url="http://localhost:5001",
            skill_id="research_topic",
        ),
        Agent(
            id="documentation",
            name="Documentation Writer Agent",
            tagline="Transform research into polished documents",
            description=(
                "A professional documentation writer that transforms raw research findings "
                "into well-structured, publication-ready documents. Produces documents with "
                "proper titles, executive abstracts, organized sections with inline citations, "
                "conclusions, and formatted reference lists. Accepts structured research data "
                "or plain text summaries."
            ),
            price=15,
            icon="D",
            category="Writing",
            tags=json.dumps(["documentation", "writing", "formatting", "synthesis", "technical"]),
            color="#a855f7",
            a2a_url="http://localhost:5002",
            skill_id="write_documentation",
        ),
        Agent(
            id="citation",
            name="Citation & Fact-Check Agent",
            tagline="Verify claims and validate every citation",
            description=(
                "An expert fact-checker and citation auditor that verifies every claim in a "
                "document against source evidence. Extracts factual claims, cross-references "
                "them with sources, validates citation accuracy, flags unsupported or "
                "unverifiable statements, and produces a comprehensive verification report "
                "with a trust score (0-100). Essential for ensuring document reliability."
            ),
            price=25,
            icon="C",
            category="Verification",
            tags=json.dumps(["citation", "fact-check", "verification", "trust", "audit"]),
            color="#00ff88",
            a2a_url="http://localhost:5003",
            skill_id="verify_and_cite",
        ),
    ]

    for agent_data in agents:
        existing = Agent.query.get(agent_data.id)
        if not existing:
            db.session.add(agent_data)

    db.session.commit()
