# Gunicorn settings for the Rudo dashboard. Access logging is OFF on purpose: URLs can carry phone-derived
# conversation references and search terms. The app logs route templates, status and timings instead.
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = int(os.environ.get('WEB_CONCURRENCY', '2'))
threads = int(os.environ.get('RUDO_THREADS', '4'))
worker_class = 'gthread'
timeout = 30
graceful_timeout = 20
keepalive = 5
accesslog = None
errorlog = '-'
loglevel = 'info'
forwarded_allow_ips = os.environ.get('FORWARDED_ALLOW_IPS', '127.0.0.1')
limit_request_line = 8190
