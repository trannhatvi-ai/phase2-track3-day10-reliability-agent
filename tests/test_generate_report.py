from reliability_lab.config import CacheConfig, CircuitBreakerConfig, LabConfig, LoadTestConfig, ProviderConfig
from scripts.generate_report import build_report, cache_delta


def test_cache_delta_reports_absolute_delta_for_zero_baseline_rates() -> None:
    rows = cache_delta(
        without_cache={
            "latency_p50_ms": 100.0,
            "latency_p95_ms": 200.0,
            "estimated_cost": 1.0,
            "cache_hit_rate": 0.0,
        },
        with_cache={
            "latency_p50_ms": 10.0,
            "latency_p95_ms": 150.0,
            "estimated_cost": 0.5,
            "cache_hit_rate": 0.7,
        },
    )

    assert "| cache_hit_rate | 0.0 | 0.7 | +0.7000 |" in rows


def test_report_uses_completed_redis_evidence_wording() -> None:
    config = LabConfig(
        providers=[
            ProviderConfig(
                name="primary",
                fail_rate=0.0,
                base_latency_ms=200,
                cost_per_1k_tokens=0.004,
            )
        ],
        circuit_breaker=CircuitBreakerConfig(
            failure_threshold=3,
            reset_timeout_seconds=2,
            success_threshold=1,
        ),
        cache=CacheConfig(
            enabled=True,
            backend="memory",
            ttl_seconds=300,
            similarity_threshold=0.92,
        ),
        load_test=LoadTestConfig(requests=100),
    )
    metrics = {
        "availability": 1.0,
        "latency_p95_ms": 500.0,
        "fallback_success_rate": 1.0,
        "cache_hit_rate": 0.2,
        "recovery_time_ms": 2500.0,
        "scenarios": {"primary_timeout_100": "pass"},
    }

    report = build_report(metrics, config, without_cache=None, with_cache=None)

    assert "Redis verification is pending" not in report
    assert "tests/test_redis_cache.py" in report
