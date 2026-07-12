"""
BrokerInterface - 券商交易接口抽象基类

功能:
1. 多券商API支持（Alpaca/IBKr/Binance）
2. 订单执行（BUY/SELL）
3. 订单状态查询
4. 账户余额查询
5. 持仓查询
6. 订单历史记录
7. 错误处理和重试机制

Created: 2026-06-03
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import time


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"  # 市价单
    LIMIT = "limit"  # 限价单
    STOP_LOSS = "stop_loss"  # 止损单
    STOP_LIMIT = "stop_limit"  # 止损限价单


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"  # 待提交
    SUBMITTED = "submitted"  # 已提交
    FILLED = "filled"  # 已成交
    PARTIALLY_FILLED = "partially_filled"  # 部分成交
    CANCELLED = "cancelled"  # 已取消
    REJECTED = "rejected"  # 已拒绝
    FAILED = "failed"  # 失败


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


@dataclass
class OrderRequest:
    """订单请求"""
    symbol: str  # 交易标的
    side: OrderSide  # BUY/SELL
    quantity: int  # 数量
    order_type: OrderType  # 订单类型
    limit_price: Optional[float] = None  # 限价（Limit订单需要）
    stop_price: Optional[float] = None  # 止损价（Stop订单需要）
    time_in_force: str = "gtc"  # 有效期（gtc=Good Till Cancelled）
    client_order_id: Optional[str] = None  # 客户端订单ID


@dataclass
class OrderResponse:
    """订单响应"""
    order_id: str  # 券商订单ID
    client_order_id: str  # 客户端订单ID
    symbol: str  # 交易标的
    side: OrderSide  # BUY/SELL
    quantity: int  # 订单数量
    filled_quantity: int  # 已成交数量
    order_type: OrderType  # 订单类型
    limit_price: Optional[float]  # 限价
    stop_price: Optional[float]  # 止损价
    status: OrderStatus  # 订单状态
    submitted_at: datetime  # 提交时间
    filled_at: Optional[datetime]  # 成交时间
    avg_fill_price: Optional[float]  # 平均成交价格
    total_cost: Optional[float]  # 总成本
    commission: Optional[float]  # 佣金
    error_message: Optional[str] = None  # 错误信息


@dataclass
class AccountInfo:
    """账户信息"""
    account_id: str  # 账户ID
    cash_balance: float  # 现金余额
    buying_power: float  # 可用购买力
    total_portfolio_value: float  # 总组合价值
    total_pnl: float  # 总盈亏
    daily_pnl: float  # 单日盈亏
    currency: str  # 货币类型（USD/CNY）


@dataclass
class PositionInfo:
    """持仓信息"""
    symbol: str  # 交易标的
    quantity: int  # 持仓数量
    avg_entry_price: float  # 平均买入价格
    current_price: float  # 当前市场价格
    market_value: float  # 市值
    unrealized_pnl: float  # 未实现盈亏
    unrealized_pnl_percent: float  # 未实现盈亏百分比
    realized_pnl: float  # 已实现盈亏
    cost_basis: float  # 成本基础


class BrokerInterface(ABC):
    """券商交易接口抽象基类"""

    def __init__(self, api_key: str, api_secret: str, config: Dict[str, Any] = None):
        """初始化券商接口

        Args:
            api_key: API密钥
            api_secret: API密钥
            config: 配置字典
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.config = config or {}

        # 订单历史记录
        self.order_history: List[OrderResponse] = []

        # 连接状态
        self.connected = False

    @abstractmethod
    def connect(self) -> bool:
        """连接券商API

        Returns:
            bool: 是否成功连接
        """
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """断开券商API连接

        Returns:
            bool: 是否成功断开
        """
        pass

    @abstractmethod
    def submit_order(self, order_request: OrderRequest) -> OrderResponse:
        """提交订单

        Args:
            order_request: 订单请求

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: 券商API错误
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """取消订单

        Args:
            order_id: 订单ID

        Returns:
            bool: 是否成功取消

        Raises:
            BrokerError: 券商API错误
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> OrderResponse:
        """查询订单状态

        Args:
            order_id: 订单ID

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: 券商API错误
        """
        pass

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """查询账户信息

        Returns:
            AccountInfo: 账户信息

        Raises:
            BrokerError: 券商API错误
        """
        pass

    @abstractmethod
    def get_positions(self) -> List[PositionInfo]:
        """查询持仓信息

        Returns:
            List[PositionInfo]: 持仓列表

        Raises:
            BrokerError: 券商API错误
        """
        pass

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """获取当前市场价格

        Args:
            symbol: 交易标的

        Returns:
            float: 当前价格

        Raises:
            BrokerError: 券商API错误
        """
        pass

    def execute_trade_with_retry(
        self,
        order_request: OrderRequest,
        max_retries: int = 3,
        retry_delay: float = 1.0
    ) -> OrderResponse:
        """执行交易（带重试机制）

        Args:
            order_request: 订单请求
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: 券商API错误（重试失败）
        """
        for attempt in range(max_retries):
            try:
                response = self.submit_order(order_request)

                # 记录订单历史
                self.order_history.append(response)

                # 成功执行，返回响应
                if response.status == OrderStatus.FILLED:
                    return response

                # 订单被拒绝或失败，不重试
                if response.status in [OrderStatus.REJECTED, OrderStatus.FAILED]:
                    return response

                # 订单待成交或部分成交，等待确认
                time.sleep(retry_delay)

                # 查询订单状态
                final_response = self.get_order_status(response.order_id)

                # 更新订单历史
                self.order_history[-1] = final_response

                return final_response

            except BrokerError as e:
                if attempt == max_retries - 1:
                    # 最后一次重试失败，抛出异常
                    raise e

                # 等待后重试
                time.sleep(retry_delay)

        # 重试失败，返回失败响应
        return OrderResponse(
            order_id="",
            client_order_id=order_request.client_order_id or "",
            symbol=order_request.symbol,
            side=order_request.side,
            quantity=order_request.quantity,
            filled_quantity=0,
            order_type=order_request.order_type,
            limit_price=order_request.limit_price,
            stop_price=order_request.stop_price,
            status=OrderStatus.FAILED,
            submitted_at=datetime.now(),
            filled_at=None,
            avg_fill_price=None,
            total_cost=None,
            commission=None,
            error_message="Max retries exceeded"
        )

    def wait_for_order_fill(
        self,
        order_id: str,
        timeout: float = 60.0,
        poll_interval: float = 1.0
    ) -> OrderResponse:
        """等待订单成交

        Args:
            order_id: 订单ID
            timeout: 等待超时（秒）
            poll_interval: 查询间隔（秒）

        Returns:
            OrderResponse: 最终订单响应

        Raises:
            BrokerError: 券商API错误或超时
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = self.get_order_status(order_id)

            # 订单已成交、取消或失败，返回最终状态
            if response.status in [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED]:
                return response

            # 部分成交，继续等待
            if response.status == OrderStatus.PARTIALLY_FILLED:
                time.sleep(poll_interval)
                continue

            # 待成交，继续等待
            if response.status in [OrderStatus.PENDING, OrderStatus.SUBMITTED]:
                time.sleep(poll_interval)
                continue

        # 超时，返回当前状态
        return self.get_order_status(order_id)

    def get_order_history(self, limit: int = 100) -> List[OrderResponse]:
        """获取订单历史记录

        Args:
            limit: 返回记录数量限制

        Returns:
            List[OrderResponse]: 订单历史列表
        """
        return self.order_history[-limit:]

    def get_trade_statistics(self) -> Dict[str, Any]:
        """获取交易统计信息

        Returns:
            Dict[str, Any]: 交易统计字典
        """
        total_orders = len(self.order_history)
        filled_orders = sum(1 for order in self.order_history if order.status == OrderStatus.FILLED)
        failed_orders = sum(1 for order in self.order_history if order.status in [OrderStatus.FAILED, OrderStatus.REJECTED])

        # 总成交量
        total_buy_volume = sum(order.quantity for order in self.order_history
                              if order.side == OrderSide.BUY and order.status == OrderStatus.FILLED)
        total_sell_volume = sum(order.quantity for order in self.order_history
                               if order.side == OrderSide.SELL and order.status == OrderStatus.FILLED)

        # 总成本和佣金
        total_cost = sum(order.total_cost or 0 for order in self.order_history
                        if order.status == OrderStatus.FILLED)
        total_commission = sum(order.commission or 0 for order in self.order_history
                            if order.status == OrderStatus.FILLED)

        return {
            "total_orders": total_orders,
            "filled_orders": filled_orders,
            "failed_orders": failed_orders,
            "fill_rate": filled_orders / total_orders if total_orders > 0 else 0,
            "total_buy_volume": total_buy_volume,
            "total_sell_volume": total_sell_volume,
            "total_cost": total_cost,
            "total_commission": total_commission
        }


class BrokerError(Exception):
    """券商API错误"""
    def __init__(self, message: str, error_code: Optional[str] = None, order_id: Optional[str] = None):
        super().__init__(message)
        self.error_code = error_code
        self.order_id = order_id


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("BrokerInterface使用示例（抽象基类）")
    print("="*60)
    print("\n此模块为抽象基类，需要具体券商实现（Alpaca/IBKr/Binance）")
    print("\n示例代码:")
    print("""
    from tradingagents.broker.alpaca_broker import AlpacaBroker

    # 初始化Alpaca券商接口
    broker = AlpacaBroker(api_key="YOUR_API_KEY", api_secret="YOUR_API_SECRET")

    # 连接券商API
    broker.connect()

    # 查询账户信息
    account_info = broker.get_account_info()
    print(f"可用资金: $%.2f" % account_info.cash_balance)

    # 提交买入订单
    order_request = OrderRequest(
        symbol="NVDA",
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.MARKET
    )

    order_response = broker.submit_order(order_request)
    print(f"订单ID: {order_response.order_id}")
    print(f"订单状态: {order_response.status}")

    # 查询持仓
    positions = broker.get_positions()
    for position in positions:
        print(f"{position.symbol}: {position.quantity}股，盈亏${position.unrealized_pnl:.2f}")

    # 断开连接
    broker.disconnect()
    """)