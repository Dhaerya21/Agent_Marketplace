"""
Application Configuration
==========================
Environment-based config for dev, staging, and production.
All sensitive values read from environment variables.

Usage:
    from .config import cfg
    app.config["SECRET_KEY"] = cfg.SECRET_KEY
"""

import os

class Config:
    """Centralized configuration — reads from env vars with safe defaults."""

    # ── App ────────────────────────────────────────────────────────────────
    ENV = os.environ.get("FLASK_ENV", "development")
    DEBUG = ENV == "development"
    SECRET_KEY = os.environ.get("JWT_SECRET", "marketplace-dev-secret-CHANGE-IN-PROD")
    JWT_TOKEN_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "24"))

    # ── Database ───────────────────────────────────────────────────────────
    # SQLite for dev, PostgreSQL for prod (just change the env var)
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _DEFAULT_DB = f"sqlite:///{os.path.join(_BASE_DIR, 'marketplace.db')}"
    DATABASE_URL = os.environ.get("DATABASE_URL", _DEFAULT_DB)

    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # ── CORS ───────────────────────────────────────────────────────────────
    # In production, set to your domain: "https://marketplace.example.com"
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

    # ── Agent URLs (internal — never exposed to users) ─────────────────────
    AGENT_URLS = {
        "researcher":     os.environ.get("RESEARCHER_URL",     "http://localhost:5001"),
        "documentation":  os.environ.get("DOCUMENTATION_URL",  "http://localhost:5002"),
        "citation":       os.environ.get("CITATION_URL",       "http://localhost:5003"),
        "codereview":     os.environ.get("CODEREVIEW_URL",     "http://localhost:5004"),
        "dataextractor":  os.environ.get("DATAEXTRACTOR_URL",  "http://localhost:5005"),
    }

    # ── Marketplace Proxy ──────────────────────────────────────────────────
    MARKETPLACE_MASTER_KEY = os.environ.get(
        "MARKETPLACE_MASTER_KEY", "mk_internal_proxy_2a9f8b3e"
    )

    # ── Rate Limits ────────────────────────────────────────────────────────
    RATE_LIMITS = {
        "agent_run":     {"limit": 10,  "window": 60},      # 10/min
        "tool_run":      {"limit": 15,  "window": 60},      # 15/min
        "auth":          {"limit": 5,   "window": 60},       # 5/min
        "key_regen":     {"limit": 3,   "window": 3600},     # 3/hour
        "global_user":   {"limit": 60,  "window": 60},       # 60/min total
    }

    # ── Security ───────────────────────────────────────────────────────────
    MAX_REQUEST_SIZE_BYTES = int(os.environ.get("MAX_REQUEST_SIZE", str(32 * 1024)))  # 32KB
    MAX_INPUT_LENGTH = int(os.environ.get("MAX_INPUT_LENGTH", "8000"))  # chars

    # ── Tool Pricing (credits) ─────────────────────────────────────────────
    TOOL_PRICES = {
        "summarizer": 2,
        "extractor":  2,
        "rewriter":   3,
    }

    # ── LLM (internal) ────────────────────────────────────────────────────
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
    LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")


cfg = Config()
