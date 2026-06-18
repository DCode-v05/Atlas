# ─── Stage 1: build the React/Vite frontend ──────────────────────────────────
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

# ─── Stage 2: Python runtime serving API + static frontend (single container) ─
FROM python:3.12-slim AS app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ATLAS_HOST=0.0.0.0 \
    ATLAS_PORT=8000

# Runtime deps (kept explicit so the image needs no build backend).
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "sse-starlette>=2.1" \
    "boto3>=1.40"

COPY pyproject.toml ./
COPY atlas/ ./atlas/
COPY --from=web /web/dist ./web/dist

EXPOSE 8000
# One worker is mandatory: the in-process agent bus must stay in a single process.
CMD ["python", "-m", "atlas"]
