"""
AlpacaBroker - Alpaca券商API实现

功能:
1. Alpaca Markets API集成
2. 股票交易（美股）
3. Paper Trading（模拟盘）只读支持
4. 实时行情数据
5. WebSocket实时订单更新（可选）

依赖:
pip install alpaca-trade-api

使用方法:
    broker = AlpacaBroker(api_key="KEY", api_secret="SECRET", paper=True)
    broker.connect()
    # 下单必须通过带签名授权和幂等保护的 Alpaca MCP。

Created: 2026-06-03
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import OrderSide

    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    print("⚠️ alpaca-trade-api未安装，请运行: pip install alpaca-trade-api")

from .broker_interface import (
    AccountInfo,
    BrokerError,
    BrokerInterface,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    PositionInfo,
)


class AlpacaBroker(BrokerInterface):
    """Alpaca券商API实现"""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        paper: bool = True,  # 默认使用模拟盘
        config: Dict[str, Any] = None
    ):
        """初始化Alpaca券商接口

        Args:
            api_key: Alpaca API密钥
            api_secret: Alpaca API密钥
            paper: 是否使用模拟盘（True=Paper Trading, False=Live Trading）
            config: 配置字典
        """
        super().__init__(api_key, api_secret, config)

        if not ALPACA_AVAILABLE:
            raise BrokerError("alpaca-trade-api未安装，无法使用AlpacaBroker")

        self.paper = paper
        self.trading_client: Optional[TradingClient] = None
        self.data_client: Optional[StockHistoricalDataClient] = None

        # Alpaca API配置
        if paper:
            # Paper Trading API endpoints
            self.base_url = "https://paper-api.alpaca.markets"
        else:
            # Live Trading API endpoints
            self.base_url = "https://api.alpaca.markets"

    def connect(self) -> bool:
        """连接Alpaca API

        Returns:
            bool: 是否成功连接
        """
        try:
            # 初始化TradingClient
            self.trading_client = TradingClient(
                api_key=self.api_key,
                secret_key=self.api_secret,
                paper=self.paper
            )

            # 初始化DataClient（行情数据）
            self.data_client = StockHistoricalDataClient(
                api_key=self.api_key,
                secret_key=self.api_secret
            )

            # 测试连接（获取账户信息）
            account = self.trading_client.get_account()

            if account:
                self.connected = True
                print(f"✓ Alpaca API连接成功（Paper={self.paper}）")
                print(f"  账户ID: {account.id}")
                print(f"  账户状态: {account.status}")
                return True
            else:
                self.connected = False
                return False

        except Exception as e:
            self.connected = False
            raise BrokerError(f"Alpaca API连接失败: {str(e)}")

    def disconnect(self) -> bool:
        """断开Alpaca API连接

        Returns:
            bool: 是否成功断开
        """
        try:
            # Alpaca SDK无显式断开方法，直接清空客户端
            self.trading_client = None
            self.data_client = None
            self.connected = False

            print("✓ Alpaca API已断开")
            return True

        except Exception as e:
            raise BrokerError(f"Alpaca API断开失败: {str(e)}")

    def submit_order(self, order_request: OrderRequest) -> OrderResponse:
        """Reject the legacy unguarded execution path."""
        del order_request
        raise BrokerError(
            "Direct AlpacaBroker submission is disabled; use the controlled Alpaca MCP"
        )

    def cancel_order(self, order_id: str) -> bool:
        """取消Alpaca订单

        Args:
            order_id: Alpaca订单ID

        Returns:
            bool: 是否成功取消

        Raises:
            BrokerError: Alpaca API错误
        """
        if not self.connected:
            raise BrokerError("Alpaca API未连接")

        try:
            # 取消订单
            self.trading_client.cancel_order_by_id(order_id)
            return True

        except Exception as e:
            raise BrokerError(f"取消订单失败: {str(e)}", order_id=order_id)

    def get_order_status(self, order_id: str) -> OrderResponse:
        """查询Alpaca订单状态

        Args:
            order_id: Alpaca订单ID

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: Alpaca API错误
        """
        if not self.connected:
            raise BrokerError("Alpaca API未连接")

        try:
            # 查询订单状态
            alpaca_order = self.trading_client.get_order_by_id(order_id)

            # 转换响应格式
            return self._convert_alpaca_order_to_response(alpaca_order)

        except Exception as e:
            raise BrokerError(f"查询订单失败: {str(e)}", order_id=order_id)

    def get_account_info(self) -> AccountInfo:
        """查询Alpaca账户信息

        Returns:
            AccountInfo: 账户信息

        Raises:
            BrokerError: Alpaca API错误
        """
        if not self.connected:
            raise BrokerError("Alpaca API未连接")

        try:
            # 查询账户信息
            account = self.trading_client.get_account()

            # 转换格式
            return AccountInfo(
                account_id=account.id,
                cash_balance=float(account.cash),
                buying_power=float(account.buying_power),
                total_portfolio_value=float(account.portfolio_value),
                total_pnl=float(account.equity) - float(account.last_equity),
                daily_pnl=float(account.equity) - float(account.last_equity),
                currency="USD"
            )

        except Exception as e:
            raise BrokerError(f"查询账户信息失败: {str(e)}")

    def get_positions(self) -> List[PositionInfo]:
        """查询Alpaca持仓信息

        Returns:
            List[PositionInfo]: 持仓列表

        Raises:
            BrokerError: Alpaca API错误
        """
        if not self.connected:
            raise BrokerError("Alpaca API未连接")

        try:
            # 查询所有持仓
            positions = self.trading_client.get_all_positions()

            # 转换格式
            position_list = []
            for position in positions:
                position_info = PositionInfo(
                    symbol=position.symbol,
                    quantity=int(position.qty),
                    avg_entry_price=float(position.avg_entry_price),
                    current_price=float(position.current_price),
                    market_value=float(position.market_value),
                    unrealized_pnl=float(position.unrealized_pl),
                    unrealized_pnl_percent=float(position.unrealized_plpc),
                    realized_pnl=float(position.realized_pl) if hasattr(position, 'realized_pl') else 0.0,
                    cost_basis=float(position.cost_basis)
                )
                position_list.append(position_info)

            return position_list

        except Exception as e:
            raise BrokerError(f"查询持仓失败: {str(e)}")

    def get_current_price(self, symbol: str) -> float:
        """获取当前市场价格

        Args:
            symbol: 交易标的

        Returns:
            float: 当前价格

        Raises:
            BrokerError: Alpaca API错误
        """
        if not self.connected:
            raise BrokerError("Alpaca API未连接")

        try:
            # 使用实时行情数据（简化：使用最新交易价格）
            from alpaca.data.requests import StockLatestTradeRequest

            request = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trades = self.data_client.get_stock_latest_trade(request)

            if symbol in trades:
                trade = trades[symbol]
                return float(trade.price)
            else:
                raise BrokerError(f"无法获取{symbol}的实时价格")

        except Exception as e:
            raise BrokerError(f"获取价格失败: {str(e)}")

    def _convert_alpaca_order_response(
        self,
        alpaca_order: Any,
        original_request: OrderRequest
    ) -> OrderResponse:
        """转换Alpaca订单响应为统一格式

        Args:
            alpaca_order: Alpaca订单对象
            original_request: 原始订单请求

        Returns:
            OrderResponse: 统一订单响应格式
        """
        # 转换订单状态
        status_map = {
            'new': OrderStatus.SUBMITTED,
            'accepted': OrderStatus.SUBMITTED,
            'pending_new': OrderStatus.PENDING,
            'filled': OrderStatus.FILLED,
            'partially_filled': OrderStatus.PARTIALLY_FILLED,
            'done_for_day': OrderStatus.CANCELLED,
            'canceled': OrderStatus.CANCELLED,
            'expired': OrderStatus.CANCELLED,
            'replaced': OrderStatus.SUBMITTED,
            'pending_cancel': OrderStatus.CANCELLED,
            'pending_replace': OrderStatus.SUBMITTED,
            'rejected': OrderStatus.REJECTED,
            'stopped': OrderStatus.FILLED,
            'calc': OrderStatus.PENDING
        }

        alpaca_status = str(alpaca_order.status).lower()
        order_status = status_map.get(alpaca_status, OrderStatus.PENDING)

        # 提取成交信息
        filled_quantity = int(alpaca_order.filled_qty) if hasattr(alpaca_order, 'filled_qty') else 0
        avg_fill_price = float(alpaca_order.filled_avg_price) if hasattr(alpaca_order, 'filled_avg_price') and alpaca_order.filled_avg_price else None

        # 计算总成本
        total_cost = None
        if avg_fill_price and filled_quantity > 0:
            total_cost = avg_fill_price * filled_quantity

        # 提取佣金（Alpaca Paper Trading无佣金）
        commission = 0.0

        # 提取时间信息
        submitted_at = datetime.fromisoformat(str(alpaca_order.created_at).replace('Z', '+00:00'))
        filled_at = None
        if hasattr(alpaca_order, 'filled_at') and alpaca_order.filled_at:
            filled_at = datetime.fromisoformat(str(alpaca_order.filled_at).replace('Z', '+00:00'))

        return OrderResponse(
            order_id=alpaca_order.id,
            client_order_id=alpaca_order.client_order_id or original_request.client_order_id or "",
            symbol=alpaca_order.symbol,
            side=OrderSide.BUY if str(alpaca_order.side).upper() == "BUY" else OrderSide.SELL,
            quantity=int(alpaca_order.qty),
            filled_quantity=filled_quantity,
            order_type=original_request.order_type,
            limit_price=float(alpaca_order.limit_price) if hasattr(alpaca_order, 'limit_price') and alpaca_order.limit_price else None,
            stop_price=float(alpaca_order.stop_price) if hasattr(alpaca_order, 'stop_price') and alpaca_order.stop_price else None,
            status=order_status,
            submitted_at=submitted_at,
            filled_at=filled_at,
            avg_fill_price=avg_fill_price,
            total_cost=total_cost,
            commission=commission
        )

    def _convert_alpaca_order_to_response(self, alpaca_order: Any) -> OrderResponse:
        """转换Alpaca订单查询响应为统一格式（无原始请求）

        Args:
            alpaca_order: Alpaca订单对象

        Returns:
            OrderResponse: 统一订单响应格式
        """
        # 转换订单类型
        order_type_map = {
            'market': OrderType.MARKET,
            'limit': OrderType.LIMIT,
            'stop': OrderType.STOP_LOSS,
            'stop_limit': OrderType.STOP_LIMIT
        }

        alpaca_type = str(alpaca_order.order_type).lower()
        order_type = order_type_map.get(alpaca_type, OrderType.MARKET)

        # 创建临时OrderRequest（用于转换）
        temp_request = OrderRequest(
            symbol=alpaca_order.symbol,
            side=OrderSide.BUY if str(alpaca_order.side).upper() == "BUY" else OrderSide.SELL,
            quantity=int(alpaca_order.qty),
            order_type=order_type,
            limit_price=float(alpaca_order.limit_price) if hasattr(alpaca_order, 'limit_price') and alpaca_order.limit_price else None,
            stop_price=float(alpaca_order.stop_price) if hasattr(alpaca_order, 'stop_price') and alpaca_order.stop_price else None,
            client_order_id=alpaca_order.client_order_id
        )

        return self._convert_alpaca_order_response(alpaca_order, temp_request)


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("AlpacaBroker使用示例")
    print("="*60)

    if ALPACA_AVAILABLE:
        print("\n注意: 使用前需要安装alpaca-trade-api")
        print("安装命令: pip install alpaca-trade-api")
        print("\n示例代码:")
        print("""
        from tradingagents.broker.alpaca_broker import AlpacaBroker
        from tradingagents.broker.broker_interface import OrderRequest, OrderSide, OrderType

        # 初始化Alpaca券商接口（Paper Trading模式）
        broker = AlpacaBroker(
            api_key="YOUR_ALPACA_API_KEY",
            api_secret="YOUR_ALPACA_API_SECRET",
            paper=True  # 使用模拟盘（安全测试）
        )

        # 连接Alpaca API
        broker.connect()

        # 查询账户信息
        account = broker.get_account_info()
        print(f"可用资金: $%.2f" % account.cash_balance)
        print(f"购买力: $%.2f" % account.buying_power)

        # 提交买入订单（市价单）
        order_request = OrderRequest(
            symbol="NVDA",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET
        )

        # 执行交易（带重试机制）
        order_response = broker.execute_trade_with_retry(order_request, max_retries=3)

        if order_response.status.name == "FILLED":
            print(f"✓ 订单成交成功")
            print(f"  订单ID: {order_response.order_id}")
            print(f"  成交价格: $%.2f" % order_response.avg_fill_price)
            print(f"  成交数量: {order_response.filled_quantity}股")
            print(f"  总成本: $%.2f" % order_response.total_cost)
        else:
            print(f"✗ 订单失败: {order_response.error_message}")

        # 查询持仓
        positions = broker.get_positions()
        for position in positions:
            print(f"{position.symbol}: {position.quantity}股，盈亏${position.unrealized_pnl:.2f}")

        # 断开连接
        broker.disconnect()
        """)
    else:
        print("\n⚠️ alpaca-trade-api未安装")
        print("请运行: pip install alpaca-trade-api")
