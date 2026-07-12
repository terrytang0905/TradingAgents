"""
TradingAgents Chainlit Web UI.

Interactive web interface for trading analysis.
Run: chainlit run tradingagents/app.py -w
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import chainlit as cl
from chainlit.element import Element

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_limits import RiskLimits


def run_web():
    """Launch the packaged Chainlit web application."""
    app_path = Path(__file__).resolve()
    subprocess.run(
        [sys.executable, "-m", "chainlit", "run", str(app_path)],
        check=True,
    )


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
    # Welcome message
    welcome = """
# 🤖 TradingAgents Web Interface

Welcome to the Multi-Agent LLM Financial Trading Framework!

## Quick Start
Just type a ticker symbol and date to analyze:
- `NVDA 2024-05-10` — Analyze NVIDIA on May 10, 2024
- `AAPL today` — Analyze Apple with today's date

## Available Commands
- `/analyze <ticker> <date>` — Run full analysis
- `/config <key> <value>` — Update configuration
- `/status` — Check system status
- `/help` — Show help message

## Agent Team
📊 **Analysts**: Market, Sentiment, News, Fundamentals
⚖️ **Researchers**: Bull vs Bear debate
📈 **Trader**: Investment decision
🛡️ **Risk**: Risky vs Safe vs Neutral debate
"""
    await cl.Message(content=welcome).send()

    # Show config options
    config_options = cl.Step(name="config_options")
    config_options.input = """
## Current Configuration
| Parameter | Value |
|-----------|-------|
| Deep Think LLM | `{deep}` |
| Quick Think LLM | `{quick}` |
| Debate Rounds | `{debate}` |
| Online Tools | `{online}` |

To change: `/config <key> <value>`
""".format(
        deep=_current_config["deep_think_llm"],
        quick=_current_config["quick_think_llm"],
        debate=_current_config["max_debate_rounds"],
        online=_current_config["online_tools"]
    )
    await config_options.send()


@cl.on_message
async def on_message(message: cl.Message):
    """Handle user message."""
    content = message.content.strip()

    # Parse command
    if content.startswith("/"):
        await handle_command(content)
        return

    # Parse ticker and date from message
    parts = content.split()
    if len(parts) >= 1:
        ticker = parts[0].upper()
        date = parts[1] if len(parts) >= 2 else datetime.now().strftime("%Y-%m-%d")

        # Handle "today" keyword
        if date.lower() == "today":
            date = datetime.now().strftime("%Y-%m-%d")

        await run_analysis(ticker, date)
    else:
        await cl.Message(
            content="Please provide a ticker symbol. Example: `NVDA 2024-05-10`"
        ).send()


async def handle_command(command: str):
    """Handle slash commands."""
    parts = command.split()
    cmd = parts[0].lower()

    if cmd == "/help":
        help_text = """
## Commands Reference

| Command | Usage | Description |
|---------|-------|-------------|
| `/analyze` | `/analyze NVDA 2024-05-10` | Run full analysis |
| `/config` | `/config max_debate_rounds 2` | Update config |
| `/status` | `/status` | Show system status |
| `/reset` | `/reset` | Reset session |

## Config Keys
- `deep_think_llm` — Deep reasoning model
- `quick_think_llm` — Fast response model
- `max_debate_rounds` — Number of debate rounds
- `online_tools` — Use real API calls (true/false)
"""
        await cl.Message(content=help_text).send()

    elif cmd == "/status":
        from tradingagents.monitoring.rate_limiter import RateLimiter

        limits = RiskLimits.load_from_config()
        quota = RateLimiter.get_remaining_quota("openai_chat")

        status_text = """
## System Status

### Risk Limits
- Max Position per Symbol: `{pos}`
- Max Daily Trades: `{trades}`
- Max Portfolio Exposure: `{exp}`

