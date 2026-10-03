# Bradley University AI Assistant
# One image runs both the web app and the crawler service (see docker-compose.yml).

# ---- Stage 1: build the React frontend ----
FROM node:24-alpine AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python backend ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # All state lives on the /data volume: the SQLite database and conversation exports
    DATABASE_URL=sqlite:////data/app.db \
    BACKUP_DIR=/data/backups \
    # The embedding model is baked into the image so the app starts fast and works offline
    EMBEDDING_CACHE_DIR=/opt/models \
    HF_HUB_OFFLINE=1

WORKDIR /app

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data /opt/models \
    && chown app:app /data /opt/models

# Dependencies are installed from backend/uv.lock, so every build gets the same versions.
# Update them with `uv lock --upgrade` in backend/.
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

USER app
RUN HF_HUB_OFFLINE=0 python -c "from fastembed import TextEmbedding; TextEmbedding('snowflake/snowflake-arctic-embed-s', cache_dir='/opt/models')"

COPY --chown=app:app backend/ ./
COPY --chown=app:app systemprompt.txt ./
COPY --from=frontend --chown=app:app /app/frontend/build/ ./static/

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

# uvicorn runs as PID 1 so `docker stop` shuts it down gracefully.
# One worker: the app is async, and one process is plenty for a single user.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
