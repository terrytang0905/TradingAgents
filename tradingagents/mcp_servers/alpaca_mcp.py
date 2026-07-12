"""Alpaca Broker MCP Server.

Provides real broker integration for TradingAgents.
Supports paper trading and live trading modes.
"""

import json
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
from mcp.server import Server
from mcp.types import Tool, TextContent
import alpaca_trade_api as tradeapi


class AlpacaBrokerMCP(Server):
    """MCP server for Alpaca broker integration.

    Provides tools for:
    - Account info retrieval
    - Position management
    - Order submission
    - Order cancellation
    """

    def __init__(self, api_key: str, secret_key: str, base_url: str = None):
        """Initialize Alpaca broker connection.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            base_url: API endpoint (paper or live)
        """
        # Default to paper trading
        if base_url is None:
            base_url = "https://paper-api.alpaca.markets"

        self.api = tradeapi.REST(api_key, secret_key, base_url)
        self.base_url = base_url

        super().__init__("alpaca-broker")

    @Tool
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

    @Tool
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

    @Tool
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

    @Tool
    async def submit_order(
        self,
        symbol: str,
        qty: int,
        side: str,  # "buy" or "sell"
        type: str,  # "market", "limit", "stop", "stop_limit"
        limit_price: float = None,
        stop_price: float = None,
        time_in_force: str = "day"
    ) -> TextContent:
        """Submit an order to Alpaca.

        Args:
            symbol: Ticker symbol
            qty: Number of shares
            side: "buy" or "sell"
            type: Order type
            limit_price: Limit price (for limit/stop_limit orders)
            stop_price: Stop price (for stop/stop_limit orders)
            time_in_force: Order duration

        Returns:
            Order confirmation with order_id and status
        """
        try:
            # Validate inputs
            if side.lower() not in ["buy", "sell"]:
                raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'")

            if type.lower() not in ["market", "limit", "stop", "stop_limit"]:
                raise ValueError(f"Invalid type: {type}")

            # Submit order
            order = self.api.submit_order(
                symbol=symbol.upper(),
                qty=qty,
                side=side.lower(),
                type=type.lower(),
                limit_price=limit_price,
                stop_price=stop_price,
                time_in_force=time_in_force
            )

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "order": {
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
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "order_params": {
                        "symbol": symbol,
                        "qty": qty,
                        "side": side,
                        "type": type
                    }
                })
            )

    @Tool
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

    @Tool
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

    @Tool
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

    @Tool
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

    @Tool
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
