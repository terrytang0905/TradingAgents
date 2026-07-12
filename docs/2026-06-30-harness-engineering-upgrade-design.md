# TradingAgents Harness Engineering 升级设计

> 从研究框架升级为生产部署级量化Agent系统，完整五层架构覆盖配置管理、安全约束、组件复用、团队协作、外部集成。

## 一、现状痛点分析

| 痛点 | 当前状态 | 升级目标 |
|------|---------|---------|
| **配置散乱** | `default_config.py` + 环境变量 + CLI参数混杂 | L1 CLAUDE.md 分层策略，统一配置入口 |
| **缺乏安全约束** | 无风险限额检查、无API rate limit | L2 Hooks 硬性约束，零例外执行 |
| **Agent复用困难** | 每个 Agent 函数需从头编写 | L3 Skills 渐进披露，策略模板化 |
| **上下文溢出** | 复杂回测任务易超 context window | Subagent 隔离 + MCP 外部计算 |
| **无外部集成** | 仅模拟交易，无券商API | L5 MCP Servers 连接实盘接口 |

---

## 二、五层扩展栈升级方案

### L1: CLAUDE.md 分层策略

**核心原则：全局精简 + 局部详细**

```
TradingAgents/
├── CLAUDE.md                    ← 项目入口指引（≤50行）
├── tradingagents/
│   ├── agents/
│   │   └── CLAUDE.md            ← Agent层约定：创建规范、接口定义
│   ├── dataflows/
│   │   └── CLAUDE.md            ← 数据层约定：API调用、缓存策略
│   ├── graph/
│   │   └── CLAUDE.md            ← 图层约定：节点添加、边定义
│   └── risk_management/
│   │   └── CLAUDE.md            ← 风控层约定：限额、止损逻辑
│   └── CLAUDE.md                ← 核心模块约定：配置、初始化
├── .claude/
│   └── CLAUDE.md                ← Claude Code 项目级偏好（可选）
└── ~/.claude/CLAUDE.md          ← 用户全局偏好（已存在）
```

**根目录 CLAUDE.md 示例（精简版）**：

```markdown
# TradingAgents: Multi-Agent Quantitative Trading Framework

## MUST READ FIRST
- `tradingagents/default_config.py` for all configurable parameters
- `tradingagents/agents/CLAUDE.md` before creating new agents

## Critical Gotchas
- **IMPORTANT**: Never call `propagate()` without risk limits check
- **IMPORTANT**: Use `create_msg_delete()` after each analyst node to prevent context explosion
- **IMPORTANT**: ChromaDB memory is session-scoped; persist with `.persist()` before exit

## Configuration
| Parameter | Default | Override Method |
|-----------|---------|-----------------|
| `deep_think_llm` | `o4-mini` | CLI `--model` or config dict |
| `quick_think_llm` | `gpt-4o-mini` | CLI `--quick-model` |
| `max_debate_rounds` | `1` | CLI `--debate-rounds` |
| `online_tools` | `True` | CLI `--offline` to disable |

## Testing
```bash
pytest tests/ -v                              # Full test suite
pytest tests/test_risk_controller.py -v       # Risk module only
```

## Branch Naming
- `feat/<agent-type>-enhancement`  # New agent features
- `fix/<component>-bug`            # Bug fixes
- `refactor/<module>`              # Refactoring

## See Detailed Docs
- Agents: `@tradingagents/agents/CLAUDE.md`
- Data: `@tradingagents/dataflows/CLAUDE.md`
- Graph: `@tradingagents/graph/CLAUDE.md`
```

**子目录 CLAUDE.md 示例（agents层）**：

```markdown
# TradingAgents Agents Layer

## Agent Creation Pattern

All agents follow factory function pattern:
```python
def create_<agent_name>(llm, memory=None) -> callable:
    def node(state) -> dict:
        # 1. Extract needed state fields
        # 2. Get past memories if memory exists
        # 3. Build prompt with context + memories
        # 4. Invoke LLM
        # 5. Return state update dict
    return node
