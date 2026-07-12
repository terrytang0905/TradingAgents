"""
TradingAgents - Multi-Agent LLM Financial Trading Framework.

A production-ready quantitative trading system using multi-agent architecture.

Quick Start:
    from tradingagents import TradingAgentsGraph

    ta = TradingAgentsGraph()
    state, decision = ta.propagate("NVDA", "2024-05-10")
    print(decision)

CLI Usage:
    tradingagents run --ticker NVDA --date 2024-05-10

API Usage:
    python -m tradingagents.api.server

Web UI:
    chainlit run tradingagents/app.py -w
"""

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.risk_management.risk_limits import RiskLimits
from tradingagents.risk_management.pre_flight_check import PreFlightCheck

__version__ = "0.1.0"
__author__ = "TradingAgents Team"

__all__ = [
    "TradingAgentsGraph",
    "DEFAULT_CONFIG",
    "RiskLimits",
    "PreFlightCheck",
]