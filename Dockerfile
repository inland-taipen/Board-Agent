# BoardLens AI - single image serving both the API and the web interface.
#
# One image is deliberate: listed-company platform teams review what they
# deploy, and a single container with one open port is far easier to get
# through an information-security review than a multi-service topology.

# --- stage 1: build the web interface ----------------------------------------
FROM node:22-alpine AS web

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BOARDLENS_DATA_DIR=/data \
    BOARDLENS_WEB_DIR=/app/frontend/dist

WORKDIR /app

COPY backend/pyproject.toml ./backend/
COPY backend/boardlens ./backend/boardlens
# Install all three provider SDKs. They are small next to the base image, and a
# deployed container that cannot reach the provider the operator has a key for
# is a support call rather than a saved megabyte. The `dense` extra is excluded
# deliberately - it pulls torch and would multiply the image size.
RUN pip install --no-cache-dir "./backend[gemini,groq]"

COPY --from=web /build/dist ./frontend/dist

# Run unprivileged; the data directory is the only writable path needed.
RUN useradd --system --uid 10001 --home /app boardlens \
    && mkdir -p /data \
    && chown -R boardlens:boardlens /data /app
USER boardlens

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "boardlens.main:app", "--host", "0.0.0.0", "--port", "8000"]