```

## State Interface Contract
- Input: `AgentState` (TypedDict in `utils/agent_states.py`)
- Output: Dict with keys matching `AgentState` fields
- **IMPORTANT**: Always include `investment_debate_state["count"] + 1` for debate agents

## Memory Integration
```python
curr_situation = f"{market_report}\n{sentiment_report}\n{news_report}\n{fundamentals_report}"
past_memories = memory.get_memories(curr_situation, n_matches=2)
```

## Adding New Analyst
1. Create `analysts/<new_analyst>.py` with `create_<new_analyst>()`
2. Add to `agents/__init__.py` exports
3. Register tool node in `TradingAgentsGraph._create_tool_nodes()`
4. Add conditional logic in `conditional_logic.py`
5. Update `setup.py` graph construction
```

---

### L2: Hooks 设计（安全约束层）

**核心原则：确定性约束，零例外执行**

```json
// .claude/settings.json
{
  "hooks": {
    // 1. 风险限额强制检查
    "PreToolUse": [{
      "matcher": "TradingAgentsGraph.propagate",
      "hooks": [{
        "type": "command",
        "command": "python -m tradingagents.risk_management.pre_flight_check $CLAUDE_TICKER $CLAUDE_DATE"
      }]
    }],

    // 2. API Rate Limit 保护
    "PostToolUse": [{
      "matcher": "Toolkit.get_*",
      "hooks": [{
        "type": "command",
        "command": "python -m tradingagents.monitoring.rate_limiter.log_call"
      }]
    }],

    // 3. 代码格式强制
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{
        "type": "command",
        "command": "ruff check --fix $CLAUDE_FILE && ruff format $CLAUDE_FILE"
      }]
    }],

    // 4. 提交前测试门控
    "PreCommit": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "pytest tests/test_risk_controller.py -v --tb=short"
      }]
    }]
  }
}
```

**风控 Pre-flight Check 实现**：

```python
# tradingagents/risk_management/pre_flight_check.py

import sys
from tradingagents.risk_management.risk_limits import RiskLimits

def main(ticker: str, trade_date: str):
    """Pre-flight risk check before propagate()"""
    limits = RiskLimits.load_from_config()

    # Check 1: Position limit
    current_positions = limits.get_current_positions()
    if ticker in current_positions and current_positions[ticker] >= limits.max_position_per_symbol:
        print(f"BLOCKED: {ticker} position limit reached ({limits.max_position_per_symbol})")
        sys.exit(1)

    # Check 2: Daily trade count
    today_trades = limits.get_trades_count(trade_date)
    if today_trades >= limits.max_daily_trades:
        print(f"BLOCKED: Daily trade limit reached ({limits.max_daily_trades})")
        sys.exit(1)

    # Check 3: Portfolio exposure
    total_exposure = limits.calculate_total_exposure()
    if total_exposure >= limits.max_portfolio_exposure:
        print(f"BLOCKED: Portfolio exposure limit ({limits.max_portfolio_exposure})")
        sys.exit(1)

    # Check 4: API quota
    api_quota = limits.get_api_quota_remaining()
    if api_quota < limits.min_api_quota_reserve:
        print(f"BLOCKED: API quota reserve depleted ({api_quota} remaining)")
        sys.exit(1)

    print(f"PASS: Risk checks cleared for {ticker} on {trade_date}")
    sys.exit(0)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

**Rate Limiter 实现**：

```python
# tradingagents/monitoring/rate_limiter.py

import time
import json
from pathlib import Path
from collections import defaultdict

