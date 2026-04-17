"""
Gunicorn Production Configuration
===================================
Usage: gunicorn -c deployment/gunicorn.conf.py marketplace.app:app
"""

import multiprocessing

# Bind to all interfaces
bind = "0.0.0.0:8080"

# Workers = 2 × CPU cores + 1
workers = multiprocessing.cpu_count() * 2 + 1

# Use sync workers (compatible with Ollama blocking calls)
worker_class = "sync"

# Timeout — LLM calls can take up to 2 mins
timeout = 180
graceful_timeout = 30
keepalive = 5

# Max requests before worker restart (leak prevention)
max_requests = 500
max_requests_jitter = 50

# Logging
accesslog = "-"           # stdout (CloudWatch friendly)
errorlog = "-"            # stdout
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# Preload app (share memory across workers)
preload_app = True
