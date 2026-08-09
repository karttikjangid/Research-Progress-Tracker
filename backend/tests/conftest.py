import datetime as dt
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

ARTIFACT = ("Derived SVD from the spectral theorem: A^T A is symmetric PSD, so it "
            "admits an eigendecomposition V D V^T with orthonormal V. Set sigma_i "
            "= sqrt(d_i), u_i = A v_i / sigma_i, showed u_i orthonormal, extended "
            "to a full basis via Gram-Schmidt for rank-deficient A. NumPy check: "
            "reconstruction error 3e-15 on a rank-2 6x4 matrix.")
ANSWER = ("The gradient expression is unchanged because it never required full "
          "column rank; what changes is the solution set — the normal equations "
          "become singular and the minimizers form an affine set W* + null(X), "
          "so descent simply never moves along the flat directions.")


MODS = ("main", "db", "llm", "transcribe", "infra", "clock")


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Fresh app + fresh state root (db, data, logs, backups) per test."""
    monkeypatch.setenv("GATEKEEPER_STATE", str(tmp_path))
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-never-used")
    monkeypatch.delenv("GATEKEEPER_DB", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    for m in MODS:
        sys.modules.pop(m, None)
    import main
    yield main
    for m in MODS:
        sys.modules.pop(m, None)


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    return TestClient(app.app)


@pytest.fixture()
def mock_llm(app, monkeypatch):
    """Deterministic evaluator; tests override attributes to change behavior."""
    calls = {"question": 0, "eval": 0,
             "real_evaluate_answer": app.llm.evaluate_answer}

    def gen_q(artifact, **kw):
        calls["question"] += 1
        calls["last_gen_kwargs"] = kw
        return f"Probing question #{calls['question']}: what breaks at n=1?"

    def ev(artifact, question, answer, **kw):
        calls["eval"] += 1
        return ("PASS", "specific and correct")

    monkeypatch.setattr(app.llm, "generate_question", gen_q)
    monkeypatch.setattr(app.llm, "evaluate_answer", ev)
    monkeypatch.setattr(app.llm, "audit_transcript",
                        lambda t, **kw: "AUDIT: be blunt")
    return calls


def make_webm(path: Path, seconds: int):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", "libopus", "-b:a", "16k", str(path)],
        check=True, capture_output=True)
    return path


def gated(client, title="Gated"):
    r = client.post("/api/tasks", json={"title": title, "type": "gated"})
    assert r.status_code == 201
    return r.json()["id"]


def freeze(app, date_str, hour=12):
    """Freeze 'now' for a test. Patches app.today/app._now (what most route
    logic calls) AND app.clock.now_utc directly — llm.py's audit-trail
    timestamps (_record in llm.py) call clock.now_utc() straight, bypassing
    main._now, so a freeze that only patches the latter silently leaves
    llm_calls rows stamped with the real wall-clock time. Found via
    test_simulated_week_export failing off of its assumed date; see
    SESSION_LOG.md."""
    d = dt.date.fromisoformat(date_str)
    when = dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.timezone.utc)
    app.today = lambda: date_str
    app._now = lambda: when
    app.clock.now_utc = lambda: when