class RateLimiter:
    """Protect API calls from exceeding rate limits"""

    LIMITS = {
        "openai_chat": {"rpm": 500, "tpm": 200000},
        "openai_embedding": {"rpm": 100},
        "finnhub": {"rpm": 60},
        "yfinance": {"rpm": 2000},
    }

    call_history = defaultdict(list)
    log_file = Path(".claude/api_calls.log")

    @classmethod
    def log_call(cls, api_type: str):
        """Log API call and check rate limit"""
        now = time.time()
        cls.call_history[api_type].append(now)

        # Trim history to last minute
        cls.call_history[api_type] = [
            t for t in cls.call_history[api_type] if now - t < 60
        ]

        # Check limit
        rpm = cls.LIMITS.get(api_type, {}).get("rpm", 1000)
        if len(cls.call_history[api_type]) >= rpm * 0.9:  # 90% warning threshold
            print(f"WARNING: {api_type} approaching rate limit ({len(cls.call_history[api_type])}/{rpm} rpm)")

        # Persist log
        cls.log_file.write_text(json.dumps({
            "timestamp": now,
            "api_type": api_type,
            "count_last_minute": len(cls.call_history[api_type])
        }) + "\n", append=True)
```

---

### L3: Skills 渐进披露（Agent复用层）

**目录结构**：

```
.claude/skills/
├── trading-strategy/
│   ├── SKILL.md                  ← 核心触发规则（≤100行）
│   ├── references/
│   │   ├── bull_bear_template.md ← Bull/Bear辩论prompt模板
│   │   ├── risk_triangle.md      ← 风险三角辩论模板
│   │   └── decision_output.md    ← 决策输出格式标准
│   └── tests/
│       ├── should-trigger.md     ← 触发条件测试
│       └── shouldnt-trigger.md   ← 不触发条件测试
├── backtest-runner/
│   ├── SKILL.md
│   ├── references/
│   │   ├── backtrader_config.md
│   │   └── performance_metrics.md
│   └── templates/
│       └── strategy_template.py  ← 策略代码模板
├── risk-analysis/
│   ├── SKILL.md
│   └── references/
│       ├── risk_metrics.md
│       └── stop_loss_rules.md
└── data-collection/
    ├── SKILL.md
    └── references/
        ├── api_endpoints.md
        ├── cache_strategy.md
```

**trading-strategy/SKILL.md 示例**：

```markdown
---
name: trading-strategy
description: 创建新交易策略Agent，基于现有模板快速定制
origin: custom
---

# Trading Strategy Skill

## When to Activate
- 用户提及"新策略"、"添加Agent"、"创建分析师"
- 用户描述交易逻辑意图（如"我要一个动量策略Agent"）
- 需要复用现有辩论/决策模式

手动调用：`/trading-strategy` 或 `/新策略`

## Strategy Templates

### 1. Analyst Agent
```python
# Template: analysts/<name>_analyst.py
def create_<name>_analyst(llm, toolkit):
    def node(state) -> dict:
        # Standard: extract state → build prompt → invoke → return
        ...
    return node
```
See `@references/analyst_template.md` for full code.

### 2. Debater Agent
- Bull/Bear: `@references/bull_bear_template.md`
- Risk Triangle: `@references/risk_triangle.md`

### 3. Decision Agent
- Trader: `@references/trader_template.md`
- Risk Manager: `@references/risk_manager_template.md`

## Adding New Strategy Workflow
1. 确定策略类型（Analyst/Debater/Decision）
2. 加载对应模板：`/trading-strategy <type>`
3. 填写prompt定制部分
4. 运行测试：`pytest tests/test_<name>_analyst.py`
5. 注册到graph：按 `@tradingagents/graph/CLAUDE.md` 流程

## Output Format
All decision outputs must follow `@references/decision_output.md`:
```
FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**
CONFIDENCE: HIGH/MEDIUM/LOW
POSITION_SIZE: <percentage of portfolio>
STOP_LOSS: <price or percentage>
TARGET_PRICE: <price>
RATIONALE: <bullet points>
```
```

---

### L4: Plugin 打包（团队协作层）

**Plugin 结构**：

```
tradingagents-plugin/
├── manifest.json              ← 安装清单
├── skills/                    ← 技能定义
│   ├── trading-strategy/
│   ├── backtest-runner/
│   └── risk-analysis/
├── agents/                    ← 子智能体定义
│   ├── market-screener.md
│   ├── portfolio-optimizer.md
│   └── execution-monitor.md
├── hooks/                     ← 钩子配置
│   └── settings.json
├── mcp/                       ← MCP服务器配置
│   ├── brokers/
│   │   └── alpaca-mcp.json
│   └── data/
│       └── polygon-mcp.json
└── templates/                 ← 代码模板
    ├── agent_factory.py
    └── strategy_skeleton.py
