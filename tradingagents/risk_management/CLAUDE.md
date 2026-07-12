# TradingAgents Risk Management Layer

> 风控约束、限额配置、Pre-flight检查约定

## Risk Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Risk Management Stack                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  L2 Hook: pre_flight_check.py                                  │
│  ↑ (强制阻断，零例外)                                           │
│                                                                 │
│  Risk Agents: Risky/Safe/Neutral Debators + Risk Judge         │
│  ↑ (辩论决策层)                                                 │
│                                                                 │
│  Risk Limits: risk_limits.py                                   │
│  ↑ (限额配置层)                                                 │
│                                                                 │
│  Risk Metrics: risk_metrics.py                                 │
│  (计算层)                                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Risk Limits Configuration

```python
# tradingagents/risk_management/risk_limits.py

from dataclasses import dataclass
from typing import Dict, Any
import os

@dataclass
class RiskLimits:
    """Risk limit configuration for trading operations."""

    # Position Limits
    max_position_per_symbol: float = 0.10  # 10% of portfolio per symbol
    max_position_per_sector: float = 0.30  # 30% per sector

    # Trade Limits
    max_daily_trades: int = 50
    max_hourly_trades: int = 10
    max_trade_size_usd: float = 100_000

    # Portfolio Limits
    max_portfolio_exposure: float = 0.80  # 80% invested max
    min_cash_reserve: float = 0.20  # 20% cash reserve min

    # Stop Loss Rules
    default_stop_loss_pct: float = 0.05  # 5% stop loss
    trailing_stop_enabled: bool = True
    trailing_stop_pct: float = 0.03  # 3% trailing

    # API Protection
    min_api_quota_reserve: int = 100  # Reserve 100 calls

    # Leverage
    max_leverage: float = 1.0  # No leverage by default

    @classmethod
    def load_from_config(cls, config: Dict[str, Any] = None) -> "RiskLimits":
        """Load limits from config dict or environment."""
        if config is None:
            config = {}

        # Override from environment variables
        return cls(
            max_position_per_symbol=float(os.getenv("MAX_POSITION_PER_SYMBOL", "0.10")),
            max_daily_trades=int(os.getenv("MAX_DAILY_TRADES", "50")),
            max_portfolio_exposure=float(os.getenv("MAX_PORTFOLIO_EXPOSURE", "0.80")),
            min_api_quota_reserve=int(os.getenv("MIN_API_QUOTA_RESERVE", "100")),
            **config.get("risk_limits", {})
        )

    def validate_trade(self, symbol: str, quantity: int, price: float,
                       portfolio_value: float, current_positions: Dict) -> bool:
        """Validate a single trade against all limits."""
        trade_value = quantity * price

        # Check position limit
        if symbol in current_positions:
            current_pct = current_positions[symbol] / portfolio_value
            new_pct = current_pct + trade_value / portfolio_value
            if new_pct > self.max_position_per_symbol:
                return False

        # Check trade size
        if trade_value > self.max_trade_size_usd:
            return False

        return True
```

## Pre-flight Check (Hook Enforcement)

