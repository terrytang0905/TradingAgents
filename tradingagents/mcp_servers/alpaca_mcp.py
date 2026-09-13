"""Alpaca Broker MCP Server.

Provides real broker integration for TradingAgents.
Supports paper trading and live trading modes.
"""

import json
from typing import Any, Dict, Optional

import alpaca_trade_api as tradeapi
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from tradingagents.risk_management.execution_control import (
    ExecutionCircuitOpen,
    ExecutionDenied,
    ExecutionGuard,
    ExecutionOrder,
    ExecutionUnavailable,
)
from tradingagents.risk_management.risk_data import ALLOWED_ALPACA_BASE_URLS


class AlpacaBrokerMCP:
    """MCP server for Alpaca broker integration.

    Provides tools for:
    - Account info retrieval
    - Position management
    - Order submission
    - Order cancellation
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        base_url: Optional[str] = None,
        execution_guard: Optional[ExecutionGuard] = None,
    ):
        """Initialize Alpaca broker connection.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            base_url: API endpoint (paper or live)
        """
        # Default to paper trading
        if base_url is None:
            base_url = "https://paper-api.alpaca.markets"
        base_url = base_url.rstrip("/")
        if base_url not in ALLOWED_ALPACA_BASE_URLS:
            raise ValueError("base_url must be an approved Alpaca endpoint")

        self.api = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=base_url,
            api_version="v2",
        )
        self.base_url = base_url
        self.execution_guard = execution_guard or ExecutionGuard.from_environment()
        self.server = FastMCP("alpaca-broker")
        self._register_tools()

    def _register_tools(self) -> None:
        for tool in (
            self.get_account,
            self.get_positions,
            self.get_position,
            self.submit_order,
            self.cancel_order,
            self.cancel_all_orders,
            self.get_orders,
            self.get_latest_price,
            self.get_portfolio_history,
        ):
            self.server.tool()(tool)

    async def get_account(self) -> TextContent:
        """Get account information.

        Returns:
            Account details: cash, portfolio_value, buying_power
        """
        try:
            account = self.api.get_account()

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "account": {
                        "id": account.id,
                        "status": account.status,
                        "cash": float(account.cash),
                        "portfolio_value": float(account.portfolio_value),
                        "buying_power": float(account.buying_power),
                        "equity": float(account.equity),
                        "last_equity": float(account.last_equity),
                        "initial_margin": float(account.initial_margin),
                        "maintenance_margin": float(account.maintenance_margin),
                        "pattern_day_trader": account.pattern_day_trader,
                        "trading_blocked": account.trading_blocked,
                        "transfers_blocked": account.transfers_blocked,
                        "account_blocked": account.account_blocked,
                        "created_at": str(account.created_at),
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    async def get_positions(self) -> TextContent:
        """Get all current positions.

        Returns:
            List of positions with symbol, qty, market_value
        """
        try:
            positions = self.api.list_positions()

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "positions": [
                        {
                            "symbol": p.symbol,
                            "qty": float(p.qty),
                            "market_value": float(p.market_value),
                            "cost_basis": float(p.cost_basis),
                            "unrealized_pl": float(p.unrealized_pl),
                            "unrealized_plpc": float(p.unrealized_plpc),
                            "current_price": float(p.current_price),
                            "avg_entry_price": float(p.avg_entry_price),
                            "side": p.side,
                        }
                        for p in positions
                    ],
                    "total_positions": len(positions)
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    async def get_position(self, symbol: str) -> TextContent:
        """Get position for a specific symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Position details for the symbol
        """
        try:
            position = self.api.get_position(symbol)

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "position": {
                        "symbol": position.symbol,
                        "qty": float(position.qty),
                        "market_value": float(position.market_value),
                        "current_price": float(position.current_price),
                        "avg_entry_price": float(position.avg_entry_price),
                    }
                }, indent=2)
            )
        except Exception as e:
            # Position might not exist
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,  # "buy" or "sell"
        type: str,  # "market", "limit", "stop", "stop_limit"
        trade_date: str,
        approval_token: str,
        client_order_id: str,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "day",
    ) -> TextContent:
        """Submit an order to Alpaca.

        Args:
            symbol: Ticker symbol
            qty: Number of shares
            side: "buy" or "sell"
            type: Order type
            trade_date: Date bound to the analysis approval
            approval_token: Signed capability returned by the analysis API
            client_order_id: Unique idempotency key for this order
            limit_price: Limit price (for limit/stop_limit orders)
            stop_price: Stop price (for stop/stop_limit orders)
            time_in_force: Order duration

        Returns:
            Order confirmation with order_id and status
        """
        requested_order = ExecutionOrder(
            symbol=symbol,
            quantity=qty,
            side=side,
            order_type=type,
            trade_date=trade_date,
            approval_token=approval_token,
            client_order_id=client_order_id,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
        )

        def latest_price(order_symbol: str) -> float:
            return float(self.api.get_latest_trade(order_symbol).price)

        def submit(execution_order: ExecutionOrder) -> Dict[str, Any]:
            order = self.api.submit_order(
                symbol=execution_order.symbol,
                qty=execution_order.quantity,
                side=execution_order.side,
                type=execution_order.order_type,
                limit_price=execution_order.limit_price,
                stop_price=execution_order.stop_price,
                time_in_force=execution_order.time_in_force,
                client_order_id=execution_order.client_order_id,
            )
            return {
                "id": order.id,
                "client_order_id": order.client_order_id,
                "symbol": order.symbol,
                "qty": order.qty,
                "side": order.side,
                "type": order.type,
                "status": order.status,
                "limit_price": float(order.limit_price) if order.limit_price else None,
                "stop_price": float(order.stop_price) if order.stop_price else None,
                "created_at": str(order.created_at),
                "submitted_at": str(order.submitted_at) if order.submitted_at else None,
            }

        try:
            result = self.execution_guard.execute(
                requested_order,
                price_provider=latest_price,
                submitter=submit,
            )
            return TextContent(
                type="text",
                text=json.dumps(result, indent=2),
            )
        except (ExecutionDenied, ExecutionCircuitOpen, ExecutionUnavailable) as exc:
            return TextContent(
                type="text",
                text=json.dumps({"status": "error", "message": str(exc)}),
            )
        except Exception:
            return TextContent(
                type="text",
                text=json.dumps(
                    {"status": "error", "message": "Broker execution is unavailable"}
                ),
            )

    async def cancel_order(self, order_id: str) -> TextContent:
        """Cancel a pending order.

        Args:
            order_id: Order ID to cancel

        Returns:
            Cancellation confirmation
        """
        try:
            self.api.cancel_order(order_id)

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": f"Order {order_id} cancelled",
                    "order_id": order_id
                })
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "order_id": order_id
                })
            )

    async def cancel_all_orders(self) -> TextContent:
        """Cancel all pending orders.

        Returns:
            Cancellation summary
        """
        try:
            self.api.cancel_all_orders()

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "All pending orders cancelled"
                })
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    async def get_orders(self, status: str = "open") -> TextContent:
        """Get orders by status.

        Args:
            status: Order status filter (open, closed, all)

        Returns:
            List of orders
        """
        try:
            orders = self.api.list_orders(status=status)

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "orders": [
                        {
                            "id": o.id,
                            "symbol": o.symbol,
                            "qty": o.qty,
                            "side": o.side,
                            "type": o.type,
                            "status": o.status,
                            "created_at": str(o.created_at),
                        }
                        for o in orders
                    ],
                    "total_orders": len(orders)
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    async def get_latest_price(self, symbol: str) -> TextContent:
        """Get latest price for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Latest trade price
        """
        try:
            bar = self.api.get_latest_trade(symbol)

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "price": {
                        "symbol": symbol,
                        "price": float(bar.price),
                        "timestamp": str(bar.timestamp),
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    async def get_portfolio_history(
        self,
        period: str = "1M",
        timeframe: str = "1D"
    ) -> TextContent:
        """Get portfolio performance history.

        Args:
            period: Time period (1D, 1W, 1M, 3M, 1A, all)
            timeframe: Timeframe (1Min, 5Min, 15Min, 1H, 1D)

        Returns:
            Portfolio equity history
        """
        try:
            history = self.api.get_portfolio_history(
                period=period,
                timeframe=timeframe
            )

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "history": {
                        "timestamp": [str(t) for t in history.timestamp],
                        "equity": [float(e) for e in history.equity],
                        "profit_loss": [float(p) for p in history.profit_loss],
                        "profit_loss_pct": [float(p) for p in history.profit_loss_pct],
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    def run(self) -> None:
        """Run the MCP server over standard input/output."""
        self.server.run(transport="stdio")


def run_server():
    """Run the MCP server."""
    import os

    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

    if not api_key or not secret_key:
        raise ValueError("ALPACA_API_KEY and ALPACA_SECRET_KEY required")

    server = AlpacaBrokerMCP(api_key, secret_key, base_url)
    server.run()


if __name__ == "__main__":
    run_server()
