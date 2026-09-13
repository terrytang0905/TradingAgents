"""Executable example of a typical offline quantitative decision workflow."""

from unittest.mock import Mock, patch

from tradingagents.graph.propagation import Propagator
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_offline_quant_decision_runs_preflight_then_returns_processed_signal(tmp_path, monkeypatch):
    """Shows how to run TradingAgentsGraph without live market or LLM calls."""
    config = {
        "online_tools": False,
        "enforce_trading_hours": False,
    }
    final_state = {
        "company_of_interest": "NVDA",
        "trade_date": "2024-05-10",
        "market_report": "Price is above the 20-day moving average.",
        "sentiment_report": "Social sentiment is constructive but not euphoric.",
        "news_report": "No material negative catalyst was detected.",
        "fundamentals_report": "Revenue growth remains healthy.",
        "investment_debate_state": {
            "bull_history": "Momentum and fundamentals support upside.",
            "bear_history": "Valuation risk remains elevated.",
            "history": "Bull and bear cases were compared.",
            "current_response": "Proceed with measured exposure.",
            "judge_decision": "Accept a small long position.",
        },
        "trader_investment_plan": "Open a small long position with a stop loss.",
        "risk_debate_state": {
            "risky_history": "Upside is attractive.",
            "safe_history": "Keep exposure below the limit.",
            "neutral_history": "Use a small starter position.",
            "history": "Risk team converged on controlled exposure.",
            "judge_decision": "Approve with position cap.",
        },
        "investment_plan": "Buy only if portfolio exposure remains within limits.",
        "final_trade_decision": "FINAL TRANSACTION PROPOSAL: BUY NVDA with 5% position size.",
    }

    trading_graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    trading_graph.debug = False
    trading_graph.config = config
    trading_graph.propagator = Propagator()
    trading_graph.graph = Mock()
    trading_graph.graph.invoke.return_value = final_state
    trading_graph.signal_processor = Mock()
    trading_graph.signal_processor.process_signal.return_value = "BUY"
    trading_graph.log_states_dict = {}

    monkeypatch.chdir(tmp_path)

    with patch("tradingagents.graph.trading_graph.PreFlightCheck") as preflight_cls:
        preflight_cls.return_value.run.return_value = {
            "passed": True,
            "blocked_reason": None,
            "checks": [],
        }
        state, decision = trading_graph.propagate("NVDA", "2024-05-10")

    assert state is final_state
    assert decision == "BUY"
    assert trading_graph.ticker == "NVDA"
    assert trading_graph.curr_state is final_state

    invoked_state = trading_graph.graph.invoke.call_args.args[0]
    assert invoked_state["company_of_interest"] == "NVDA"
    assert invoked_state["trade_date"] == "2024-05-10"
    assert invoked_state["messages"] == [("human", "NVDA")]

    graph_args = trading_graph.graph.invoke.call_args.kwargs
    assert graph_args["stream_mode"] == "values"
    assert graph_args["config"]["recursion_limit"] == 100

    trading_graph.signal_processor.process_signal.assert_called_once_with(
        "FINAL TRANSACTION PROPOSAL: BUY NVDA with 5% position size."
    )
    log_file = (
        tmp_path
        / "eval_results"
        / "NVDA"
        / "TradingAgentsStrategy_logs"
        / "full_states_log_2024-05-10.json"
    )
    assert log_file.exists()
