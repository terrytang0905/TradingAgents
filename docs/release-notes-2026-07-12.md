# TradingAgents Review Fix Baseline

Date: 2026-07-12.

## Scope

This baseline captures the code-review remediation and engineering hardening work for TradingAgents:

- Risk pre-flight gate before graph propagation.
- Risk limit and risk controller modules.
- API rate limiting and monitoring helpers.
- Resilient data toolkit support.
- Web UI and FastAPI entry points.
- Broker and MCP integration scaffolding.
- Backtest engine scaffolding.
- Project-local agent instructions, skills, and hook configuration.
- Offline tests for risk controls, rate limiting, optimized memory, and graph pre-flight behavior.

## Dependency Metadata

- `pyproject.toml` defines core runtime dependencies plus `dev`, `broker`, and `mcp` extras.
- `requirements.txt` is a complete local development/runtime install list.
- `uv.lock` has been refreshed from `pyproject.toml`.

## Verification

Primary offline smoke command:

```bash
uv run pytest tests/test_risk_controller.py tests/test_risk_limits.py tests/test_pre_flight_check.py tests/test_rate_limiter.py tests/test_optimized_memory.py tests/test_trading_graph_preflight.py -q
```

Online checks are documented in `docs/testing.md` and require explicit credentials.
