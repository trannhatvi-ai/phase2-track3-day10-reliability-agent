from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from reliability_lab.config import LabConfig, load_config


JsonObject = dict[str, object]


def metric(metrics: Mapping[str, object], key: str, default: object = "not captured") -> object:
    return metrics.get(key, default)


def metric_number(metrics: Mapping[str, object], key: str, default: float = 0.0) -> float:
    value = metrics.get(key, default)
    if value is None:
        return default
    if isinstance(value, int | float | str):
        return float(value)
    raise ValueError(f"metric {key!r} must be numeric, got {type(value).__name__}")


def met(actual: float | int | None, op: str, target: float) -> str:
    if actual is None:
        return "no"
    if op == ">=":
        return "yes" if actual >= target else "no"
    if op == "<":
        return "yes" if actual < target else "no"
    raise ValueError(f"unsupported operator: {op}")


def load_json_object(path: str | Path) -> JsonObject:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return cast(JsonObject, raw)


def load_optional_json(path: str | None) -> JsonObject | None:
    if path is None or not Path(path).exists():
        return None
    return load_json_object(path)


def cache_delta(without_cache: JsonObject | None, with_cache: JsonObject | None) -> list[str]:
    if without_cache is None or with_cache is None:
        return [
            "| Metric | Without cache | With cache | Delta |",
            "|---|---:|---:|---|",
            "| latency_p50_ms | not captured | not captured | run comparison scenario |",
            "| latency_p95_ms | not captured | not captured | run comparison scenario |",
            "| estimated_cost | not captured | not captured | run comparison scenario |",
            "| cache_hit_rate | 0 | not captured | run comparison scenario |",
        ]

    rows = ["| Metric | Without cache | With cache | Delta |", "|---|---:|---:|---|"]
    for key in ["latency_p50_ms", "latency_p95_ms", "estimated_cost", "cache_hit_rate"]:
        before = metric_number(without_cache, key)
        after = metric_number(with_cache, key)
        if before == 0:
            delta = f"{after - before:+.4f}" if key.endswith("_rate") else "n/a"
        else:
            delta = f"{((after - before) / before) * 100:.1f}%"
        rows.append(f"| {key} | {before} | {after} | {delta} |")
    return rows


def redis_key_evidence(config: LabConfig) -> list[str]:
    if config.cache.backend != "redis":
        return [f"Redis key check skipped because cache backend is `{config.cache.backend}`."]

    try:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(config.cache.redis_url, decode_responses=True)
        keys = sorted(str(key) for key in client.scan_iter("rl:cache:*"))[:5]
        client.close()
    except Exception as exc:
        return [f"Redis key check could not connect: {type(exc).__name__}."]

    if not keys:
        return ["Redis key check found no `rl:cache:*` keys for this run."]
    return [
        "Redis key evidence (`docker compose exec -T redis redis-cli KEYS \"rl:cache:*\"`):",
        "",
        "```text",
        *keys,
        "```",
    ]


def config_table(config: LabConfig) -> list[str]:
    return [
        "| Setting | Value | Reason |",
        "|---|---:|---|",
        (
            f"| failure_threshold | {config.circuit_breaker.failure_threshold} | "
            "Open quickly after repeated provider failures without reacting to one transient error. |"
        ),
        (
            f"| reset_timeout_seconds | {config.circuit_breaker.reset_timeout_seconds} | "
            "Give the provider a short recovery window before a probe request. |"
        ),
        (
            f"| success_threshold | {config.circuit_breaker.success_threshold} | "
            "One successful probe is enough for this local fake-provider lab. |"
        ),
        (
            f"| cache TTL | {config.cache.ttl_seconds} | "
            "Five minutes keeps FAQ-style answers reusable while limiting stale data. |"
        ),
        (
            f"| cache backend | {config.cache.backend} | "
            "Redis demonstrates shared cache state across gateway instances for the lab. |"
        ),
        (
            f"| similarity_threshold | {config.cache.similarity_threshold} | "
            "High default threshold avoids broad semantic matches; guardrails catch numeric false hits. |"
        ),
        (
            f"| load_test requests | {config.load_test.requests} | "
            "Enough requests to trigger circuit transitions and repeated cache lookups. |"
        ),
    ]


