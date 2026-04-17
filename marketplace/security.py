"""
Security Module
================
Input/output sanitization, security headers, prompt injection detection,
and request validation for the AI Agent Marketplace.

Threat Model:
  - Prompt injection → Detect and block known patterns
  - XSS via LLM output → Escape all HTML in responses
  - Oversized payloads → Enforce request body limits
  - Source code theft → Strip internal paths/URLs from responses
  - Brute force → Rate limiting (handled by rate_limiter.py)
"""

import re
import html
import logging
from flask import request, jsonify

logger = logging.getLogger("marketplace.security")

# ==============================================================================
# PROMPT INJECTION DETECTION
# ==============================================================================
_INJECTION_PATTERNS = [
    # Direct prompt override attempts
    r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?|rules?)",
    r"(?i)disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)",
    r"(?i)forget\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)",
    r"(?i)override\s+(system|previous)\s+(prompt|instructions?)",
    # System prompt extraction
    r"(?i)(reveal|show|display|print|output|return)\s+(your|the)\s+(system\s+)?prompt",
    r"(?i)what\s+(are|is)\s+your\s+(system\s+)?(instructions?|prompt|rules?)",
    r"(?i)(repeat|echo)\s+(the\s+)?(system\s+)?prompt",
    # Role manipulation
    r"(?i)you\s+are\s+now\s+(a|an|the)\s+(unrestricted|unfiltered|evil)",
    r"(?i)act\s+as\s+(a|an)\s+(hacker|attacker|malicious)",
    r"(?i)jailbreak",
    r"(?i)DAN\s+mode",
    # Code/shell execution attempts
    r"(?i)(execute|run|eval)\s+(this\s+)?(python|code|command|shell|bash|script)",
    r"(?i)import\s+os\s*;",
    r"(?i)subprocess\.(run|call|Popen)",
    r"(?i)__import__",
    r"(?i)exec\s*\(",
]

_COMPILED_PATTERNS = [re.compile(p) for p in _INJECTION_PATTERNS]


def detect_prompt_injection(text):
    """
    Scan text for known prompt injection patterns.

    Returns:
        (is_suspicious, matched_pattern_description)
    """
    if not text:
        return False, None

    for i, pattern in enumerate(_COMPILED_PATTERNS):
        if pattern.search(text):
            logger.warning(f"Prompt injection detected (pattern {i}): {text[:100]}...")
            return True, "Potentially harmful input pattern detected."

    return False, None


# ==============================================================================
# INPUT SANITIZATION
# ==============================================================================
def sanitize_input(text, max_length=8000):
    """
    Clean and validate user input text.

    Returns:
        (clean_text, error_message)
    """
    if not text or not isinstance(text, str):
        return None, "Input text is required."

    text = text.strip()

    if not text:
        return None, "Input text cannot be empty."

    if len(text) > max_length:
        return None, f"Input too long. Maximum {max_length} characters."

    if len(text) < 3:
        return None, "Input too short. Minimum 3 characters."

    # Strip null bytes and other control characters (keep newlines/tabs)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Check for prompt injection
    is_suspicious, reason = detect_prompt_injection(text)
    if is_suspicious:
        return None, "Your input contains patterns that are not allowed. Please rephrase."

    return text, None


def sanitize_string_field(value, max_length=200):
    """Sanitize a short string field (username, email, etc.)."""
    if not isinstance(value, str):
        return ""
    value = value.strip()[:max_length]
    # Remove control characters
    value = re.sub(r'[\x00-\x1f\x7f]', '', value)
    return value


# ==============================================================================
# OUTPUT SANITIZATION
# ==============================================================================
def escape_html_deep(obj):
    """
    Recursively HTML-escape all string values in a dict/list.
    Prevents XSS from LLM-generated content.
    """
    if isinstance(obj, str):
        return html.escape(obj, quote=True)
    elif isinstance(obj, dict):
        return {k: escape_html_deep(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [escape_html_deep(item) for item in obj]
    return obj


# Internal patterns to strip from responses
_INTERNAL_PATTERNS = [
    r"http://localhost:\d+",
    r"http://127\.0\.0\.1:\d+",
    r"http://0\.0\.0\.0:\d+",
    r"http://192\.168\.\d+\.\d+:\d+",
    r"http://10\.\d+\.\d+\.\d+:\d+",
    r"[A-Za-z]:\\[\\A-Za-z0-9_.\-]+",  # Windows paths
    r"/home/[a-zA-Z0-9_]+/[^\s\"']+",   # Linux paths
    r"ollama|qwen2\.5|llama|mistral",    # Model names
    r"mk_internal_proxy_[a-f0-9]+",      # Master keys
]

_COMPILED_INTERNAL = [re.compile(p, re.IGNORECASE) for p in _INTERNAL_PATTERNS]


def strip_internals(obj):
    """Remove internal URLs, paths, and model names from response data."""
    if isinstance(obj, str):
        result = obj
        for pattern in _COMPILED_INTERNAL:
            result = pattern.sub("[REDACTED]", result)
        return result
    elif isinstance(obj, dict):
        # Remove known internal keys
        blocked_keys = {
            "a2a_url", "internal_url", "model", "model_name",
            "ollama_endpoint", "file_path", "chunk_id", "doc_index",
            "source_index", "master_key", "prompt_tokens", "eval_tokens",
        }
        return {
            k: strip_internals(v)
            for k, v in obj.items()
            if k not in blocked_keys
        }
    elif isinstance(obj, list):
        return [strip_internals(item) for item in obj]
    return obj


def sanitize_output(data):
    """Full output sanitization: strip internals + escape HTML."""
    return escape_html_deep(strip_internals(data))


# ==============================================================================
# REQUEST VALIDATION MIDDLEWARE
# ==============================================================================
def validate_request_middleware():
    """
    Flask before_request handler.
    Validates content length, content type, and rejects suspicious requests.
    """
    from .config import cfg

    # Skip for GET, OPTIONS, HEAD
    if request.method in ("GET", "OPTIONS", "HEAD"):
        return None

    # Check content length
    content_length = request.content_length or 0
    if content_length > cfg.MAX_REQUEST_SIZE_BYTES:
        logger.warning(f"Oversized request: {content_length} bytes from {request.remote_addr}")
        return jsonify({
            "error": f"Request body too large. Maximum {cfg.MAX_REQUEST_SIZE_BYTES // 1024}KB."
        }), 413

    # Ensure JSON content type for API endpoints
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "PATCH"):
        ct = request.content_type or ""
        if "json" not in ct and "form" not in ct:
            return jsonify({"error": "Content-Type must be application/json."}), 415

    return None


# ==============================================================================
# SECURITY HEADERS MIDDLEWARE
# ==============================================================================
def add_security_headers(response):
    """
    Flask after_request handler.
    Adds security headers to all responses.
    """
    # Prevent clickjacking
    response.headers["X-Frame-Options"] = "DENY"
    # Prevent MIME-type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # XSS protection (legacy browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Referrer policy
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Content Security Policy
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    # Permissions policy
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )

    return response