```

**manifest.json 示例**：

```json
{
  "name": "tradingagents-enterprise",
  "version": "1.0.0",
  "description": "Production-ready TradingAgents with Harness Engineering",
  "author": "Your Team",
  "skills": [
    "trading-strategy",
    "backtest-runner",
    "risk-analysis",
    "data-collection"
  ],
  "agents": [
    "market-screener",
    "portfolio-optimizer",
    "execution-monitor"
  ],
  "hooks": {
    "pre_flight_check": true,
    "rate_limiter": true,
    "format_enforcer": true
  },
  "mcp_servers": [
    "alpaca-broker",
    "polygon-data"
  ],
  "compatibility": {
    "claude_code": ">=0.5.0",
    "python": ">=3.10"
  }
}
```

---

### L5: MCP Servers（外部集成层）

**券商API MCP（Alpaca示例）**：

```python
# mcp_servers/alpaca_mcp.py

from mcp.server import Server
from mcp.types import Tool, TextContent
import alpaca_trade_api as tradeapi

class AlpacaBrokerMCP(Server):
    """MCP server for Alpaca broker integration"""

    def __init__(self, api_key, secret_key, base_url):
        self.api = tradeapi.REST(api_key, secret_key, base_url)
        super().__init__("alpaca-broker")

    @Tool
    async def get_account(self) -> TextContent:
        """Get account info: balance, positions, buying power"""
        account = self.api.get_account()
        return TextContent(type="text", text=json.dumps({
            "cash": account.cash,
            "portfolio_value": account.portfolio_value,
            "buying_power": account.buying_power,
            "positions_count": len(self.api.list_positions())
        }))

    @Tool
    async def get_positions(self) -> TextContent:
        """List all open positions"""
        positions = self.api.list_positions()
        return TextContent(type="text", text=json.dumps([
            {"symbol": p.symbol, "qty": p.qty, "market_value": p.market_value}
            for p in positions
        ]))

    @Tool
    async def submit_order(
        symbol: str,
        qty: int,
        side: str,  # "buy" or "sell"
        type: str,  # "market", "limit", "stop"
        limit_price: float = None,
        stop_price: float = None
    ) -> TextContent:
        """Submit order to Alpaca"""
        order = self.api.submit_order(
            symbol=symbol,
            qty=qty,
            side=side,
            type=type,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force="day"
        )
        return TextContent(type="text", text=json.dumps({
            "order_id": order.id,
            "status": order.status,
            "created_at": order.created_at
        }))

    @Tool
    async def cancel_all_orders(self) -> TextContent:
        """Cancel all pending orders"""
        self.api.cancel_all_orders()
        return TextContent(type="text", text="All orders cancelled")
```

**MCP 配置**：

```json
// .claude/mcp_servers.json
{
  "mcpServers": {
    "alpaca-broker": {
      "command": "python",
      "args": ["mcp_servers/alpaca_mcp.py"],
      "env": {
        "ALPACA_API_KEY": "${ALPACA_API_KEY}",
        "ALPACA_SECRET_KEY": "${ALPACA_SECRET_KEY}",
        "ALPACA_BASE_URL": "https://paper-api.alpaca.markets"
      }
    },
    "polygon-data": {
      "command": "python",
      "args": ["mcp_servers/polygon_mcp.py"],
      "env": {
        "POLYGON_API_KEY": "${POLYGON_API_KEY}"
      }
    }
  }
}
```

---

## 三、上下文管理策略

**Subagent 隔离设计**：

```markdown
# Subagent Dispatch Rules

