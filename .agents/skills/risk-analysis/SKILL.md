---
name: risk-analysis
description: 分析交易风险，计算VaR/MaxDD/Volatility，生成风险评估报告。
origin: custom
---

# Risk Analysis Skill

> 量化风险评估与报告生成

## When to Activate

- 用户提及"风险分析"、"风险评估"、"VaR"
- 需要评估策略风险水平
- 决策前风险预检

手动调用：`/risk-analysis` 或 `/风险分析`

---

## Risk Metrics Framework

| 指标 | 公式 | 说明 |
|------|------|------|
| **VaR (95%)** | `returns[5th percentile]` | 95%置信下最大损失 |
| **CVaR** | `mean(returns < VaR)` | 超过VaR的平均损失 |
| **Max Drawdown** | `max(peak - trough)/peak` | 最大回撤 |
| **Volatility** | `std(returns) * sqrt(252)` | 年化波动率 |
| **Beta** | `cov(stock, market)/var(market)` | 市场相关性 |
| **Sharpe** | `(returns - rf)/volatility` | 风险调整收益 |

---

## Risk Analysis Workflow

```
┌─────────────────────────────────────────────────────────────┐
│  Risk Analysis Workflow                                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Input:                                                     │
│  ├── trade_decision (from Risk Judge)                      │
│  ├── portfolio_state (current positions)                   │
│  └── market_data (price history)                           │
│                                                             │
│  Analysis:                                                  │
│  ├── 1. Portfolio Risk                                      │
│  │   ├── Total exposure                                    │
│  │   ├── Sector concentration                              │
│  │   ├── Correlation matrix                                │
│  │                                                          │
│  ├── 2. Position Risk                                       │
│  │   ├── Single position VaR                               │
│  │   ├── Stop loss distance                                │
│  │   ├── Liquidity assessment                              │
│  │                                                          │
│  ├── 3. Market Risk                                         │
│  │   ├── Current volatility                                │
│  │   ├── Trend strength                                    │
│  │   ├── Macro event risk                                  │
│  │                                                          │
│  Output:                                                    │
│  ├── Risk Score (0-100)                                    │
│  ├── Risk Report (markdown)                                │
│  ├── Recommendations (position adjustment)                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Risk Score Calculation

```python
def calculate_risk_score(portfolio, market_data):
    """Calculate overall risk score 0-100."""

    scores = {
        "exposure": portfolio.exposure_pct * 100,           # 0-80
        "concentration": portfolio.max_sector_pct * 50,    # 0-50
        "volatility": market_data.volatility * 100,        # 0-30
        "drawdown": portfolio.max_dd * 100,                # 0-20
    }

    # Weighted sum
    weights = {
        "exposure": 0.3,
        "concentration": 0.2,
        "volatility": 0.3,
        "drawdown": 0.2,
    }

    risk_score = sum(scores[k] * weights[k] for k in scores)
    return min(100, risk_score)  # Cap at 100
```

---

## Risk Report Template

```markdown
## Risk Analysis Report

### Portfolio Summary
- Total Exposure: XX%
- Cash Reserve: XX%
- Positions: X symbols

### Risk Metrics
| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| VaR (95%) | -$X | <$Y | 🟢 OK |
| Max DD | X% | <20% | 🟢 OK |
| Volatility | X% | <30% | 🟡 Warning |

### Risk Score: XX/100
- 🟢 Low (0-30): Safe to proceed
- 🟡 Medium (31-60): Monitor closely
- 🔴 High (61-100): Consider adjustment

### Recommendations
1. <recommendation_1>
2. <recommendation_2>
```

---

## Integration with Pre-flight Check

```python
# Pre-flight check uses risk_score
risk_check = checker._check_risk_score(ticker)

if risk_score > limits.max_risk_score:
    return {
        "passed": False,
        "reason": f"Risk score {risk_score} > max {limits.max_risk_score}"
    }
```

---

## See Detailed References

- Risk Metrics: `@references/risk_metrics.md`
- Stop Loss Rules: `@references/stop_loss_rules.md`
- Portfolio Analysis: `@references/portfolio_analysis.md`