# TradingAgents: Multi-Agent Quantitative Trading Framework

> Harness Engineering 升级版 — 生产部署级量化Agent系统

## MUST READ FIRST

- `tradingagents/default_config.py` — 所有可配置参数定义
- `tradingagents/agents/AGENTS.md` — 创建新Agent前必读
- `tradingagents/risk_management/AGENTS.md` — 风控约束前必读

## Critical Gotchas (IMPORTANT)

- **IMPORTANT**: Never call `propagate()` without pre-flight risk check passing
- **IMPORTANT**: Use `create_msg_delete()` after each analyst node to prevent context explosion
- **IMPORTANT**: ChromaDB memory is session-scoped; call `.persist()` before exit to save
- **IMPORTANT**: `online_tools=True` uses real API calls; set `False` for cached data

## Configuration Quick Reference

| Parameter | Default | CLI Override | Config Override |
|-----------|---------|--------------|-----------------|
| `deep_think_llm` | `o4-mini` | `--model` | `config["deep_think_llm"]` |
| `quick_think_llm` | `gpt-4o-mini` | `--quick-model` | `config["quick_think_llm"]` |
| `max_debate_rounds` | `1` | `--debate-rounds` | `config["max_debate_rounds"]` |
| `max_risk_discuss_rounds` | `1` | `--risk-rounds` | `config["max_risk_discuss_rounds"]` |
| `online_tools` | `True` | `--offline` | `config["online_tools"]=False` |

## Testing

```bash
pytest tests/ -v                              # Full test suite
pytest tests/test_risk_controller.py -v       # Risk module only
pytest tests/test_optimized_memory.py -v      # Memory module only
```

## Branch Naming Convention

- `feat/<agent-type>-enhancement` — New agent features
- `fix/<component>-bug` — Bug fixes
- `refactor/<module>` — Refactoring
- `harness/<layer>-upgrade` — Harness Engineering upgrades

## Key Architecture Components

| Component | Location | Purpose |
|-----------|----------|---------|
| TradingAgentsGraph | `graph/trading_graph.py` | Main orchestrator |
| AgentState | `agents/utils/agent_states.py` | State TypedDict definitions |
| FinancialSituationMemory | `agents/utils/memory.py` | ChromaDB reflection storage |
| Toolkit | `agents/utils/agent_utils.py` | Data API tool definitions |
| ConditionalLogic | `graph/conditional_logic.py` | Graph flow routing |

## Detailed Layer Docs (按需加载)

- Agents layer: `@tradingagents/agents/AGENTS.md`
- Dataflows layer: `@tradingagents/dataflows/AGENTS.md`
- Graph layer: `@tradingagents/graph/AGENTS.md`
- Risk management: `@tradingagents/risk_management/AGENTS.md`
- Monitoring: `@tradingagents/monitoring/AGENTS.md`

## Workflow Quick Start

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# Initialize with default config
ta = TradingAgentsGraph(debug=True, config=DEFAULT_CONFIG.copy())

# Run single ticker analysis
state, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)

# Reflect and learn after returns are known
ta.reflect_and_remember(returns_losses=0.15)  # 15% gain
```

## Harness Engineering Layers

| Layer | Status | Description |
|-------|--------|-------------|
| L1 AGENTS.md | ✅ Active | This file + subdirectory docs |
| L2 Hooks | ✅ Active | Pre-flight risk check + rate limiter |
| L3 Skills | 📋 Planned | Strategy templates |
| L4 Plugin | 📋 Planned | Team distribution |
| L5 MCP | 📋 Planned | Broker API integration |

## Risk Limits (Enforced by Hooks)

| Limit | Default | Config Key |
|-------|---------|------------|
| Max position per symbol | 10% | `max_position_per_symbol` |
| Max daily trades | 50 | `max_daily_trades` |
| Max portfolio exposure | 80% | `max_portfolio_exposure` |
| Min API quota reserve | 100 calls | `min_api_quota_reserve` |

## API Rate Limits (Protected by Hooks)

| API | RPM Limit | TPM Limit |
|-----|-----------|-----------|
| OpenAI Chat | 500 | 200,000 |
| OpenAI Embedding | 100 | — |
| FinnHub | 60 | — |
| YFinance | 2,000 | — |