### API Quota
- Remaining: `{remaining}/{limit}` RPM
""".format(
            pos=f"{limits.max_position_per_symbol:.0%}",
            trades=limits.max_daily_trades,
            exp=f"{limits.max_portfolio_exposure:.0%}",
            remaining=quota["rpm_remaining"],
            limit=quota["rpm_limit"]
        )
        await cl.Message(content=status_text).send()

    elif cmd == "/config" and len(parts) >= 3:
        key = parts[1]
        value = parts[2]

        # Parse value
        if value.lower() == "true":
            value = True
        elif value.lower() == "false":
            value = False
        elif value.isdigit():
            value = int(value)

        # Update config
        if key in _current_config:
            _current_config[key] = value
            await cl.Message(content=f"✅ Updated `{key}` to `{value}`").send()
        else:
            await cl.Message(content=f"❌ Unknown config key: `{key}`").send()

    elif cmd == "/reset":
        global _ta_instance
        _ta_instance = None
        _current_config = DEFAULT_CONFIG.copy()
        await cl.Message(content="🔄 Session reset to defaults").send()

    elif cmd == "/analyze" and len(parts) >= 2:
        ticker = parts[1].upper()
        date = parts[2] if len(parts) >= 3 else datetime.now().strftime("%Y-%m-%d")
        await run_analysis(ticker, date)

    else:
        await cl.Message(content=f"Unknown command: `{cmd}`. Type `/help` for available commands.").send()


async def run_analysis(ticker: str, trade_date: str):
    """Run TradingAgents analysis with visual progress."""
    # Pre-flight check
    check_step = cl.Step(name="risk_check", show_input=False)
    await check_step.send()

    checker = PreFlightCheck()
    risk_result = checker.run(ticker, trade_date)

    if not risk_result["passed"]:
        check_step.output = f"""
## ⛔ Risk Check Failed

**Reason**: {risk_result['blocked_reason']}

### Check Results
"""
        for check in risk_result["checks"]:
            status = "✅" if check["passed"] else "❌"
            check_step.output += f"- {status} {check['name']}\n"

        await check_step.update()
        return

    check_step.output = "✅ All risk checks passed"
    await check_step.update()

    # Start analysis
    analysis_step = cl.Step(name="analysis", show_input=False)
    analysis_step.input = f"## Analyzing {ticker} on {trade_date}\n\nStarting agent workflow..."
    await analysis_step.send()

    # Initialize TradingAgents
    ta = get_trading_agents()

    # Track progress
    agents_status = {
        "Market Analyst": "⏳",
        "Social Analyst": "⏳",
        "News Analyst": "⏳",
        "Fundamentals Analyst": "⏳",
        "Bull Researcher": "⏳",
        "Bear Researcher": "⏳",
        "Research Manager": "⏳",
        "Trader": "⏳",
        "Risky Analyst": "⏳",
        "Safe Analyst": "⏳",
        "Neutral Analyst": "⏳",
        "Risk Judge": "⏳",
    }

    # Run propagation with streaming
    try:
        for chunk in ta.graph.stream(
            ta.propagator.create_initial_state(ticker, trade_date),
            **ta.propagator.get_graph_args()
        ):
            if chunk:
                # Update agent status based on chunk
                for node_name in chunk.keys():
                    if node_name in agents_status:
                        agents_status[node_name] = "✅"

                # Build status display
                status_display = "## Agent Progress\n\n"
                for agent, status in agents_status.items():
                    status_display += f"- {status} {agent}\n"

                analysis_step.output = status_display
                await analysis_step.update()

        # Get final state
        state = ta.curr_state
        decision = state.get("final_trade_decision", "")

        # Build final report
        final_report = f"""
## 📊 Analysis Complete: {ticker}

### Final Decision
{decision}

### Agent Reports

#### Market Analysis
{state.get('market_report', 'N/A')[:500]}...

#### Sentiment Analysis
{state.get('sentiment_report', 'N/A')[:500]}...

#### News Analysis
{state.get('news_report', 'N/A')[:500]}...

#### Fundamentals
{state.get('fundamentals_report', 'N/A')[:500]}...
"""
        analysis_step.output = final_report
        await analysis_step.update()

        # Send final message
        await cl.Message(
            content=f"Analysis complete for **{ticker}** on **{trade_date}**."
        ).send()

    except Exception as e:
        analysis_step.output = f"❌ Error: {str(e)}"
        await analysis_step.update()
        await cl.Message(content=f"Analysis failed: {str(e)}").send()


@cl.on_settings_update
async def on_settings_update(settings: Dict[str, Any]):
    """Handle settings update from UI."""
    global _current_config

    for key, value in settings.items():
        if key in _current_config:
            _current_config[key] = value

    await cl.Message(content=f"Settings updated: {settings}").send()


# Chainlit app configuration
# (chainlit.toml should be configured separately)
