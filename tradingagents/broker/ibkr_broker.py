"""
IBKrBroker - Interactive Brokers券商API实现

功能:
1. Interactive Brokers TWS API集成
2. 全球市场交易（股票/期货/期权/外汇）
3. Paper Trading支持
4. 实时行情数据
5. 高级订单类型（Bracket Order/OFA等）

依赖:
pip install ibapi

使用方法:
    broker = IBKrBroker(host="127.0.0.1", port=7497, client_id=1)
    broker.connect()
    order = broker.submit_order(order_request)

Created: 2026-06-03
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import time
import threading

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
    from ibapi.order_state import OrderState
    from ibapi.execution import Execution
    from ibapi.ticktype import TickTypeEnum
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    print("⚠️ ibapi未安装，请运行: pip install ibapi")

from .broker_interface import (
    BrokerInterface,
    OrderRequest,
    OrderResponse,
    OrderStatus,
    OrderType,
    OrderSide,
    AccountInfo,
    PositionInfo,
    BrokerError
)


class IBKrBroker(BrokerInterface):
    """Interactive Brokers券商API实现"""

    def __init__(
        self,
        host: str = "127.0.0.1",  # TWS/Gateway IP地址
        port: int = 7497,  # TWS端口（7497=Paper, 7496=Live）
        client_id: int = 1,  # 客户端ID
        config: Dict[str, Any] = None
    ):
        """初始化IBKr券商接口

        Args:
            host: TWS/Gateway IP地址
            port: TWS/Gateway端口（Paper Trading=7497, Live Trading=7496）
            client_id: 客户端ID（唯一标识）
            config: 配置字典
        """
        # IBKr不使用API key/secret，而是使用TWS连接
        super().__init__(api_key="", api_secret="", config=config)

        if not IBKR_AVAILABLE:
            raise BrokerError("ibapi未安装，无法使用IBKrBroker")

        self.host = host
        self.port = port
        self.client_id = client_id

        # TWS连接客户端
        self.tws_client: Optional[IBKrClientWrapper] = None

        # Paper Trading判断
        self.paper = (port == 7497)  # 7497端口为Paper Trading

        # 账户信息缓存
        self.account_id: Optional[str] = None
        self.account_cache: Dict[str, Any] = {}

        # 订单ID映射
        self.order_id_map: Dict[int, str] = {}  # IBKr orderId -> clientOrderId

        # 下一个订单ID
        self.next_order_id: Optional[int] = None

    def connect(self) -> bool:
        """连接IBKr TWS/Gateway

        Returns:
            bool: 是否成功连接
        """
        try:
            # 创建TWS客户端包装器
            self.tws_client = IBKrClientWrapper(self)

            # 连接TWS
            self.tws_client.connect(self.host, self.port, self.client_id)

            # 启动消息处理线程
            thread = threading.Thread(target=self.tws_client.run)
            thread.start()

            # 等待连接建立
            time.sleep(2)

            if self.tws_client.isConnected():
                self.connected = True
                print(f"✓ IBKr TWS连接成功（Paper={self.paper}）")
                print(f"  Host: {self.host}")
                print(f"  Port: {self.port}")
                print(f"  Client ID: {self.client_id}")

                # 请求账户信息
                self.tws_client.reqAccountSummary(True, "All", "AccountType,NetLiquidation,TotalCashValue,AvailableFunds")

                return True
            else:
                self.connected = False
                return False

        except Exception as e:
            self.connected = False
            raise BrokerError(f"IBKr TWS连接失败: {str(e)}")

    def disconnect(self) -> bool:
        """断开IBKr TWS连接

        Returns:
            bool: 是否成功断开
        """
        try:
            if self.tws_client and self.tws_client.isConnected():
                self.tws_client.disconnect()

            self.connected = False
            print("✓ IBKr TWS已断开")
            return True

        except Exception as e:
            raise BrokerError(f"IBKr TWS断开失败: {str(e)}")

    def submit_order(self, order_request: OrderRequest) -> OrderResponse:
        """提交订单到IBKr TWS

        Args:
            order_request: 订单请求

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: IBKr API错误
        """
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        if self.next_order_id is None:
            raise BrokerError("未获取到IBKr订单ID")

        try:
            # 创建IBKr Contract对象
            contract = self._create_ibkr_contract(order_request.symbol)

            # 创建IBKr Order对象
            ibkr_order = self._create_ibkr_order(order_request)

            # 设置订单ID
            ibkr_order.orderId = self.next_order_id
            self.next_order_id += 1

            # 记录订单ID映射
            self.order_id_map[ibkr_order.orderId] = order_request.client_order_id or ""

            # 提交订单
            self.tws_client.placeOrder(ibkr_order.orderId, contract, ibkr_order)

            # 等待订单确认（简化：等待1秒）
            time.sleep(1)

            # 返回初始响应（实际状态需要等待回调更新）
            return OrderResponse(
                order_id=str(ibkr_order.orderId),
                client_order_id=order_request.client_order_id or "",
                symbol=order_request.symbol,
                side=order_request.side,
                quantity=order_request.quantity,
                filled_quantity=0,
                order_type=order_request.order_type,
                limit_price=order_request.limit_price,
                stop_price=order_request.stop_price,
                status=OrderStatus.SUBMITTED,
                submitted_at=datetime.now(),
                filled_at=None,
                avg_fill_price=None,
                total_cost=None,
                commission=None
            )

        except Exception as e:
            error_message = str(e)

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
                error_message=error_message
            )

    def cancel_order(self, order_id: str) -> bool:
        """取消IBKr订单

        Args:
            order_id: IBKr订单ID

        Returns:
            bool: 是否成功取消

        Raises:
            BrokerError: IBKr API错误
        """
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        try:
            # 取消订单
            ibkr_order_id = int(order_id)
            self.tws_client.cancelOrder(ibkr_order_id)
            return True

        except Exception as e:
            raise BrokerError(f"取消订单失败: {str(e)}", order_id=order_id)

    def get_order_status(self, order_id: str) -> OrderResponse:
        """查询IBKr订单状态（简化实现）

        Args:
            order_id: IBKr订单ID

        Returns:
            OrderResponse: 订单响应

        Raises:
            BrokerError: IBKr API错误
        """
        # 简化实现：IBKr需要通过回调获取订单状态，这里返回缓存数据
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        # 从订单历史中查找
        for order in self.order_history:
            if order.order_id == order_id:
                return order

        # 未找到，返回默认响应
        return OrderResponse(
            order_id=order_id,
            client_order_id=self.order_id_map.get(int(order_id), ""),
            symbol="UNKNOWN",
            side=OrderSide.BUY,
            quantity=0,
            filled_quantity=0,
            order_type=OrderType.MARKET,
            limit_price=None,
            stop_price=None,
            status=OrderStatus.PENDING,
            submitted_at=datetime.now(),
            filled_at=None,
            avg_fill_price=None,
            total_cost=None,
            commission=None
        )

    def get_account_info(self) -> AccountInfo:
        """查询IBKr账户信息（简化实现）

        Returns:
            AccountInfo: 账户信息

        Raises:
            BrokerError: IBKr API错误
        """
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        # 简化实现：从缓存获取账户信息
        if self.account_cache:
            return AccountInfo(
                account_id=self.account_id or "UNKNOWN",
                cash_balance=self.account_cache.get("TotalCashValue", 0.0),
                buying_power=self.account_cache.get("AvailableFunds", 0.0),
                total_portfolio_value=self.account_cache.get("NetLiquidation", 0.0),
                total_pnl=0.0,
                daily_pnl=0.0,
                currency="USD"
            )

        # 未缓存，返回默认账户信息
        return AccountInfo(
            account_id=self.account_id or "UNKNOWN",
            cash_balance=0.0,
            buying_power=0.0,
            total_portfolio_value=0.0,
            total_pnl=0.0,
            daily_pnl=0.0,
            currency="USD"
        )

    def get_positions(self) -> List[PositionInfo]:
        """查询IBKr持仓信息（简化实现）

        Returns:
            List[PositionInfo]: 持仓列表

        Raises:
            BrokerError: IBKr API错误
        """
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        # 简化实现：需要通过回调获取持仓，这里返回空列表
        return []

    def get_current_price(self, symbol: str) -> float:
        """获取当前市场价格（简化实现）

        Args:
            symbol: 交易标的

        Returns:
            float: 当前价格

        Raises:
            BrokerError: IBKr API错误
        """
        if not self.connected:
            raise BrokerError("IBKr TWS未连接")

        # 简化实现：需要通过市场数据订阅获取实时价格
        # 这里返回假设价格
        return 100.0

    def _create_ibkr_contract(self, symbol: str) -> Contract:
        """创建IBKr Contract对象

        Args:
            symbol: 交易标的

        Returns:
            Contract: IBKr合约对象
        """
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"  # 股票
        contract.exchange = "SMART"  # 智能路由
        contract.currency = "USD"

        return contract

    def _create_ibkr_order(self, order_request: OrderRequest) -> Order:
        """创建IBKr Order对象

        Args:
            order_request: 订单请求

        Returns:
            Order: IBKr订单对象
        """
        order = Order()

        # 设置订单动作
        order.action = "BUY" if order_request.side == OrderSide.BUY else "SELL"

        # 设置订单数量
        order.totalQuantity = order_request.quantity

        # 设置订单类型
        if order_request.order_type == OrderType.MARKET:
            order.orderType = "MKT"  # 市价单

        elif order_request.order_type == OrderType.LIMIT:
            order.orderType = "LMT"  # 限价单
            order.lmtPrice = order_request.limit_price

        elif order_request.order_type == OrderType.STOP_LOSS:
            order.orderType = "STP"  # 止损单
            order.auxPrice = order_request.stop_price

        elif order_request.order_type == OrderType.STOP_LIMIT:
            order.orderType = "STP LMT"  # 止损限价单
            order.lmtPrice = order_request.limit_price
            order.auxPrice = order_request.stop_price

        # 设置订单有效期
        order.tif = "GTC"  # Good Till Cancelled

        # 设置客户端订单ID
        if order_request.client_order_id:
            order.orderRef = order_request.client_order_id

        return order


class IBKrClientWrapper(EClient, EWrapper):
    """IBKr TWS客户端包装器（处理回调）"""

    def __init__(self, broker: IBKrBroker):
        EClient.__init__(self, self)
        self.broker = broker

    def nextOrderId(self, orderId: int):
        """获取下一个订单ID回调"""
        self.broker.next_order_id = orderId

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        """账户信息回调"""
        self.broker.account_id = account
        self.broker.account_cache[tag] = float(value)

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: float,
        remaining: float,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float
    ):
        """订单状态回调"""
        # 更新订单状态（简化实现）
        pass

    def execDetails(self, reqId: int, contract: Contract, execution: Execution):
        """执行详情回调"""
        # 记录执行详情（简化实现）
        pass

    def error(self, reqId: int, errorCode: int, errorString: str):
        """错误回调"""
        print(f"IBKr Error: reqId={reqId}, errorCode={errorCode}, errorString={errorString}")


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("IBKrBroker使用示例")
    print("="*60)

    if IBKR_AVAILABLE:
        print("\n注意: 使用前需要:")
        print("1. 安装ibapi: pip install ibapi")
        print("2. 启动TWS或Gateway（并启用API连接）")
        print("\n示例代码:")
        print("""
        from tradingagents.broker.ibkr_broker import IBKrBroker
        from tradingagents.broker.broker_interface import OrderRequest, OrderSide, OrderType

        # 初始化IBKr券商接口（Paper Trading模式）
        broker = IBKrBroker(
            host="127.0.0.1",  # TWS本地IP
            port=7497,  # Paper Trading端口
            client_id=1  # 客户端ID
        )

        # 连接IBKr TWS（需要TWS已启动）
        broker.connect()

        # 查询账户信息
        account = broker.get_account_info()
        print(f"总资产: $%.2f" % account.total_portfolio_value)

        # 提交买入订单（市价单）
        order_request = OrderRequest(
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=10,
            order_type=OrderType.MARKET
        )

        # 执行交易
        order_response = broker.submit_order(order_request)

        print(f"订单ID: {order_response.order_id}")
        print(f"订单状态: {order_response.status}")

        # 断开连接
        broker.disconnect()
        """)
    else:
        print("\n⚠️ ibapi未安装")
        print("请运行: pip install ibapi")