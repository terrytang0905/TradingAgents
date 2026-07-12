# TradingAgents Monitoring Layer

> 上下文管理、API调用监控、日志系统约定

## Monitoring Components

| Component | File | Purpose |
|-----------|------|---------|
| RateLimiter | `rate_limiter.py` | API调用频率保护 |
| ContextManager | `context_manager.py` | Token预算动态管理 |
| TradeLogger | `trade_logger.py` | 交易日志记录 |

## Rate Limiter (API Protection)

### Rate Limits Reference

| API | RPM | TPM | Warning Threshold |
|-----|-----|-----|-------------------|
| OpenAI Chat | 500 | 200,000 | 450 RPM |
| OpenAI Embedding | 100 | — | 90 RPM |
| FinnHub | 60 | — | 54 RPM |
| YFinance | 2,000 | — | 1,800 RPM |
| Google News | 100 | — | 90 RPM |

### Implementation Pattern

```python
# tradingagents/monitoring/rate_limiter.py

from collections import defaultdict
import time
import json
from pathlib import Path

class RateLimiter:
    """Protect API calls from exceeding rate limits."""

    LIMITS = {
        "openai_chat": {"rpm": 500, "tpm": 200000, "warning": 0.9},
        "openai_embedding": {"rpm": 100, "warning": 0.9},
        "finnhub": {"rpm": 60, "warning": 0.9},
        "yfinance": {"rpm": 2000, "warning": 0.9},
        "google_news": {"rpm": 100, "warning": 0.9},
    }

    call_history = defaultdict(list)
    log_file = Path(".claude/api_calls.log")

    @classmethod
    def log_call(cls, api_type: str, tokens: int = 0):
        """Log API call and check rate limit."""
        now = time.time()
        cls.call_history[api_type].append({
            "timestamp": now,
            "tokens": tokens
        })

        # Trim to last minute
        cls.call_history[api_type] = [
            c for c in cls.call_history[api_type]
            if now - c["timestamp"] < 60
        ]

        # Check RPM
        current_rpm = len(cls.call_history[api_type])
        limit = cls.LIMITS.get(api_type, {}).get("rpm", 1000)
        warning_threshold = cls.LIMITS.get(api_type, {}).get("warning", 0.9)

        if current_rpm >= limit * warning_threshold:
            print(f"⚠️ WARNING: {api_type} at {current_rpm}/{limit} RPM")

        # Check TPM (if applicable)
        if "tpm" in cls.LIMITS.get(api_type, {}):
            current_tpm = sum(c["tokens"] for c in cls.call_history[api_type])
            tpm_limit = cls.LIMITS[api_type]["tpm"]
            if current_tpm >= tpm_limit * warning_threshold:
                print(f"⚠️ WARNING: {api_type} at {current_tpm}/{tpm_limit} TPM")

        # Persist log
        cls._persist_log(api_type, current_rpm, tokens)

    @classmethod
    def check_can_call(cls, api_type: str) -> bool:
        """Check if API call is allowed."""
        limit = cls.LIMITS.get(api_type, {}).get("rpm", 1000)
        current = len(cls.call_history[api_type])
        return current < limit

    @classmethod
    def wait_if_needed(cls, api_type: str):
        """Wait if approaching rate limit."""
        limit = cls.LIMITS.get(api_type, {}).get("rpm", 1000)
        current = len(cls.call_history[api_type])

        if current >= limit * 0.95:
            wait_time = 60 - (time.time() - cls.call_history[api_type][0]["timestamp"])
            if wait_time > 0:
                print(f"⏳ Waiting {wait_time:.1f}s for rate limit reset...")
                time.sleep(wait_time + 1)

    @classmethod
    def get_remaining_quota(cls, api_type: str) -> int:
        """Get remaining calls in current minute."""
        limit = cls.LIMITS.get(api_type, {}).get("rpm", 1000)
        current = len(cls.call_history[api_type])
        return limit - current

    @classmethod
    def _persist_log(cls, api_type: str, rpm: int, tokens: int):
        """Write call log to file."""
        cls.log_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "api_type": api_type,
            "rpm": rpm,
            "tokens": tokens
        }
        with open(cls.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
```

