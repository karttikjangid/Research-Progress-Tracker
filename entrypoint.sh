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
  # -if-replica-exists already exits 0 when the bucket is reachable but empty
  # (true first boot). A NON-zero exit means Supabase is unreachable (e.g. the
  # free project got auto-paused). We used to `|| true` that and boot an EMPTY
  # DB, which silently hid all data AND then replicated the empty DB up as the
  # newest generation — the next restore would pick it over the real history.
  # Now: retry, then refuse to start. Down is recoverable; a forked history isn't.
  n=0
  until litestream restore -if-replica-exists -config /app/litestream.yml "$SENTINEL_DB_PATH"; do
    n=$((n + 1))
    if [ "$n" -ge "${RESTORE_ATTEMPTS:-5}" ]; then
      echo "[entrypoint] FATAL: cannot reach the Supabase replica after $n attempts." >&2
      echo "[entrypoint] Is the Supabase project paused? Resume it, then redeploy/restart." >&2
      echo "[entrypoint] (Set ALLOW_EMPTY_BOOT=1 to deliberately start with an empty DB.)" >&2
      [ "${ALLOW_EMPTY_BOOT:-0}" = "1" ] && break
      exit 1
    fi
    echo "[entrypoint] restore failed (attempt $n) — retrying in 5s…" >&2
    rm -f "$SENTINEL_DB_PATH" "$SENTINEL_DB_PATH-wal" "$SENTINEL_DB_PATH-shm"
    sleep 5
  done
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
