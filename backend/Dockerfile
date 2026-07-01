FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cache-bust the source COPY: Railway's layer cache can otherwise serve a stale
# `app/` (a SUCCESS build that ships old code). Bump this token to force a fresh
# copy of the source on the next deploy.
RUN echo "source-version: 2026-07-01-onboarding-session-token"

COPY app ./app

EXPOSE 8000

# Always-on, multiple workers — Railway. No scale-to-zero (latency budget).
# Shell form so ${PORT} (injected by Railway) expands; falls back to 8000 locally.
CMD gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w 2 -b 0.0.0.0:${PORT:-8000} --timeout 30
