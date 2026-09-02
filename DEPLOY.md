# Deploying Sentinel on Render

Sentinel runs as **one Docker web service** on Render: the FastAPI backend serves
the API *and* the built frontend from the same URL, with a **persistent disk** for
the SQLite database, recorded audio, backups, and the transcription model. Access
is protected by a **single shared password** (HTTP Basic auth). Nothing is public
without that password.

## What's already wired for you

- `Dockerfile` — builds the frontend, installs `ffmpeg`, installs the backend, and
  serves everything on `$PORT`.
- `render.yaml` — a Blueprint describing the service, the disk, and the env vars.
- Backend changes — serves the built frontend, and gates every request behind
  `GATEKEEPER_PASSWORD` when that variable is set (unset locally → no auth).
- `/healthz` — an unauthenticated health check for Render.

## Before you start

- The repo is on GitHub (you've pushed it). **Make sure the new deploy files
  above are committed and pushed on the branch you'll deploy** (recommended:
  merge to `main`).
- Have your **NVIDIA NIM API key** ready.
- Decide a **password** you'll use to log in.

---

## Step 1 — Create the service from the Blueprint

1. Go to the Render dashboard → **New +** → **Blueprint**.
2. Connect your GitHub account and pick this repository, then the branch (`main`).
3. Render reads `render.yaml` and shows a plan: one web service (`sentinel`) with a
   5 GB disk at `/data`. Click **Apply**.

> Prefer to do it by hand instead? **New +** → **Web Service** → pick the repo →
> **Runtime: Docker** (it finds the `Dockerfile`) → set **Plan** to one with
> **≥ 2 GB RAM** → add a **Disk** (mount path `/data`, 5 GB) → **Health check path**
> `/healthz` → then add the env vars in Step 2.

## Step 2 — Set the secret environment variables

In the service's **Environment** tab, add the two secrets (the Blueprint left them
blank on purpose):

| Key | Value |
|---|---|
| `GATEKEEPER_PASSWORD` | the password you chose |
| `NVIDIA_API_KEY` | your NIM key (`nvapi-…`) |

These are already set by the Blueprint and should not be changed:
`GATEKEEPER_STATE=/data`, `HF_HOME=/data/hf`, `EVAL_MODEL=nvidia/nemotron-3-super-120b-a12b`.

Save — Render redeploys automatically.

## Step 3 — First build & deploy

The first build takes a few minutes (it builds the frontend, installs `ffmpeg`, and
installs Python deps). When it goes **Live**, open the service URL
(`https://sentinel-xxxx.onrender.com`).

- Your browser shows a **login prompt** → enter **any username** and your
  `GATEKEEPER_PASSWORD`.
- The **first recording** downloads the whisper model (~460 MB) into `/data/hf`.
  That one upload will sit for a couple of minutes; it's cached on the disk after
  that, so it won't happen again.

## Step 4 — Use it from your other laptops

Just open the same `https://…onrender.com` URL on any laptop and log in with the
password. All devices talk to this one service, so they share the same record.

---

## Optional — nightly auto-close

Add a **Render Cron Job** (New + → Cron Job) that closes the day at 23:00. Because
the API is password-protected, send the credentials with `-u`:

```bash
curl -s -u ":$GATEKEEPER_PASSWORD" -X POST https://sentinel-xxxx.onrender.com/api/day/close
```

Set the cron schedule to `0 23 * * *` and give the cron job the same
`GATEKEEPER_PASSWORD` env var. (You can also just click **Close the file** in the UI.)

## Updating the app

Push to the deployed branch — Render rebuilds and redeploys automatically
(`autoDeploy: true`). Your data on `/data` is untouched across deploys.

## Good to know

- **Keep the instance from sleeping.** A ≥ 2 GB paid instance stays warm. If it
  sleeps, the next request reloads the whisper model (slow first hit).
- **Where your data lives now.** The database and audio sit on Render's disk, and
  transcript *text* is sent to NVIDIA for the audit (the audio itself is
  transcribed on the server, not sent to the LLM). This is a change from
  everything-on-your-laptop — fine for personal use, worth knowing.
- **Back it up.** The `/data` disk is durable but single-copy. Periodically
  download `GET /api/export` (it's behind the password) or snapshot the disk.
- **Losing the password prompt / want to rotate it.** Change `GATEKEEPER_PASSWORD`
  in the Environment tab; it redeploys and all sessions must re-enter it.
