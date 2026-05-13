from __future__ import annotations

import json
import random
from pathlib import Path

from reliability_lab.cache import ResponseCache, SharedRedisCache
from reliability_lab.circuit_breaker import CircuitBreaker
from reliability_lab.config import LabConfig, ScenarioConfig
from reliability_lab.gateway import ReliabilityGateway
from reliability_lab.metrics import RunMetrics
from reliability_lab.providers import FakeLLMProvider


def load_queries(path: str | Path = "data/sample_queries.jsonl") -> list[str]:
    queries: list[str] = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        queries.append(json.loads(line)["query"])
    return queries


def build_gateway(config: LabConfig, provider_overrides: dict[str, float] | None = None) -> ReliabilityGateway:
    providers = []
    for p in config.providers:
        fail_rate = provider_overrides.get(p.name, p.fail_rate) if provider_overrides else p.fail_rate
        providers.append(FakeLLMProvider(p.name, fail_rate, p.base_latency_ms, p.cost_per_1k_tokens))
    breakers = {
        p.name: CircuitBreaker(
            name=p.name,
            failure_threshold=config.circuit_breaker.failure_threshold,
            reset_timeout_seconds=config.circuit_breaker.reset_timeout_seconds,
            success_threshold=config.circuit_breaker.success_threshold,
        )
        for p in config.providers
    }
    cache: ResponseCache | SharedRedisCache | None = None
    if config.cache.enabled:
        if config.cache.backend == "redis":
            cache = SharedRedisCache(
                config.cache.redis_url,
                config.cache.ttl_seconds,
                config.cache.similarity_threshold,
            )
        else:
            cache = ResponseCache(config.cache.ttl_seconds, config.cache.similarity_threshold)
    return ReliabilityGateway(providers, breakers, cache)


def calculate_recovery_time_ms(gateway: ReliabilityGateway) -> float | None:
    """Derive recovery time from circuit breaker transition logs.

    Recovery time = time between circuit opening and next successful close.
    Returns the average recovery time across all breakers, or None if no recovery occurred.
    """
    recovery_times: list[float] = []
    for breaker in gateway.breakers.values():
        open_ts: float | None = None
        for entry in breaker.transition_log:
            if entry["to"] == "open" and open_ts is None:
                open_ts = float(entry["ts"])
            elif entry["to"] == "closed" and open_ts is not None:
                recovery_times.append((float(entry["ts"]) - open_ts) * 1000)
                open_ts = None
    if not recovery_times:
        return None
    return sum(recovery_times) / len(recovery_times)


def scenario_runtime_config(config: LabConfig, scenario: ScenarioConfig) -> LabConfig:
    """Tune runtime config so each scenario exercises the intended reliability layer."""
    if scenario.name in {"primary_timeout_100", "primary_flaky_50", "all_healthy"}:
        return config.model_copy(update={"cache": config.cache.model_copy(update={"enabled": False})})
    if scenario.name == "cache_stale_candidate":
        return config.model_copy(
            update={
                "cache": config.cache.model_copy(
                    update={"enabled": True, "similarity_threshold": 0.3}
                )
            }
        )
    return config


def prompt_for_request(queries: list[str], scenario: ScenarioConfig, index: int) -> str:
    if scenario.name == "cache_stale_candidate":
        cache_probe_queries = [
            "Summarize refund policy for 2024 deadline",
            "Summarize refund policy for 2026 deadline",
        ]
        return cache_probe_queries[index % len(cache_probe_queries)]
    return random.choice(queries)


def scenario_passed(scenario: ScenarioConfig, metrics: RunMetrics) -> bool:
    if scenario.name == "primary_timeout_100":
        return (
            metrics.availability >= 0.8
            and metrics.fallback_success_rate >= 0.8
            and metrics.circuit_open_count > 0
        )
    if scenario.name == "primary_flaky_50":
        return metrics.availability >= 0.7 and (
            metrics.circuit_open_count > 0 or metrics.fallback_successes > 0
        )
    if scenario.name == "all_healthy":
        return metrics.availability >= 0.95 and metrics.static_fallbacks == 0
    if scenario.name == "cache_stale_candidate":
        return metrics.availability >= 0.95 and metrics.cache_false_hits > 0
    return metrics.successful_requests > 0


def run_scenario(config: LabConfig, queries: list[str], scenario: ScenarioConfig) -> RunMetrics:
    """Run a single named chaos scenario."""
    random.seed(20240513)
    runtime_config = scenario_runtime_config(config, scenario)
    gateway = build_gateway(runtime_config, scenario.provider_overrides or None)
    metrics = RunMetrics()
    request_count = runtime_config.load_test.requests
    for index in range(request_count):
        prompt = prompt_for_request(queries, scenario, index)
        result = gateway.complete(prompt)
        metrics.total_requests += 1
        metrics.estimated_cost += result.estimated_cost
        if result.cache_hit:
            metrics.cache_hits += 1
            metrics.estimated_cost_saved += 0.001
        if result.route.startswith("fallback:"):
            metrics.fallback_successes += 1
            metrics.successful_requests += 1
        elif result.route == "static_fallback":
            metrics.static_fallbacks += 1
            metrics.failed_requests += 1
        else:
            metrics.successful_requests += 1
        if result.latency_ms:
            metrics.latencies_ms.append(result.latency_ms)

    metrics.circuit_open_count = sum(
        1 for breaker in gateway.breakers.values() for t in breaker.transition_log if t["to"] == "open"
    )
    if gateway.cache is not None:
        metrics.cache_false_hits = len(gateway.cache.false_hit_log)
    metrics.recovery_time_ms = calculate_recovery_time_ms(gateway)
    return metrics


def run_simulation(config: LabConfig, queries: list[str]) -> RunMetrics:
    """Run all named scenarios from config, or a default run if none defined.

    TODO(student): Add a cache vs no-cache comparison scenario.
    Extend with your own custom scenarios (e.g., cost cap near limit).
    """
    if not config.scenarios:
        default_scenario = ScenarioConfig(name="default", description="baseline run")
        metrics = run_scenario(config, queries, default_scenario)
        metrics.scenarios = {"default": "pass" if metrics.successful_requests > 0 else "fail"}
        return metrics

    combined = RunMetrics()
    for scenario in config.scenarios:
        result = run_scenario(config, queries, scenario)

        passed = scenario_passed(scenario, result)
        combined.scenarios[scenario.name] = "pass" if passed else "fail"

        combined.total_requests += result.total_requests
        combined.successful_requests += result.successful_requests
        combined.failed_requests += result.failed_requests
        combined.fallback_successes += result.fallback_successes
        combined.static_fallbacks += result.static_fallbacks
        combined.cache_hits += result.cache_hits
        combined.cache_false_hits += result.cache_false_hits
        combined.circuit_open_count += result.circuit_open_count
        combined.estimated_cost += result.estimated_cost
        combined.estimated_cost_saved += result.estimated_cost_saved
        combined.latencies_ms.extend(result.latencies_ms)
        if result.recovery_time_ms is not None:
            if combined.recovery_time_ms is None:
                combined.recovery_time_ms = result.recovery_time_ms
            else:
                combined.recovery_time_ms = (combined.recovery_time_ms + result.recovery_time_ms) / 2

    return combined
