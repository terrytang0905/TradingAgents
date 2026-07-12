---
name: backtest-runner
description: 运行策略回测，计算性能指标（Sharpe/MaxDD/WinRate），支持多时间窗口回测。
origin: custom
---

# Backtest Runner Skill

> 运行TradingAgents策略回测，生成性能报告

## When to Activate

- 用户提及"回测"、"测试策略"、"性能评估"
- 需要验证策略在历史数据上的表现
- 比较不同配置下的策略效果

手动调用：`/backtest-runner` 或 `/回测`

---

## Backtest Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  Backtest Runner Workflow                                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 配置回测参数                                             │
│     ├── ticker(s): 标的列表                                 │
│     ├── start_date / end_date: 时间窗口                     │
│     ├── config: LLM/辩论轮次/数据源配置                      │
│     └── initial_capital: 初始资金                           │
│                                                             │
│  2. 执行回测循环                                             │
│     ├── for each trade_date in window:                     │
│     │   ├── propagate(ticker, date)                        │
│     │   ├── simulate_trade(decision)                       │
│     │   ├── reflect_and_remember(returns)                  │
│     │   └ log_trade_result()                               │
│                                                             │
│  3. 计算性能指标                                             │
│     ├── Sharpe Ratio                                        │
│     ├── Maximum Drawdown                                    │
│     ├── Win Rate                                            │
│     ├── Total Returns                                       │
│     └── Calmar Ratio                                        │
│                                                             │
│  4. 生成报告                                                 │
│     ├── JSON metrics file                                   │
│     ├── Trade log CSV                                       │
│     └── Performance chart (optional)                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

```python
from tradingagents.backtest.runner import BacktestRunner
from tradingagents.default_config import DEFAULT_CONFIG

# Initialize runner
runner = BacktestRunner(
    tickers=["NVDA", "AAPL"],
    start_date="2024-01-01",
    end_date="2024-06-30",
    config=DEFAULT_CONFIG.copy(),
    initial_capital=100_000
)

# Run backtest
results = runner.run()

# View metrics
print(results["metrics"])
```

---

## Performance Metrics

| 指标 | 计算方法 | 目标值 |
|------|---------|--------|
| **Sharpe Ratio** | `(returns - rf) / std(returns)` | > 1.0 |
| **Max Drawdown** | `max(peak - trough) / peak` | < 20% |
| **Win Rate** | `winning_trades / total_trades` | > 55% |
| **Total Returns** | `(final - initial) / initial` | Positive |
| **Calmar Ratio** | `annual_return / max_drawdown` | > 3.0 |

---

## Backtest Configuration

```python
config = {
    # LLM settings
    "deep_think_llm": "o4-mini",      # 决策层
    "quick_think_llm": "gpt-4o-mini", # 分析层

    # Debate settings (影响决策质量)
    "max_debate_rounds": 2,           # 更多轮次=更深入分析
    "max_risk_discuss_rounds": 2,

    # Data settings
    "online_tools": False,            # 回测用缓存数据

    # Risk settings
    "risk_limits": {
        "max_position_per_symbol": 0.10,
        "default_stop_loss_pct": 0.05,
    }
}
```

---

## Trade Simulation Logic

```python
def simulate_trade(decision: str, current_price: float, portfolio: dict):
    """
    Simulate trade execution based on decision.

    Decision format: "FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**"
    """
    action = extract_action(decision)  # BUY/HOLD/SELL

    if action == "BUY":
        # Calculate position size (based on confidence)
        position_size = calculate_position_size(decision, portfolio)
        execute_buy(position_size, current_price)

    elif action == "SELL":
        # Execute sell (full or partial)
        position_size = calculate_sell_size(decision, portfolio)
        execute_sell(position_size, current_price)

    else:  # HOLD
        # No action, update stop loss if needed
        update_trailing_stop(portfolio)
```

---

## Output Files

```
eval_results/
├── {ticker}/
│   ├── TradingAgentsStrategy_logs/
│   │   └── full_states_log_{date}.json    # 每日完整状态
│   ├── trade_logs/
│   │   ├── trades.csv                      # 交易记录
│   │   └── metrics.json                    # 性能指标
│   │   └── equity_curve.png                # 权益曲线（可选）
│   └── backtest_summary.json               # 回测总结
```

---

## Template: Backtest Runner

See `@templates/backtest_runner.py` for full implementation template.

---

## Testing Backtest

```bash
# Quick backtest (1 month, 1 ticker)
python -m tradingagents.backtest.quick_test NVDA 2024-05-01 2024-05-31

# Full backtest
python -m tradingagents.backtest.runner --tickers NVDA,AAPL --start 2024-01-01 --end 2024-06-30
```