```python
# tradingagents/risk_management/pre_flight_check.py

import sys
import json
from pathlib import Path
from datetime import datetime
from .risk_limits import RiskLimits

class PreFlightCheck:
    """Risk validation before propagate() execution."""

    def __init__(self, limits: RiskLimits = None):
        self.limits = limits or RiskLimits.load_from_config()
        self.log_file = Path(".claude/risk_checks.log")

    def run(self, ticker: str, trade_date: str) -> dict:
        """Execute all pre-flight checks. Returns result dict."""
        results = {
            "ticker": ticker,
            "trade_date": trade_date,
            "timestamp": datetime.now().isoformat(),
            "checks": [],
            "passed": True,
            "blocked_reason": None
        }

        # Check 1: Position limit
        check1 = self._check_position_limit(ticker)
        results["checks"].append(check1)
        if not check1["passed"]:
            results["passed"] = False
            results["blocked_reason"] = check1["reason"]

        # Check 2: Daily trade count
        check2 = self._check_daily_trades(trade_date)
        results["checks"].append(check2)
        if not check2["passed"]:
            results["passed"] = False
            results["blocked_reason"] = check2["reason"]

        # Check 3: Portfolio exposure
        check3 = self._check_portfolio_exposure()
        results["checks"].append(check3)
        if not check3["passed"]:
            results["passed"] = False
            results["blocked_reason"] = check3["reason"]

        # Check 4: API quota
        check4 = self._check_api_quota()
        results["checks"].append(check4)
        if not check4["passed"]:
            results["passed"] = False
            results["blocked_reason"] = check4["reason"]

        # Log result
        self._log_result(results)

        return results

    def _check_position_limit(self, ticker: str) -> dict:
        """Check if position limit reached for symbol."""
        # Mock implementation - integrate with actual portfolio
        current_positions = self._get_current_positions()
        portfolio_value = self._get_portfolio_value()

        if ticker in current_positions:
            pct = current_positions[ticker] / portfolio_value
            if pct >= self.limits.max_position_per_symbol:
                return {
                    "name": "position_limit",
                    "passed": False,
                    "reason": f"{ticker} position {pct:.2%} >= limit {self.limits.max_position_per_symbol:.2%}"
                }

        return {"name": "position_limit", "passed": True, "reason": None}

    def _check_daily_trades(self, trade_date: str) -> dict:
        """Check if daily trade limit reached."""
        today_trades = self._get_trades_count(trade_date)
        if today_trades >= self.limits.max_daily_trades:
            return {
                "name": "daily_trades",
                "passed": False,
                "reason": f"Daily trades {today_trades} >= limit {self.limits.max_daily_trades}"
            }
        return {"name": "daily_trades", "passed": True, "reason": None}

    def _check_portfolio_exposure(self) -> dict:
        """Check if portfolio exposure limit reached."""
        exposure = self._calculate_total_exposure()
        if exposure >= self.limits.max_portfolio_exposure:
            return {
                "name": "portfolio_exposure",
                "passed": False,
                "reason": f"Exposure {exposure:.2%} >= limit {self.limits.max_portfolio_exposure:.2%}"
            }
        return {"name": "portfolio_exposure", "passed": True, "reason": None}

    def _check_api_quota(self) -> dict:
        """Check API quota reserve."""
        remaining = self._get_api_quota_remaining()
        if remaining < self.limits.min_api_quota_reserve:
            return {
                "name": "api_quota",
                "passed": False,
                "reason": f"API quota {remaining} < reserve {self.limits.min_api_quota_reserve}"
            }
        return {"name": "api_quota", "passed": True, "reason": None}

    # Integration stubs - implement with actual data sources
    def _get_current_positions(self) -> dict:
        """Fetch current positions from portfolio manager."""
        # TODO: Integrate with broker API or portfolio tracker
        return {}

    def _get_portfolio_value(self) -> float:
        """Fetch total portfolio value."""
        # TODO: Integrate with broker API
        return 1_000_000  # Default $1M for testing

    def _get_trades_count(self, date: str) -> int:
        """Count trades executed on given date."""
        # TODO: Integrate with trade log
        return 0

    def _calculate_total_exposure(self) -> float:
        """Calculate total portfolio exposure."""
        positions = self._get_current_positions()
        value = self._get_portfolio_value()
        return sum(positions.values()) / value if value > 0 else 0

    def _get_api_quota_remaining(self) -> int:
        """Get remaining API quota."""
        # TODO: Integrate with rate_limiter
        return 1000  # Default for testing

    def _log_result(self, results: dict):
        """Log check result to file."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_file, "a") as f:
            f.write(json.dumps(results) + "\n")


def main():
    """CLI entry point for Hook invocation."""
    if len(sys.argv) < 3:
        print("Usage: python -m tradingagents.risk_management.pre_flight_check <ticker> <date>")
        sys.exit(1)

    ticker = sys.argv[1]
    trade_date = sys.argv[2]

    checker = PreFlightCheck()
    result = checker.run(ticker, trade_date)

    if result["passed"]:
        print(f"PASS: Risk checks cleared for {ticker} on {trade_date}")
        sys.exit(0)
    else:
        print(f"BLOCKED: {result['blocked_reason']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

## Risk Triangle Debate Agents

```python
# Risk debate flow: Risky → Safe → Neutral → Risky (循环)

# Each agent receives:
# - trader_decision: The trader's proposed action
# - market/sentiment/news/fundamentals reports
# - Debate history (all previous arguments)

# Output format:
"RISK LEVEL: HIGH/MEDIUM/LOW
POSITION_ADVICE: INCREASE/MAINTAIN/REDUCE
KEY_RISKS:
- <risk_1>
- <risk_2>
RATIONALE: <explanation>"
```

## Risk Judge Decision

```python
# Risk Manager final output must include:

"FINAL DECISION: **BUY/HOLD/SELL**
RISK_SCORE: <0-100>
CONFIDENCE: HIGH/MEDIUM/LOW
MODIFIED_POSITION_SIZE: <percentage>
STOP_LOSS: <price or percentage>
TARGET_PRICE: <price>
RISK_FACTORS_ADDRESSED:
- <factor_1>: <mitigation>
- <factor_2>: <mitigation>"
```

## Stop Loss Implementation

```python
# tradingagents/risk_management/stop_loss.py

