import time

from reliability_lab.cache import ResponseCache


def test_memory_cache_exact_hit_returns_score_one() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.8)

    cache.set("hello world", "cached response")

    cached, score = cache.get("hello world")
    assert cached == "cached response"
    assert score == 1.0


def test_memory_cache_skips_privacy_sensitive_queries() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.5)

    cache.set("account balance for user 123", "Balance: $500")

    cached, score = cache.get("account balance for user 123")
    assert cached is None
    assert score == 0.0


def test_memory_cache_logs_and_blocks_false_hit_for_different_years() -> None:
    cache = ResponseCache(ttl_seconds=60, similarity_threshold=0.3)

    cache.set("Summarize refund policy for 2024 deadline", "Old refund policy")

    cached, score = cache.get("Summarize refund policy for 2026 deadline")
    assert cached is None
    assert score >= cache.similarity_threshold
    assert cache.false_hit_log


def test_memory_cache_expires_entries_after_ttl() -> None:
    cache = ResponseCache(ttl_seconds=1, similarity_threshold=0.8)

    cache.set("short lived", "cached response")
    time.sleep(1.1)

    cached, _ = cache.get("short lived")
    assert cached is None
