# Rudo staff dashboard (read-only observer + staff management). No secrets in the image.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 ca-certificates && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 rudo
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
# Only what the dashboard serves/runs. Tests, docs, scripts, staging fixtures and local files stay out.
COPY app.py wsgi.py ./
COPY rudo ./rudo
COPY deploy/gunicorn.conf.py ./deploy/gunicorn.conf.py
COPY deploy/certs ./deploy/certs
COPY observer.html staff.html staff-login.html staff-reset.html login.html register.html forgot-password.html reset-password.html ./
COPY css ./css
COPY js ./js
COPY img ./img
USER rudo
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz',timeout=4)"
CMD ["gunicorn", "-c", "deploy/gunicorn.conf.py", "wsgi:app"]
