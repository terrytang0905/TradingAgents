"""Core graph safety-gate tests."""

from unittest.mock import Mock, patch

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph, _model_callbacks
from tradingagents.monitoring.rate_limiter import RateLimitCallbackHandler


def test_graph_model_callbacks_include_runtime_rate_limiter():
    callbacks = _model_callbacks({"risk_api_type": "openai_chat"})

    assert len(callbacks) == 1
    assert isinstance(callbacks[0], RateLimitCallbackHandler)
    assert callbacks[0].api_type == "openai_chat"


def test_propagate_blocks_before_graph_execution_when_preflight_fails():
    trading_graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    trading_graph.config = {}
    trading_graph.graph = Mock()

    failed_check = {
        "passed": False,
        "blocked_reason": "position limit exceeded",
        "checks": [],
    }

    with patch(
        "tradingagents.graph.trading_graph.PreFlightCheck"
    ) as preflight_cls:
        preflight_cls.return_value.run.return_value = failed_check

        with pytest.raises(PermissionError, match="position limit exceeded"):
            trading_graph.propagate("AAPL", "2024-05-10")

    trading_graph.graph.invoke.assert_not_called()
    trading_graph.graph.stream.assert_not_called()


def test_graph_attaches_execution_approval_after_processed_decision():
    trading_graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    trading_graph.config = {"execution_approval_ttl_seconds": 300}
    final_state = {}

    with patch(
        "tradingagents.graph.trading_graph.ExecutionApprovalIssuer"
    ) as issuer_cls:
        issuer_cls.from_environment.return_value.issue.return_value = "signed-token"
        trading_graph._attach_execution_approval(
            final_state,
            action="BUY",
            symbol="AAPL",
            trade_date="2024-05-10",
        )

    assert final_state["execution_approval"] == "signed-token"
    assert final_state["execution_approval_status"] == {"status": "approved"}
    issuer_cls.from_environment.return_value.issue.assert_called_once_with(
        "BUY", "AAPL", "2024-05-10"
    )


def test_graph_fails_closed_when_execution_approval_is_unavailable():
    trading_graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    trading_graph.config = {}
    final_state = {}

    with patch(
        "tradingagents.graph.trading_graph.ExecutionApprovalIssuer"
    ) as issuer_cls:
        issuer_cls.from_environment.side_effect = RuntimeError("secret details")
        trading_graph._attach_execution_approval(
            final_state,
            action="SELL",
            symbol="AAPL",
            trade_date="2024-05-10",
        )

    assert final_state["execution_approval"] is None
    assert final_state["execution_approval_status"] == {
        "status": "unavailable",
        "reason": "Execution approval could not be issued safely",
    }
