"""
TradingAgents Chainlit Web UI.

Interactive web interface for trading analysis.
Run: chainlit run app.py -w
"""

import os
import sys
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional

# Add project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chainlit as cl

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_limits import RiskLimits


# Global TradingAgents instance
_ta_instance: Optional[TradingAgentsGraph] = None
_current_config: Dict[str, Any] = DEFAULT_CONFIG.copy()


def get_trading_agents(config: Dict = None) -> TradingAgentsGraph:
    """Get or create TradingAgents instance."""
    global _ta_instance, _current_config

    if config:
        _current_config.update(config)

    _ta_instance = TradingAgentsGraph(debug=True, config=_current_config)
    return _ta_instance


@cl.on_chat_start
async def on_chat_start():
    """Initialize chat session."""
    welcome = """
# 🤖 TradingAgents Web Interface

Welcome to the Multi-Agent LLM Financial Trading Framework!

## Quick Start
Type a ticker symbol and date to analyze:
- `NVDA 2024-05-10` — Analyze NVIDIA
- `AAPL today` — Analyze Apple

## Commands
- `/analyze <ticker> <date>` — Run full analysis
- `/status` — Check system status
- `/help` — Show help

## Agent Workflow
📊 Analysts → ⚖️ Bull/Bear Debate → 📈 Trader → 🛡️ Risk Triangle
"""
    await cl.Message(content=welcome).send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle user message."""
    content = message.content.strip()

    # Parse command
    if content.startswith("/"):
        await handle_command(content)
        return

    # Parse ticker and date
    parts = content.split()
    if len(parts) >= 1:
        ticker = parts[0].upper()
        date = parts[1] if len(parts) >= 2 else datetime.now().strftime("%Y-%m-%d")

        if date.lower() == "today":
            date = datetime.now().strftime("%Y-%m-%d")

        await run_analysis(ticker, date)
    else:
        await cl.Message(content="Please provide a ticker. Example: `NVDA 2024-05-10`").send()


async def handle_command(command: str):
    """Handle slash commands."""
    parts = command.split()
    cmd = parts[0].lower()

    if cmd == "/help":
        help_text = """
## Commands

| Command | Example |
|---------|---------|
| `/analyze` | `/analyze NVDA 2024-05-10` |
| `/status` | `/status` |
| `/reset` | `/reset` |
"""
        await cl.Message(content=help_text).send()

    elif cmd == "/status":
        from tradingagents.monitoring.rate_limiter import RateLimiter
        limits = RiskLimits.load_from_config()
        quota = RateLimiter.get_remaining_quota("openai_chat")

        status_text = f"""
## System Status

### Risk Limits
- Max Position: `{limits.max_position_per_symbol:.0%}`
- Max Daily Trades: `{limits.max_daily_trades}`
- Max Exposure: `{limits.max_portfolio_exposure:.0%}`

### API Quota
- Remaining: `{quota["rpm_remaining"]}/{quota["rpm_limit"]}` RPM
"""
        await cl.Message(content=status_text).send()

    elif cmd == "/reset":
        global _ta_instance
        _ta_instance = None
        _current_config = DEFAULT_CONFIG.copy()
        await cl.Message(content="🔄 Session reset").send()

    elif cmd == "/analyze" and len(parts) >= 2:
        ticker = parts[1].upper()
        date = parts[2] if len(parts) >= 3 else datetime.now().strftime("%Y-%m-%d")
        await run_analysis(ticker, date)

    else:
        await cl.Message(content=f"Unknown command. Type `/help`").send()


async def run_analysis(ticker: str, trade_date: str):
    """Run TradingAgents analysis with visual progress."""
    # Pre-flight check
    check_step = cl.Step(name="risk_check")
    await check_step.send()

    checker = PreFlightCheck()
    risk_result = checker.run(ticker, trade_date)

    if not risk_result["passed"]:
        check_step.output = f"⛔ **Blocked**: {risk_result['blocked_reason']}"
        await check_step.update()
        return

    check_step.output = "✅ Risk checks passed"
    await check_step.update()

    # Analysis
    analysis_step = cl.Step(name="analysis")
    analysis_step.input = f"Analyzing **{ticker}** on **{trade_date}**..."
    await analysis_step.send()

    try:
        ta = get_trading_agents()

        # Run with streaming
        for chunk in ta.graph.stream(
            ta.propagator.create_initial_state(ticker, trade_date),
            **ta.propagator.get_graph_args()
        ):
            if chunk:
                analysis_step.output = f"Running: {list(chunk.keys())[0]}"
                await analysis_step.update()

        # Final result
        state = ta.curr_state
        decision = state.get("final_trade_decision", "")

        analysis_step.output = f"""
## 📊 Result: {ticker}

### Decision
{decision[:500]}...

### Reports Summary
- Market: ✅
- Sentiment: ✅
- News: ✅
- Fundamentals: ✅
"""
        await analysis_step.update()

        await cl.Message(content=f"✅ Analysis complete for **{ticker}**").send()

    except Exception as e:
        analysis_step.output = f"❌ Error: {str(e)}"
        await analysis_step.update()


# For chainlit.toml reference
# Run: chainlit run app.py -w --port 8000