"""Core graph safety-gate tests."""

from unittest.mock import Mock, patch

import pytest

from tradingagents.graph.trading_graph import TradingAgentsGraph


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