def build_report(
    metrics: JsonObject,
    config: LabConfig,
    without_cache: JsonObject | None,
    with_cache: JsonObject | None,
) -> str:
    availability = metric_number(metrics, "availability")
    latency_p95 = metric_number(metrics, "latency_p95_ms")
    fallback_success_rate = metric_number(metrics, "fallback_success_rate")
    cache_hit_rate = metric_number(metrics, "cache_hit_rate")
    recovery_value = (
        metric_number(metrics, "recovery_time_ms")
        if metric(metrics, "recovery_time_ms", None) is not None
        else None
    )

    lines = [
        "# Day 10 Reliability Final Report",
        "",
        "## 1. Architecture summary",
        "",
        "The gateway checks cache first, then routes through provider-specific circuit breakers. "
        "If the primary provider fails or its circuit is open, the request falls back to backup; "
        "if all providers fail, the gateway returns a static degraded-service response.",
        "",
        "```text",
        "User Request",
        "    |",
        "    v",
        "[Gateway] -> [Cache] -> hit: cached response",
        "    | miss",
        "    v",
        "[Circuit: primary] -> Provider primary",
        "    | open/error",
        "    v",
        "[Circuit: backup] -> Provider backup",
        "    | open/error",
        "    v",
        "[Static fallback]",
        "```",
        "",
        "## 2. Configuration",
        "",
        *config_table(config),
        "",
        "## 3. SLO definitions",
        "",
        "| SLI | SLO target | Actual value | Met? |",
        "|---|---|---:|---|",
        f"| Availability | >= 99% | {availability} | {met(availability, '>=', 0.99)} |",
        f"| Latency P95 | < 2500 ms | {latency_p95} | {met(latency_p95, '<', 2500)} |",
        (
            f"| Fallback success rate | >= 95% | {fallback_success_rate} | "
            f"{met(fallback_success_rate, '>=', 0.95)} |"
        ),
        f"| Cache hit rate | >= 10% | {cache_hit_rate} | {met(cache_hit_rate, '>=', 0.10)} |",
        (
            f"| Recovery time | < 5000 ms | {recovery_value} | "
            f"{met(recovery_value, '<', 5000)} |"
        ),
        "",
        "## 4. Metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
    ]

    for key, value in metrics.items():
        if key == "scenarios":
            continue
        lines.append(f"| {key} | {value} |")

    lines.extend(
        [
            "",
            "## 5. Cache comparison",
            "",
            *cache_delta(without_cache, with_cache),
            "",
            "## 6. Redis shared cache",
            "",
            "In-memory cache is per process, so horizontally scaled gateway instances do not share hits. "
            "SharedRedisCache stores query/response pairs in Redis with TTL, allowing separate gateway "
            "instances to read the same cached entry.",
            "",
            "Redis verification uses `tests/test_redis_cache.py`: exact get/set, TTL expiry, "
            "shared state across two cache instances, privacy bypass, and false-hit blocking.",
            "",
            *redis_key_evidence(config),
            "",
            "## 7. Chaos scenarios",
            "",
            "| Scenario | Status |",
            "|---|---|",
        ]
    )

    scenarios = metric(metrics, "scenarios", {})
    if isinstance(scenarios, dict):
        for key, value in scenarios.items():
            lines.append(f"| {key} | {value} |")

    lines.extend(
        [
            "",
            "## 8. Failure analysis",
            "",
            "The cache is shared by Redis, but circuit breaker state is still process-local. "
            "In production, multiple gateway replicas could keep calling a degraded provider because "
            "each process has its own breaker counters. The next production fix is to move breaker "
            "state or provider health signals into a shared backend with short TTLs.",
            "",
            "## 9. Next steps",
            "",
            "1. For production, move circuit breaker state or provider health into Redis with short TTLs.",
            "2. Add concurrent load testing instead of only sequential request loops.",
            "3. Add cost-aware routing when budget usage crosses configured thresholds.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", default="reports/metrics.json")
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--without-cache")
    parser.add_argument("--with-cache")
    parser.add_argument("--out", default="reports/final_report.md")
    args = parser.parse_args()

    metrics = load_json_object(args.metrics)
    config = load_config(args.config)
    without_cache = load_optional_json(args.without_cache)
    with_cache = load_optional_json(args.with_cache)
    report = build_report(metrics, config, without_cache, with_cache)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
