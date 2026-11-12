# DocQABot Studio: one image for the app and (in demo mode / tests) the OpenAI stub.
# Same image on Windows (Docker Desktop) and Linux servers. No key, no .env, no data inside.

# ---- 1. frontend build ------------------------------------------------------------
FROM node:22-bookworm-slim AS web
# SKIP_WEB=true builds an image without the web UI (backend-only checks). Default: the UI is required.
ARG SKIP_WEB=false
WORKDIR /web
COPY web/ ./
RUN if [ "$SKIP_WEB" = "true" ]; then \
        echo "SKIP_WEB=true: building without the web UI" && rm -rf /web/* && mkdir -p /web/dist; \
    else \
        test -f package.json || { echo "web/package.json is missing" >&2; exit 1; }; \
        npm ci --no-audit --no-fund && npm run build && test -f dist/index.html; \
    fi

# ---- 2. runtime -------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STUDIO_WEB_DIST=/srv/web

WORKDIR /srv/app

# Root requirements.txt is UTF-16 with BOM (frozen core file); pip reads it as is.
COPY requirements.txt requirements-studio.txt ./
RUN pip install -r requirements-studio.txt

COPY app/ ./app/
COPY studio/ ./studio/
COPY --from=web /web/dist/ /srv/web/

RUN useradd --system --uid 10001 --home-dir /srv/app --shell /usr/sbin/nologin studio \
    && chown -R studio /srv/app
USER studio

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "studio.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
