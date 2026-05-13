from __future__ import annotations

import argparse
from pathlib import Path

from reliability_lab.chaos import load_queries, run_scenario
from reliability_lab.config import LabConfig, ScenarioConfig, load_config


def healthy_provider_config(config: LabConfig) -> LabConfig:
    providers = [provider.model_copy(update={"fail_rate": 0.0}) for provider in config.providers]
    return config.model_copy(update={"providers": providers, "scenarios": []})


def cache_config(config: LabConfig, enabled: bool) -> LabConfig:
    return config.model_copy(update={"cache": config.cache.model_copy(update={"enabled": enabled})})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out-dir", default="reports")
    args = parser.parse_args()

    base_config = healthy_provider_config(load_config(args.config))
    queries = load_queries()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    disabled = run_scenario(
        cache_config(base_config, enabled=False),
        queries,
        ScenarioConfig(name="cache_disabled", description="Healthy providers without cache"),
    )
    enabled = run_scenario(
        cache_config(base_config, enabled=True),
        queries,
        ScenarioConfig(name="cache_enabled", description="Healthy providers with cache"),
    )

    disabled.write_json(out_dir / "cache_disabled_metrics.json")
    enabled.write_json(out_dir / "cache_enabled_metrics.json")
    print(f"wrote {out_dir / 'cache_disabled_metrics.json'}")
    print(f"wrote {out_dir / 'cache_enabled_metrics.json'}")


if __name__ == "__main__":
    main()
