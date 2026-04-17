"""
Redis-Backed Rate Limiter
==========================
Sliding-window rate limiting using Redis.
Falls back to in-memory if Redis is unavailable (for local dev).

Usage:
    from .rate_limiter import limiter

    @app.route("/api/agents/<id>/run")
    @limiter.limit("agent_run", key_func=lambda: get_jwt_identity())
    def run_agent(id): ...
"""

import time
import logging
import functools
from flask import request, jsonify

logger = logging.getLogger("marketplace.rate_limiter")

# ==============================================================================
# REDIS CONNECTION
# ==============================================================================
_redis_client = None
_use_memory_fallback = False
_memory_store = {}  # fallback: key -> [timestamps]


def init_redis(redis_url):
    """Initialize Redis connection. Fallback to memory if unavailable."""
    global _redis_client, _use_memory_fallback
    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True, socket_timeout=2)
        _redis_client.ping()
        logger.info(f"[rate_limiter] Connected to Redis: {redis_url}")
        _use_memory_fallback = False
    except Exception as e:
        logger.warning(f"[rate_limiter] Redis unavailable ({e}), using in-memory fallback")
        _use_memory_fallback = True
        _redis_client = None


# ==============================================================================
# CORE RATE CHECK
# ==============================================================================
def _check_rate_redis(key, limit, window):
    """Sliding window rate check using Redis sorted sets."""
    now = time.time()
    pipe = _redis_client.pipeline()

    # Remove expired entries
    pipe.zremrangebyscore(key, 0, now - window)
    # Count current entries
    pipe.zcard(key)
    # Add current request
    pipe.zadd(key, {str(now): now})
    # Set expiry on the key
    pipe.expire(key, window + 1)

    results = pipe.execute()
    current_count = results[1]

    if current_count >= limit:
        # Get oldest entry to calculate reset time
        oldest = _redis_client.zrange(key, 0, 0, withscores=True)
        retry_after = int(window - (now - oldest[0][1])) + 1 if oldest else window
        return False, current_count, limit, retry_after

    return True, current_count + 1, limit, 0


def _check_rate_memory(key, limit, window):
    """In-memory sliding window rate check (dev fallback)."""
    now = time.time()

    if key not in _memory_store:
        _memory_store[key] = []

    # Clean expired entries
    _memory_store[key] = [t for t in _memory_store[key] if now - t < window]

    current_count = len(_memory_store[key])

    if current_count >= limit:
        retry_after = int(window - (now - _memory_store[key][0])) + 1 if _memory_store[key] else window
        return False, current_count, limit, retry_after

    _memory_store[key].append(now)
    return True, current_count + 1, limit, 0


def check_rate(key, limit, window):
    """Check rate limit. Returns (allowed, current, limit, retry_after)."""
    if _use_memory_fallback or _redis_client is None:
        return _check_rate_memory(key, limit, window)
    try:
        return _check_rate_redis(key, limit, window)
    except Exception as e:
        logger.error(f"Redis rate check failed: {e}, falling back to memory")
        return _check_rate_memory(key, limit, window)


# ==============================================================================
# DECORATOR
# ==============================================================================
class RateLimiter:
    """Rate limiter with configurable limits per resource type."""

    def __init__(self):
        from .config import cfg
        self._limits = cfg.RATE_LIMITS

    def limit(self, resource_type, key_func=None):
        """
        Decorator to rate-limit an endpoint.

        Args:
            resource_type: Key in RATE_LIMITS config (e.g., "agent_run")
            key_func: Function returning the rate limit key (default: user ID from JWT)
        """
        def decorator(f):
            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                config = self._limits.get(resource_type)
                if not config:
                    return f(*args, **kwargs)

                # Get the key (user ID, IP, etc.)
                if key_func:
                    try:
                        identity = key_func()
                    except Exception:
                        identity = request.remote_addr
                else:
                    identity = request.remote_addr

                rate_key = f"rl:{resource_type}:{identity}"
                allowed, current, limit, retry_after = check_rate(
                    rate_key, config["limit"], config["window"]
                )

                if not allowed:
                    response = jsonify({
                        "error": f"Rate limit exceeded. Maximum {limit} requests per {config['window']}s.",
                        "retry_after": retry_after,
                    })
                    response.status_code = 429
                    response.headers["Retry-After"] = str(retry_after)
                    response.headers["X-RateLimit-Limit"] = str(limit)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    response.headers["X-RateLimit-Reset"] = str(int(time.time()) + retry_after)
                    return response

                # Execute the endpoint
                result = f(*args, **kwargs)

                # Add rate limit headers to successful responses
                if hasattr(result, "headers"):
                    result.headers["X-RateLimit-Limit"] = str(limit)
                    result.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
                elif isinstance(result, tuple) and len(result) >= 1:
                    resp = result[0]
                    if hasattr(resp, "headers"):
                        resp.headers["X-RateLimit-Limit"] = str(limit)
                        resp.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))

                return result

            return wrapper
        return decorator

    def check_global(self, user_id):
        """
        Check global per-user rate limit. Call this in before_request.
        Returns (allowed, response_or_none).
        """
        config = self._limits.get("global_user")
        if not config:
            return True, None

        rate_key = f"rl:global:{user_id}"
        allowed, current, limit, retry_after = check_rate(
            rate_key, config["limit"], config["window"]
        )

        if not allowed:
            response = jsonify({
                "error": "Global rate limit exceeded. Slow down.",
                "retry_after": retry_after,
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return False, response

        return True, None


# Singleton (initialized lazily)
_limiter = None


def get_limiter():
    """Get or create the rate limiter singleton."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
