"""Riva offline_recognize retry/timeout policy.

Only the FIRST attempt gets the full _RIVA_TIMEOUT (120s) — justified by real
NVIDIA RTFX benchmarks (see transcribe.py's comment: RTFX 60-90x means even an
8-minute recording needs only ~3-8s of compute, so 120s is already 15x+
headroom). Retries use the shorter _RIVA_RETRY_TIMEOUT: a first attempt that
needed anywhere near 120s is already an anomaly, and re-waiting the same long
budget twice more just triples a multi-minute wait for a request unlikely to
succeed — the same mistake fixed in llm.py's TIMEOUT/LONG_TIMEOUT split.
"""
import time

import grpc

import transcribe as tr


class _FakeFuture:
    def __init__(self, behavior):
        self.behavior = behavior  # callable(timeout) -> result, or raises

    def result(self, timeout):
        return self.behavior(timeout)


class _FakeSvc:
    def __init__(self, behaviors):
        self.behaviors = list(behaviors)
        self.calls = 0

    def offline_recognize(self, data, config, future=True):
        self.calls += 1
        return _FakeFuture(self.behaviors.pop(0))


class _FakeRpcError(grpc.RpcError):
    def __init__(self, code, details="boom"):
        self._code, self._details = code, details

    def code(self):
        return self._code

    def details(self):
        return self._details


def _timeout_behavior(timeout):
    raise grpc.FutureTimeoutError()


def test_first_attempt_gets_full_budget_retries_get_shorter_one(monkeypatch):
    seen = []
    def behavior(timeout):
        seen.append(timeout)
        raise grpc.FutureTimeoutError()
    svc = _FakeSvc([behavior, behavior, behavior])
    monkeypatch.setattr(tr, "_riva_service", lambda: svc)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    try:
        tr._offline_recognize(b"data", None)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    assert seen == [tr._RIVA_TIMEOUT, tr._RIVA_RETRY_TIMEOUT, tr._RIVA_RETRY_TIMEOUT]
    assert svc.calls == tr._RIVA_RETRIES + 1


def test_timeout_error_message_reports_elapsed_and_budget(monkeypatch):
    svc = _FakeSvc([_timeout_behavior, _timeout_behavior, _timeout_behavior])
    monkeypatch.setattr(tr, "_riva_service", lambda: svc)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    try:
        tr._offline_recognize(b"data", None)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        msg = str(e)
        assert "timed out after" in msg
        assert f"budget {tr._RIVA_RETRY_TIMEOUT}s" in msg  # last attempt's budget


def test_success_on_first_attempt_makes_only_one_call(monkeypatch):
    svc = _FakeSvc([lambda timeout: "a real transcript result"])
    monkeypatch.setattr(tr, "_riva_service", lambda: svc)
    result = tr._offline_recognize(b"data", None)
    assert result == "a real transcript result"
    assert svc.calls == 1


def test_transient_rpc_error_retries_all_attempts(monkeypatch):
    def behavior(timeout):
        raise _FakeRpcError(grpc.StatusCode.UNAVAILABLE)
    svc = _FakeSvc([behavior, behavior, behavior])
    monkeypatch.setattr(tr, "_riva_service", lambda: svc)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    try:
        tr._offline_recognize(b"data", None)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "transient UNAVAILABLE" in str(e)
    assert svc.calls == tr._RIVA_RETRIES + 1


def test_non_transient_rpc_error_raises_immediately(monkeypatch):
    def behavior(timeout):
        raise _FakeRpcError(grpc.StatusCode.INVALID_ARGUMENT, "bad audio")
    svc = _FakeSvc([behavior, behavior, behavior])
    monkeypatch.setattr(tr, "_riva_service", lambda: svc)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    try:
        tr._offline_recognize(b"data", None)
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "INVALID_ARGUMENT" in str(e) and "bad audio" in str(e)
    assert svc.calls == 1  # no retry — retrying a permanent error can't help
