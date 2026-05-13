import time

import pytest

from reliability_lab.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


def test_circuit_opens_then_recovers_after_successful_probe() -> None:
    breaker = CircuitBreaker(
        "primary",
        failure_threshold=2,
        reset_timeout_seconds=0.01,
        success_threshold=1,
    )

    breaker.record_failure()
    assert breaker.state == CircuitState.CLOSED

    breaker.record_failure()
    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow_request()

    time.sleep(0.02)
    assert breaker.allow_request()
    assert breaker.state == CircuitState.HALF_OPEN

    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED
    assert breaker.failure_count == 0
    assert [t["to"] for t in breaker.transition_log] == ["open", "half_open", "closed"]


def test_half_open_failure_reopens_immediately() -> None:
    breaker = CircuitBreaker("primary", failure_threshold=1, reset_timeout_seconds=0.01)

    breaker.record_failure()
    time.sleep(0.02)
    assert breaker.allow_request()

    breaker.record_failure()

    assert breaker.state == CircuitState.OPEN
    assert not breaker.allow_request()
    assert breaker.transition_log[-1]["reason"] == "probe_failure"


def test_open_circuit_call_fails_fast_without_running_function() -> None:
    breaker = CircuitBreaker("primary", failure_threshold=1, reset_timeout_seconds=60)
    breaker.record_failure()
    called = False

    def provider_call() -> str:
        nonlocal called
        called = True
        return "ok"

    with pytest.raises(CircuitOpenError):
        breaker.call(provider_call)

    assert called is False
