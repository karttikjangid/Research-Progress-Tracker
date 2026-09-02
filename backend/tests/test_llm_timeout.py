"""_chat's per-purpose timeout.

Long-output calls (transcript_audit, weekly_synthesis) ask for 900-1200 tokens
— 4-6x the 200-300 the live gated-flow calls (question_gen/answer_eval) ask
for — so they get a longer read budget (LONG_TIMEOUT). Added after production
recording 3's audit kept failing with the identical error on every retry: a
flat 30s timeout applied to all purposes can never be fixed by retrying with
the SAME 30s budget when the real problem is "the model needed more time."
"""
import requests


def _ok(content):
    class R:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": content}}]}
    return R()


def test_short_calls_use_default_timeout(app, monkeypatch):
    seen = {}
    def fake_post(url, headers, json, timeout):
        seen['timeout'] = timeout
        return _ok("a probing question")
    monkeypatch.setattr(requests, "post", fake_post)
    app.llm.generate_question("some artifact text")
    assert seen['timeout'] == app.llm.TIMEOUT


def test_nemotron_super_disables_thinking_for_clean_verdicts(app, monkeypatch):
    seen = {}
    def fake_post(url, headers, json, timeout):
        seen['payload'] = json
        return _ok("a probing question")
    monkeypatch.setenv("EVAL_MODEL", "nvidia/nemotron-3-super-120b-a12b")
    monkeypatch.setattr(requests, "post", fake_post)
    app.llm.generate_question("some artifact text")
    assert seen['payload']['chat_template_kwargs'] == {"enable_thinking": False}


def test_transcript_audit_uses_long_timeout(app, monkeypatch):
    seen = {}
    def fake_post(url, headers, json, timeout):
        seen['timeout'] = timeout
        return _ok("audit text")
    monkeypatch.setattr(requests, "post", fake_post)
    app.llm.audit_transcript("some transcript text")
    assert seen['timeout'] == app.llm.LONG_TIMEOUT


def test_weekly_synthesis_uses_long_timeout(app, monkeypatch):
    seen = {}
    def fake_post(url, headers, json, timeout):
        seen['timeout'] = timeout
        return _ok("synthesis text")
    monkeypatch.setattr(requests, "post", fake_post)
    app.llm.weekly_synthesis("week markdown")
    assert seen['timeout'] == app.llm.LONG_TIMEOUT


def test_read_timeout_message_reports_elapsed_and_budget(app, monkeypatch):
    def fake_post(*a, **kw):
        raise requests.exceptions.ReadTimeout("boom")
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(app.llm.time, "sleep", lambda s: None)  # skip real backoff
    try:
        app.llm.audit_transcript("some transcript text")
        assert False, "expected LLMError"
    except app.llm.LLMError as e:
        msg = str(e)
        assert "ReadTimeout" in msg
        assert f"budget {app.llm.LONG_TIMEOUT}s" in msg  # proves LONG_TIMEOUT was applied
        assert "after" in msg


def test_read_timeout_exhausts_all_attempts_then_raises(app, monkeypatch):
    calls = []
    def fake_post(*a, **kw):
        calls.append(1)
        raise requests.exceptions.ReadTimeout("boom")
    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setattr(app.llm.time, "sleep", lambda s: None)
    try:
        app.llm.generate_question("artifact")
        assert False, "expected LLMError"
    except app.llm.LLMError:
        pass
    assert len(calls) == app.llm.RETRIES + 1
