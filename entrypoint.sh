#!/bin/sh
# Container entrypoint: restore the DB from Supabase on a fresh (ephemeral) disk,
# then run the app under Litestream so the SQLite DB is continuously replicated.
# Falls back to running the app directly when Supabase isn't configured.
set -e

: "${GATEKEEPER_STATE:=/data}"
export SENTINEL_DB_PATH="${GATEKEEPER_DB:-$GATEKEEPER_STATE/data/gatekeeper.db}"
mkdir -p "$(dirname "$SENTINEL_DB_PATH")"

if [ -n "$SUPABASE_S3_BUCKET" ] && [ ! -f "$SENTINEL_DB_PATH" ]; then
  echo "[entrypoint] no local DB — restoring from Supabase if a replica exists…"
  litestream restore -if-replica-exists -config /app/litestream.yml "$SENTINEL_DB_PATH" || true
fi

cd /app/backend
if [ -n "$SUPABASE_S3_BUCKET" ]; then
  echo "[entrypoint] running under Litestream, replicating to Supabase…"
  exec litestream replicate -config /app/litestream.yml \
    -exec "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"
else
  echo "[entrypoint] Supabase not configured — running without replication…"
  exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-7860}"
fi
