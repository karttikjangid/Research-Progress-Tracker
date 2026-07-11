# syntax=docker/dockerfile:1

# ---- stage 1: build the frontend ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: backend runtime (also serves the built frontend) ----
FROM python:3.11-slim
# ffmpeg/ffprobe are required by the transcription pipeline
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY prompts/ prompts/
COPY week.yaml week.yaml
COPY --from=web /web/dist frontend/dist
ENV SENTINEL_STATIC=/app/frontend/dist \
    HF_HOME=/data/hf \
    PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000
# Render provides $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