## Context Manager (Token Budget)

### Budget Calculation

```python
# Context budget formula
effective_budget = context_window - system_prompt - tool_schema - safety_buffer

# Opus 4.8: 1,000,000 tokens
# System prompt: ~10,000 tokens
# Tool schemas: ~5,000 tokens
# Safety buffer: 50,000 tokens
# Effective: ~935,000 tokens
```

### Implementation Pattern

```python
# tradingagents/monitoring/context_manager.py

class ContextBudget:
    """Dynamic context window management."""

    # Model-specific context windows
    CONTEXT_WINDOWS = {
        "claude-opus-4-8": 1_000_000,
        "claude-sonnet-4-6": 200_000,
        "claude-haiku-4-5": 200_000,
        "gpt-4o-mini": 128_000,
        "o4-mini": 200_000,
    }

    SAFETY_BUFFER = 50_000
    DANGER_THRESHOLD = 0.2  # Last 20% is danger zone

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self.context_window = self.CONTEXT_WINDOWS.get(model, 200_000)
        self.current_usage = 0
        self.task_estimates = []

    def get_effective_budget(self) -> int:
        """Calculate usable context budget."""
        return self.context_window - self.SAFETY_BUFFER

    def get_remaining(self) -> int:
        """Get remaining tokens."""
        return self.get_effective_budget() - self.current_usage

    def get_remaining_pct(self) -> float:
        """Get remaining as percentage."""
        return self.get_remaining() / self.get_effective_budget()

    def should_delegate(self, task_tokens: int) -> bool:
        """Decide if task should be delegated to subagent."""
        remaining_pct = self.get_remaining_pct()

        # Delegate if in danger zone
        if remaining_pct < self.DANGER_THRESHOLD:
            return True

        # Delegate if task > 30% of remaining
        if task_tokens > self.get_remaining() * 0.3:
            return True

        return False

    def recommend_action(self) -> str:
        """Provide context management recommendation."""
        remaining_pct = self.get_remaining_pct()

        if remaining_pct < 0.1:
            return "🚨 CRITICAL: Use /clear immediately or delegate all work"
        elif remaining_pct < self.DANGER_THRESHOLD:
            return "⚠️ WARNING: Consider /clear or subagent delegation"
        elif remaining_pct < 0.4:
            return "💡 INFO: Monitor usage, consider /compact for non-essential context"
        else:
            return "✅ OK: Continue normally"

    def estimate_task_tokens(self, task_type: str) -> int:
        """Estimate tokens needed for task type."""
        estimates = {
            "single_analyst": 5_000,
            "debate_round": 10_000,
            "trader_decision": 3_000,
            "risk_triangle": 15_000,
            "full_propagate": 50_000,
            "backtest_1month": 100_000,
            "reflection": 8_000,
        }
        return estimates.get(task_type, 10_000)

    def log_usage(self, task: str, actual_tokens: int):
        """Log actual token usage."""
        from pathlib import Path
        import json
        import time

        log_file = Path(".claude/context_usage.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": time.time(),
            "task": task,
            "estimated": self.estimate_task_tokens(task),
            "actual": actual_tokens,
            "remaining_pct": self.get_remaining_pct()
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        self.current_usage += actual_tokens
```

## Trade Logger

