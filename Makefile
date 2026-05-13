.PHONY: test lint typecheck run-chaos cache-compare report clean docker-up docker-down

test:
	pytest -q

lint:
	ruff check src tests scripts

typecheck:
	mypy src

run-chaos:
	python scripts/run_chaos.py --config configs/default.yaml --out reports/metrics.json

cache-compare:
	python scripts/run_cache_comparison.py --config configs/default.yaml --out-dir reports

report:
	python scripts/generate_report.py --metrics reports/metrics.json --config configs/default.yaml --without-cache reports/cache_disabled_metrics.json --with-cache reports/cache_enabled_metrics.json --out reports/final_report.md

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache reports/metrics.json reports/cache_disabled_metrics.json reports/cache_enabled_metrics.json reports/final_report.md
