"""Security regression tests for the Alpaca MCP execution tool."""

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents.risk_management.execution_control import ExecutionDenied


def test_alpaca_mcp_module_imports_with_locked_mcp_version():
    result = subprocess.run(
        [sys.executable, "-c", "import tradingagents.mcp_servers.alpaca_mcp"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_alpaca_mcp_never_submits_when_execution_guard_denies():
    from tradingagents.mcp_servers.alpaca_mcp import AlpacaBrokerMCP

    broker = AlpacaBrokerMCP.__new__(AlpacaBrokerMCP)
    broker.api = Mock()
    broker.execution_guard = Mock()
    broker.execution_guard.execute.side_effect = ExecutionDenied("invalid approval")

    response = await broker.submit_order(
        symbol="AAPL",
        qty=10,
        side="buy",
        type="market",
        trade_date="2025-01-02",
        approval_token="invalid-token",
        client_order_id="analysis-1-order-1",
    )

    assert json.loads(response.text) == {
        "status": "error",
        "message": "invalid approval",
    }
    broker.api.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_alpaca_mcp_hides_unexpected_execution_errors():
    from tradingagents.mcp_servers.alpaca_mcp import AlpacaBrokerMCP

    broker = AlpacaBrokerMCP.__new__(AlpacaBrokerMCP)
    broker.api = Mock()
    broker.execution_guard = Mock()
    broker.execution_guard.execute.side_effect = RuntimeError("secret broker detail")

    response = await broker.submit_order(
        symbol="AAPL",
        qty=10,
        side="buy",
        type="market",
        trade_date="2025-01-02",
        approval_token="signed-token",
        client_order_id="analysis-1-order-1",
    )

    assert json.loads(response.text) == {
        "status": "error",
        "message": "Broker execution is unavailable",
    }
    broker.api.submit_order.assert_not_called()


@pytest.mark.asyncio
async def test_alpaca_mcp_passes_client_order_id_through_guard_to_broker():
    from tradingagents.mcp_servers.alpaca_mcp import AlpacaBrokerMCP

    broker = AlpacaBrokerMCP.__new__(AlpacaBrokerMCP)
    broker.api = Mock()
    broker.api.get_latest_trade.return_value = SimpleNamespace(price="100")
    broker.api.submit_order.return_value = SimpleNamespace(
        id="broker-order-1",
        client_order_id="analysis-1-order-1",
        symbol="AAPL",
        qty="10",
        side="buy",
        type="market",
        status="accepted",
        limit_price=None,
        stop_price=None,
        created_at="2025-01-02T15:00:00Z",
        submitted_at="2025-01-02T15:00:00Z",
    )

    def execute(request, price_provider, submitter):
        assert price_provider(request.symbol) == 100.0
        return {
            "status": "success",
            "order": submitter(request),
            "idempotent_replay": False,
        }

    broker.execution_guard = Mock()
    broker.execution_guard.execute.side_effect = execute

    response = await broker.submit_order(
        symbol="AAPL",
        qty=10,
        side="buy",
        type="market",
        trade_date="2025-01-02",
        approval_token="signed-token",
        client_order_id="analysis-1-order-1",
    )

    assert json.loads(response.text)["order"]["id"] == "broker-order-1"
    broker.api.submit_order.assert_called_once_with(
        symbol="AAPL",
        qty=10,
        side="buy",
        type="market",
        limit_price=None,
        stop_price=None,
        time_in_force="day",
        client_order_id="analysis-1-order-1",
    )


def test_legacy_alpaca_broker_cannot_bypass_execution_guard():
    from tradingagents.broker.alpaca_broker import AlpacaBroker
    from tradingagents.broker.broker_interface import BrokerError, OrderRequest

    broker = AlpacaBroker.__new__(AlpacaBroker)
    broker.connected = True

    with pytest.raises(BrokerError, match="controlled Alpaca MCP"):
        broker.submit_order(Mock(spec=OrderRequest))