```python
# tradingagents/monitoring/trade_logger.py

from pathlib import Path
import json
from datetime import datetime

class TradeLogger:
    """Log all trade decisions and outcomes."""

    log_dir = Path("eval_results/trade_logs")

    @classmethod
    def log_decision(cls, ticker: str, trade_date: str,
                      decision: str, rationale: str,
                      confidence: str, state: dict):
        """Log a trade decision."""
        cls.log_dir.mkdir(parents=True, exist_ok=True)

        entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "trade_date": trade_date,
            "decision": decision,
            "rationale": rationale,
            "confidence": confidence,
            "state_summary": {
                "market_report": state.get("market_report", "")[:500],
                "sentiment_report": state.get("sentiment_report", "")[:500],
                "bull_history": state.get("investment_debate_state", {}).get("bull_history", "")[:500],
                "bear_history": state.get("investment_debate_state", {}).get("bear_history", "")[:500],
                "risk_judge_decision": state.get("risk_debate_state", {}).get("judge_decision", "")[:500],
            }
        }

        log_file = cls.log_dir / f"{ticker}_{trade_date}.json"
        with open(log_file, "w") as f:
            json.dump(entry, f, indent=2)

    @classmethod
    def log_outcome(cls, ticker: str, trade_date: str,
                    returns: float, actual_price_change: float):
        """Log trade outcome after execution."""
        log_file = cls.log_dir / f"{ticker}_{trade_date}_outcome.json"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": ticker,
            "trade_date": trade_date,
            "returns": returns,
            "price_change": actual_price_change,
        }

        with open(log_file, "w") as f:
            json.dump(entry, f, indent=2)
```

## Integration with Hooks

```python
# Hook calls RateLimiter after each API tool use
# tradingagents/monitoring/rate_limiter.py is invoked by:
#   - PostToolUse hook matching Toolkit.get_*
#   - Manual call in interface.py before API requests

# Example integration in dataflows/interface.py:
from tradingagents.monitoring.rate_limiter import RateLimiter

def get_YFin_data_online(symbol, start_date, end_date):
    api_type = "yfinance"

    # Check before call
    if not RateLimiter.check_can_call(api_type):
        RateLimiter.wait_if_needed(api_type)

    # Make API call
    result = yf.Ticker(symbol).history(start=start_date, end=end_date)

    # Log after call
    RateLimiter.log_call(api_type)

    return result
```

## Monitoring Dashboard (Optional)

```python
# CLI status command
def show_monitoring_status():
    """Display current monitoring status."""
    from tradingagents.monitoring.rate_limiter import RateLimiter
    from tradingagents.monitoring.context_manager import ContextBudget

    print("=== TradingAgents Monitoring Status ===")

    # API Quota
    print("\n📊 API Quota:")
    for api in RateLimiter.LIMITS.keys():
        remaining = RateLimiter.get_remaining_quota(api)
        limit = RateLimiter.LIMITS[api]["rpm"]
        pct = remaining / limit * 100
        status = "🟢" if pct > 50 else "🟡" if pct > 10 else "🔴"
        print(f"  {status} {api}: {remaining}/{limit} ({pct:.0f}%)")

    # Context Budget
    print("\n🧠 Context Budget:")
    budget = ContextBudget()
    print(f"  {budget.recommend_action()}")
    print(f"  Remaining: {budget.get_remaining():,} tokens ({budget.get_remaining_pct():.0%})")
```

## Log File Locations

```
.claude/
├── api_calls.log          # API调用日志
├── context_usage.log      # 上下文使用日志
├── risk_checks.log        # 风控检查日志
└── sessions/              # 会话历史

eval_results/
├── {ticker}/
│   ├── TradingAgentsStrategy_logs/
│   │   └── full_states_log_{date}.json
│   └── trade_logs/
│       ├── {ticker}_{date}.json
│       └── {ticker}_{date}_outcome.json
```

## Testing Monitoring

```python
# tests/test_monitoring.py

def test_rate_limiter_logs_call():
    from tradingagents.monitoring.rate_limiter import RateLimiter
    RateLimiter.log_call("openai_chat", tokens=500)
    assert len(RateLimiter.call_history["openai_chat"]) > 0

def test_rate_limiter_blocks_at_limit():
    from tradingagents.monitoring.rate_limiter import RateLimiter
    # Simulate hitting limit
    for _ in range(550):  # Over 500 limit
        RateLimiter.log_call("openai_chat")
    assert not RateLimiter.check_can_call("openai_chat")

def test_context_budget_delegation():
    from tradingagents.monitoring.context_manager import ContextBudget
    budget = ContextBudget()
    budget.current_usage = 800_000  # Near limit
    assert budget.should_delegate(50_000)
```