| 任务类型 | Subagent | 工具权限 | 上下文策略 |
|---------|---------|---------|-----------|
| 数据探索 | `Explore` | Read-only | 完成后返回摘要，不进主上下文 |
| 回测执行 | `backtest-runner` | Read+Bash | 运行于独立worktree，返回结果JSON |
| 策略生成 | `trading-strategy` | Read+Write | 产出代码文件，主上下文只看文件路径 |
| 风险分析 | `risk-analysis` | Read+Grep | 返回风险评估报告，不超过500 tokens |

**调用模式**：
```python
# 主上下文调用示例
result = await Agent(
    subagent_type="backtest-runner",
    prompt="Run backtest for NVDA strategy 2024-01 to 2024-06",
    isolation="worktree"  # 独立git worktree
)
# result: {"sharpe": 1.8, "max_drawdown": -12%, "win_rate": 65%}
```
```

**Token 预算动态管理**：

```python
# tradingagents/monitoring/context_manager.py

class ContextBudget:
    """Dynamic context window management"""

    # Opus 4.8: 1M context
    CONTEXT_WINDOW = 1_000_000
    SAFETY_BUFFER = 50_000  # Reserve for safety

    @classmethod
    def get_effective_budget(cls):
        return cls.CONTEXT_WINDOW - cls.SAFETY_BUFFER - cls.get_system_prompt_size()

    @classmethod
    def should_delegate(cls, task_tokens_estimate):
        """Decide if task should be delegated to subagent"""
        remaining = cls.get_effective_budget() - cls.get_current_usage()
        if remaining < cls.CONTEXT_WINDOW * 0.2:  # Last 20% danger zone
            return True
        if task_tokens_estimate > remaining * 0.3:  # Task > 30% of remaining
            return True
        return False

    @classmethod
    def recommend_action(cls):
        remaining_pct = (cls.get_effective_budget() - cls.get_current_usage()) / cls.get_effective_budget()
        if remaining_pct < 0.2:
            return "BLOCK: Context critical. Use /clear or delegate to subagent."
        elif remaining_pct < 0.4:
            return "WARN: Consider /compact or subagent delegation."
        else:
            return "OK: Continue normally."
