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
# ffmpeg/ffprobe: transcription pipeline. curl: fetch litestream.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg curl \
 && rm -rf /var/lib/apt/lists/*
# Litestream: continuous SQLite replication to Supabase Storage.
RUN curl -sSL https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz \
    | tar -xz -C /usr/local/bin litestream
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY prompts/ prompts/
COPY week.yaml week.yaml
COPY litestream.yml entrypoint.sh ./
RUN chmod +x entrypoint.sh
COPY --from=web /web/dist frontend/dist
ENV SENTINEL_STATIC=/app/frontend/dist \
    PYTHONUNBUFFERED=1
EXPOSE 7860
# entrypoint restores the DB from Supabase then runs the app under Litestream.
CMD ["/app/entrypoint.sh"]
