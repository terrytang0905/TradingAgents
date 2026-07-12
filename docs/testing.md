# TradingAgents Testing Guide

Last updated: 2026-07-12.

## Offline Smoke Test

Use this before every commit. It validates risk limits, rate limiting, memory helpers, and the `TradingAgentsGraph.propagate()` pre-flight gate without requiring live market-data or broker credentials.

```bash
uv run pytest tests/test_risk_controller.py tests/test_risk_limits.py tests/test_pre_flight_check.py tests/test_rate_limiter.py tests/test_optimized_memory.py tests/test_trading_graph_preflight.py -q
```

Expected result: all selected tests pass.

## Full Local Test Suite

```bash
uv run pytest tests/ -q
```

Use this when changing graph orchestration, risk management, dataflow behavior, broker/MCP code, or dependency metadata.

## Online Integration Checks

Online checks can call paid or rate-limited services. Run them only when credentials are explicitly available and the target environment is clear.

Required environment variables depend on the feature being tested:

```bash
OPENAI_API_KEY=...
FINNHUB_API_KEY=...
ALPACA_API_KEY=...
ALPACA_SECRET_KEY=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets
POLYGON_API_KEY=...
```

Recommended sequence:

```bash
uv run python -m tradingagents.risk_management.pre_flight_check NVDA 2024-05-10
uv run tradingagents-api
uv run tradingagents-web
```

For broker work, use paper trading first. Do not point `ALPACA_BASE_URL` at a live trading endpoint until risk limits and order sizing have been independently reviewed.

## Runtime Data Separation

Keep generated data outside Git:

- `results/`, `eval_results/`, `eval_data/`, `outputs/`, and `reports/` are run outputs.
- `tradingagents/dataflows/data_cache/`, `data_cache/`, and `cache/` are market-data caches.
- `models/` and `checkpoints/` are model artifacts.
- `.claude/risk_logs/` contains local hook logs.

Use environment variables for writable paths when running long jobs:

```bash
TRADINGAGENTS_RESULTS_DIR=/path/to/runtime/results
TRADINGAGENTS_DATA_DIR=/path/to/runtime/data_cache
```