```

---

## 四、升级实施路线

### Phase 1: L1 CLAUDE.md 分层（1-2天）

```
Task 1.1: 创建根目录 CLAUDE.md（精简版）
Task 1.2: 创建 agents/CLAUDE.md（Agent创建规范）
Task 1.3: 创建 dataflows/CLAUDE.md（数据API约定）
Task 1.4: 创建 graph/CLAUDE.md（图扩展指南）
Task 1.5: 创建 risk_management/CLAUDE.md（风控约定）
```

### Phase 2: L2 Hooks 安全网（2-3天）

```
Task 2.1: 实现 pre_flight_check.py（风险限额检查）
Task 2.2: 实现 rate_limiter.py（API调用保护）
Task 2.3: 配置 .claude/settings.json hooks
Task 2.4: 测试 hook 触发与阻断逻辑
```

### Phase 3: L3 Skills 渐进披露（3-4天）

```
Task 3.1: 创建 trading-strategy/SKILL.md + references/
Task 3.2: 创建 backtest-runner/SKILL.md + templates/
Task 3.3: 创建 risk-analysis/SKILL.md
Task 3.4: 创建 data-collection/SKILL.md
Task 3.5: 编写 skills 测试用例
```

### Phase 4: L4 Plugin 打包（1-2天）

```
Task 4.1: 创建 manifest.json
Task 4.2: 组织 skills/agents/hooks/mcp 目录结构
Task 4.3: 编写安装脚本 install.sh
Task 4.4: 测试 Plugin 安装流程
```

### Phase 5: L5 MCP 集成（3-5天）

```
Task 5.1: 实现 alpaca_mcp.py（券商API）
Task 5.2: 实现 polygon_mcp.py（数据API）
Task 5.3: 配置 mcp_servers.json
Task 5.4: 测试 MCP 工具调用
Task 5.5: 集成到 TradingAgentsGraph
```

---

## 五、升级后架构总览

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TradingAgents Harness Stack                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  L5 MCP Servers          →  Alpaca Broker / Polygon Data APIs       │
│  ↑                       →  实盘交易执行 / 实时数据流               │
│                                                                     │
│  L4 Plugin               →  tradingagents-enterprise manifest       │
│  ↑                       →  团队共享配置 / 一键安装部署            │
│                                                                     │
│  L3 Skills               →  trading-strategy / backtest-runner      │
│  ↑                       →  策略模板复用 / 渐进披露文档             │
│                                                                     │
│  L2 Hooks                →  pre_flight_check / rate_limiter         │
│  ↑                       →  风险限额强制 / API保护                  │
│                                                                     │
│  L1 CLAUDE.md            →  分层约定 / 项目入口 / 关键坑点          │
│  ↑                       →  精简指引 + 局部详细                     │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                     │
│  TradingAgents Core                                                │
│  ├── LangGraph Workflow (Analyst → Debate → Trader → Risk)        │
│  ├── Memory Layer (ChromaDB + Reflection)                         │
│  ├── Tool Nodes (YFinance / FinnHub / Reddit / OpenAI)            │
│  └── Context Manager (Subagent isolation + Token budget)          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 六、关键设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Hook 触发时机 | PreToolUse | 阻断式检查，在 propagate() 前强制验证 |
| Skill 文档策略 | 渐进披露 | SKILL.md ≤100行，详细文档按需加载 |
| MCP 集成方式 | 独立进程 | 与 TradingAgents 解耦，支持多券商切换 |
| Context 管理 | 20%阈值阻断 | 避免最后20%做大规模重构，强制委托 |
| Plugin 打包 | manifest.json | 标准化安装，支持版本兼容检查 |

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Hook 阻断过多 | 交易机会流失 | 提供 `--bypass-risk-check` CLI flag（仅测试模式） |
| MCP API 依赖 | 外部服务不稳定 | 实现 MCP fallback：缓存数据 + 模拟模式 |
| Skills 过度模板化 | 策略创新受限 | 允许 raw prompt override via config |
| Context 预算误判 | 误委托或误阻断 | 提供 `context-status` CLI 查看当前预算 |

---

## 附录：文件清单

升级后新增文件：

```
TradingAgents/
├── CLAUDE.md                                    # L1 根指引
├── .claude/
│   ├── settings.json                            # L2 Hooks配置
│   ├── mcp_servers.json                         # L5 MCP配置
│   ├── skills/                                  # L3 Skills目录
│   │   ├── trading-strategy/
│   │   ├── backtest-runner/
│   │   ├── risk-analysis/
│   │   └── data-collection/
│   ├── agents/                                  # L4 Plugin agents
│   │   ├── market-screener.md
│   │   ├── portfolio-optimizer.md
│   │   └── execution-monitor.md
│   └── plugin/
│       └── manifest.json                        # L4 Plugin清单
├── tradingagents/
│   ├── agents/CLAUDE.md                         # L1 Agent层约定
│   ├── dataflows/CLAUDE.md                      # L1 数据层约定
│   ├── graph/CLAUDE.md                          # L1 图层约定
│   ├── risk_management/
│   │   ├── CLAUDE.md                            # L1 风控层约定
│   │   ├── pre_flight_check.py                  # L2 风险检查
│   │   └── risk_limits.py                       # 风险限额配置
│   ├── monitoring/
│   │   ├── rate_limiter.py                      # L2 API保护
│   │   └── context_manager.py                   # 上下文管理
│   └── mcp_servers/
│       ├── alpaca_mcp.py                        # L5 券商MCP
│       └── polygon_mcp.py                       # L5 数据MCP
└── docs/
    └── 2026-06-30-harness-engineering-upgrade-design.md  # 本文档
```