class StopLossManager:
    """Manage stop loss orders for positions."""

    def __init__(self, risk_limits: RiskLimits):
        self.limits = risk_limits
        self.stop_orders = {}  # symbol -> stop_price

    def set_stop_loss(self, symbol: str, entry_price: float,
                       stop_pct: float = None) -> float:
        """Calculate and set stop loss price."""
        pct = stop_pct or self.limits.default_stop_loss_pct
        stop_price = entry_price * (1 - pct)
        self.stop_orders[symbol] = {
            "entry_price": entry_price,
            "stop_price": stop_price,
            "stop_pct": pct,
            "type": "fixed"
        }
        return stop_price

    def set_trailing_stop(self, symbol: str, current_price: float) -> float:
        """Update trailing stop based on price movement."""
        if not self.limits.trailing_stop_enabled:
            return self.stop_orders.get(symbol, {}).get("stop_price", 0)

        existing = self.stop_orders.get(symbol)
        if existing:
            # Trail only upward (for long positions)
            new_stop = current_price * (1 - self.limits.trailing_stop_pct)
            if new_stop > existing["stop_price"]:
                existing["stop_price"] = new_stop
                existing["type"] = "trailing"
            return existing["stop_price"]
        return 0

    def check_stop_triggered(self, symbol: str, current_price: float) -> bool:
        """Check if stop loss should be triggered."""
        stop = self.stop_orders.get(symbol)
        if stop and current_price <= stop["stop_price"]:
            return True
        return False
```

## Risk Metrics

```python
# tradingagents/risk_management/risk_metrics.py

class RiskMetrics:
    """Calculate portfolio risk metrics."""

    @staticmethod
    def calculate_var(returns: list, confidence: float = 0.95) -> float:
        """Value at Risk calculation."""
        import numpy as np
        returns_sorted = np.sort(returns)
        index = int((1 - confidence) * len(returns_sorted))
        return returns_sorted[index]

    @staticmethod
    def calculate_max_drawdown(prices: list) -> float:
        """Maximum drawdown calculation."""
        peak = prices[0]
        max_dd = 0
        for price in prices:
            if price > peak:
                peak = price
            dd = (peak - price) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def calculate_sharpe(returns: list, risk_free_rate: float = 0.02) -> float:
        """Sharpe ratio calculation."""
        import numpy as np
        excess_returns = np.array(returns) - risk_free_rate / 252
        return np.mean(excess_returns) / np.std(excess_returns)

    @staticmethod
    def calculate_volatility(returns: list, annualize: bool = True) -> float:
        """Volatility calculation."""
        import numpy as np
        vol = np.std(returns)
        if annualize:
            vol *= np.sqrt(252)
        return vol
```

## Hook Integration

```json
// .claude/settings.json (相关部分)
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "TradingAgentsGraph.propagate",
      "hooks": [{
        "type": "command",
        "command": "python -m tradingagents.risk_management.pre_flight_check $CLAUDE_TICKER $CLAUDE_DATE"
      }]
    }]
  }
}
```

## Testing Risk Module

```python
# tests/test_risk_controller.py (示例)

import pytest
from tradingagents.risk_management.risk_limits import RiskLimits
from tradingagents.risk_management.pre_flight_check import PreFlightCheck

def test_position_limit_blocks_trade():
    limits = RiskLimits(max_position_per_symbol=0.10)
    checker = PreFlightCheck(limits)

    # Mock large existing position
    checker._get_current_positions = lambda: {"AAPL": 150_000}
    checker._get_portfolio_value = lambda: 1_000_000

    result = checker._check_position_limit("AAPL")
    assert not result["passed"]
    assert "position" in result["reason"].lower()

def test_daily_trade_limit():
    limits = RiskLimits(max_daily_trades=50)
    checker = PreFlightCheck(limits)
    checker._get_trades_count = lambda date: 55

    result = checker._check_daily_trades("2024-05-10")
    assert not result["passed"]

def test_pre_flight_all_checks_pass():
    checker = PreFlightCheck()
    # All stubs return safe values by default
    result = checker.run("NVDA", "2024-05-10")
    assert result["passed"]
```

## Common Risk Errors

| Error | Cause | Fix |
|-------|-------|-----|
| Trade executed despite limit | Hook not configured | Add PreToolUse hook |
| Stop loss not triggered | Stop orders not monitored | Implement position monitor |
| Risk debate never ends | Count not incremented | Check RiskDebateState update |
| API quota depleted | No rate limiter | Add rate_limiter.py |