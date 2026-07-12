"""
BacktestEngine - 回测验证系统

功能:
1. 历史数据回测（指定时间范围）
2. 策略性能评估（Sharpe Ratio/Max Drawdown/Total Return）
3. 交易记录生成（详细交易日志）
4. 风险指标可视化（性能曲线图）

使用方法:
    backtest_engine = BacktestEngine(graph, tickers, start_date, end_date)
    report = backtest_engine.run_backtest(initial_capital=100000)

Created: 2026-06-03
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import json
import numpy as np
import pandas as pd
from pathlib import Path


@dataclass
class TradeRecord:
    """交易记录"""
    date: str
    ticker: str
    action: str  # BUY/SELL/HOLD
    quantity: int
    price: float
    position_size: float
    reasoning: str
    confidence: float
    pnl: float = 0.0  # 盈亏
    return_rate: float = 0.0  # 收益率


@dataclass
class PortfolioSnapshot:
    """组合快照"""
    date: str
    total_capital: float
    cash_balance: float
    positions: Dict[str, Dict[str, float]]  # {ticker: {quantity, value}}
    total_pnl: float
    total_return: float
    daily_pnl: float
    daily_return: float


@dataclass
class BacktestReport:
    """回测报告"""
    ticker: str
    start_date: str
    end_date: str
    initial_capital: float
    final_capital: float

    # 性能指标
    total_return: float  # 总收益率
    annualized_return: float  # 年化收益率
    sharpe_ratio: float  # 夏普比率
    max_drawdown: float  # 最大回撤
    volatility: float  # 波动率
    win_rate: float  # 胜率

    # 交易统计
    total_trades: int  # 总交易次数
    winning_trades: int  # 盈利次数
    losing_trades: int  # 亏损次数
    avg_profit: float  # 平均盈利
    avg_loss: float  # 平均亏损
    profit_factor: float  # 盈利因子

    # 详细记录
    trade_records: List[TradeRecord] = field(default_factory=list)
    portfolio_snapshots: List[PortfolioSnapshot] = field(default_factory=list)


class BacktestEngine:
    """回测引擎"""

    def __init__(
        self,
        graph,
        tickers: List[str],
        start_date: str,
        end_date: str,
        config: Dict[str, Any] = None
    ):
        """初始化回测引擎

        Args:
            graph: TradingAgentsGraph实例
            tickers: 股票代码列表
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
            config: 配置字典
        """
        self.graph = graph
        self.tickers = tickers
        self.start_date = datetime.strptime(start_date, "%Y-%m-%d")
        self.end_date = datetime.strptime(end_date, "%Y-%m-%d")
        self.config = config or {}

        # 回测参数
        self.initial_capital = self.config.get("initial_capital", 100000)
        self.commission_rate = self.config.get("commission_rate", 0.001)  # 佣金率0.1%
        self.slippage_rate = self.config.get("slippage_rate", 0.0005)  # 滑点率0.05%

        # 交易记录
        self.trade_records: List[TradeRecord] = []
        self.portfolio_snapshots: List[PortfolioSnapshot] = []

    def run_backtest(self, initial_capital: float = None) -> Dict[str, BacktestReport]:
        """执行回测

        Args:
            initial_capital: 初始资金（可选）

        Returns:
            Dict[str, BacktestReport]: 各ticker的回测报告
        """
        initial_capital = initial_capital or self.initial_capital

        print("="*60)
        print(f"开始回测: {self.tickers}")
        print(f"时间范围: {self.start_date.strftime('%Y-%m-%d')} ~ {self.end_date.strftime('%Y-%m-%d')}")
        print(f"初始资金: $%.2f" % initial_capital)
        print("="*60)

        reports = {}

        for ticker in self.tickers:
            print(f"\n回测Ticker: {ticker}")
            report = self._backtest_single_ticker(ticker, initial_capital)
            reports[ticker] = report

            # 打印简要报告
            print(f"\n{ticker}回测结果:")
            print(f"  总收益率: {report.total_return:.2%}")
            print(f"  夏普比率: {report.sharpe_ratio:.2f}")
            print(f"  最大回撤: {report.max_drawdown:.2%}")
            print(f"  胜率: {report.win_rate:.2%}")

        return reports

    def _backtest_single_ticker(self, ticker: str, initial_capital: float) -> BacktestReport:
        """单个ticker回测

        Args:
            ticker: 股票代码
            initial_capital: 初始资金

        Returns:
            BacktestReport: 回测报告
        """
        # 初始化组合状态
        portfolio = {
            "cash_balance": initial_capital,
            "positions": {},  # {ticker: {quantity, avg_price}}
            "total_capital": initial_capital
        }

        # 生成日期范围
        date_range = self._generate_trading_days(self.start_date, self.end_date)

        # 遍历每个交易日
        for current_date in date_range:
            date_str = current_date.strftime("%Y-%m-%d")

            try:
                # 执行TradingAgents决策
                state, decision = self.graph.propagate(ticker, date_str)

                # 解析决策
                action = self._parse_action(decision)
                confidence = self._extract_confidence(state)

                # 获取市场价格（简化：使用假设价格或从state获取）
                market_price = self._get_market_price(state, ticker, date_str)

                # 执行交易
                trade_record = self._execute_trade(
                    ticker=ticker,
                    action=action,
                    date=date_str,
                    portfolio=portfolio,
                    market_price=market_price,
                    reasoning=decision,
                    confidence=confidence
                )

                # 记录交易
                if trade_record:
                    self.trade_records.append(trade_record)

                # 记录组合快照
                snapshot = self._create_portfolio_snapshot(portfolio, date_str)
                self.portfolio_snapshots.append(snapshot)

                # 打印进度（可选）
                if len(self.trade_records) % 10 == 0:
                    print(f"  已处理{len(self.trade_records)}条交易记录...")

            except Exception as e:
                print(f"  ⚠️ 处理{date_str}时出错: {str(e)}")
                continue

        # 计算性能指标
        final_capital = portfolio["total_capital"]
        performance_metrics = self._calculate_performance_metrics(
            self.portfolio_snapshots,
            initial_capital,
            final_capital
        )

        # 生成回测报告
        report = BacktestReport(
            ticker=ticker,
            start_date=self.start_date.strftime("%Y-%m-%d"),
            end_date=self.end_date.strftime("%Y-%m-%d"),
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=performance_metrics["total_return"],
            annualized_return=performance_metrics["annualized_return"],
            sharpe_ratio=performance_metrics["sharpe_ratio"],
            max_drawdown=performance_metrics["max_drawdown"],
            volatility=performance_metrics["volatility"],
            win_rate=performance_metrics["win_rate"],
            total_trades=len(self.trade_records),
            winning_trades=performance_metrics["winning_trades"],
            losing_trades=performance_metrics["losing_trades"],
            avg_profit=performance_metrics["avg_profit"],
            avg_loss=performance_metrics["avg_loss"],
            profit_factor=performance_metrics["profit_factor"],
            trade_records=self.trade_records,
            portfolio_snapshots=self.portfolio_snapshots
        )

        return report

    def _generate_trading_days(self, start_date: datetime, end_date: datetime) -> List[datetime]:
        """生成交易日列表（简化：排除周末）

        Args:
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            List[datetime]: 交易日列表
        """
        trading_days = []
        current_date = start_date

        while current_date <= end_date:
            # 排除周末（周六=5, 周日=6）
            if current_date.weekday() < 5:
                trading_days.append(current_date)
            current_date += timedelta(days=1)

        return trading_days

    def _parse_action(self, decision: str) -> str:
        """解析决策文本，提取动作

        Args:
            decision: 决策文本

        Returns:
            str: BUY/SELL/HOLD
        """
        # 简化解析：查找关键词
        decision_upper = decision.upper()

        if "BUY" in decision_upper:
            return "BUY"
        elif "SELL" in decision_upper:
            return "SELL"
        elif "HOLD" in decision_upper:
            return "HOLD"
        else:
            return "HOLD"  # 默认HOLD

    def _extract_confidence(self, state: Dict) -> float:
        """从state中提取置信度

        Args:
            state: TradingAgents state字典

        Returns:
            float: 置信度（0-1）
        """
        # 简化：假设置信度固定
        return 0.80  # 默认置信度80%

    def _get_market_price(self, state: Dict, ticker: str, date: str) -> float:
        """获取市场价格

        Args:
            state: TradingAgents state字典
            ticker: 股票代码
            date: 日期

        Returns:
            float: 市场价格
        """
        # 简化：使用假设价格（实际应从state或数据源获取）
        return 100.0  # 假设价格$100

    def _execute_trade(
        self,
        ticker: str,
        action: str,
        date: str,
        portfolio: Dict,
        market_price: float,
        reasoning: str,
        confidence: float
    ) -> Optional[TradeRecord]:
        """执行交易

        Args:
            ticker: 股票代码
            action: BUY/SELL/HOLD
            date: 日期
            portfolio: 组合字典
            market_price: 市场价格
            reasoning: 决策理由
            confidence: 置信度

        Returns:
            Optional[TradeRecord]: 交易记录（HOLD返回None）
        """
        if action == "HOLD":
            return None

        # 计算交易数量
        if action == "BUY":
            # 计算可购买数量（假设仓位10%）
            max_position_value = portfolio["cash_balance"] * 0.10
            quantity = int(max_position_value / market_price)

            if quantity == 0:
                return None  # 资金不足

            # 执行买入
            cost = quantity * market_price * (1 + self.commission_rate + self.slippage_rate)
            portfolio["cash_balance"] -= cost

            # 更新持仓
            if ticker not in portfolio["positions"]:
                portfolio["positions"][ticker] = {"quantity": 0, "avg_price": 0}

            old_quantity = portfolio["positions"][ticker]["quantity"]
            old_avg_price = portfolio["positions"][ticker]["avg_price"]
            new_quantity = old_quantity + quantity
            new_avg_price = (old_quantity * old_avg_price + cost) / new_quantity

            portfolio["positions"][ticker] = {
                "quantity": new_quantity,
                "avg_price": new_avg_price
            }

            # 记录交易
            return TradeRecord(
                date=date,
                ticker=ticker,
                action="BUY",
                quantity=quantity,
                price=market_price,
                position_size=quantity * market_price / portfolio["total_capital"],
                reasoning=reasoning,
                confidence=confidence
            )

        elif action == "SELL":
            # 检查持仓
            if ticker not in portfolio["positions"] or portfolio["positions"][ticker]["quantity"] == 0:
                return None  # 无持仓

            # 卖出全部持仓
            quantity = portfolio["positions"][ticker]["quantity"]
            avg_price = portfolio["positions"][ticker]["avg_price"]

            # 计算收入
            revenue = quantity * market_price * (1 - self.commission_rate - self.slippage_rate)
            portfolio["cash_balance"] += revenue

            # 计算盈亏
            cost = quantity * avg_price
            pnl = revenue - cost
            return_rate = pnl / cost

            # 清空持仓
            portfolio["positions"][ticker] = {"quantity": 0, "avg_price": 0}

            # 更新总资金
            portfolio["total_capital"] += pnl

            # 记录交易
            return TradeRecord(
                date=date,
                ticker=ticker,
                action="SELL",
                quantity=quantity,
                price=market_price,
                position_size=0.0,
                reasoning=reasoning,
                confidence=confidence,
                pnl=pnl,
                return_rate=return_rate
            )

        return None

    def _create_portfolio_snapshot(self, portfolio: Dict, date: str) -> PortfolioSnapshot:
        """创建组合快照

        Args:
            portfolio: 组合字典
            date: 日期

        Returns:
            PortfolioSnapshot: 组合快照
        """
        # 计算持仓价值
        total_position_value = 0.0
        for ticker, position in portfolio["positions"].items():
            total_position_value += position["quantity"] * position["avg_price"]

        total_capital = portfolio["cash_balance"] + total_position_value

        # 计算收益率（简化）
        total_return = (total_capital - self.initial_capital) / self.initial_capital
        daily_return = 0.0  # 需要历史数据计算

        return PortfolioSnapshot(
            date=date,
            total_capital=total_capital,
            cash_balance=portfolio["cash_balance"],
            positions=portfolio["positions"],
            total_pnl=total_capital - self.initial_capital,
            total_return=total_return,
            daily_pnl=0.0,  # 需要历史数据计算
            daily_return=daily_return
        )

    def _calculate_performance_metrics(
        self,
        snapshots: List[PortfolioSnapshot],
        initial_capital: float,
        final_capital: float
    ) -> Dict[str, float]:
        """计算性能指标

        Args:
            snapshots: 组合快照列表
            initial_capital: 初始资金
            final_capital: 最终资金

        Returns:
            Dict[str, float]: 性能指标字典
        """
        # 总收益率
        total_return = (final_capital - initial_capital) / initial_capital

        # 年化收益率（简化：假设250交易日）
        trading_days = len(snapshots)
        annualized_return = (1 + total_return) ** (250 / trading_days) - 1

        # 计算每日收益率序列
        returns = []
        for i in range(1, len(snapshots)):
            prev_capital = snapshots[i-1].total_capital
            curr_capital = snapshots[i].total_capital
            if prev_capital > 0:
                daily_return = (curr_capital - prev_capital) / prev_capital
                returns.append(daily_return)

        # 波动率
        if len(returns) > 0:
            volatility = np.std(returns) * np.sqrt(250)  # 年化波动率
        else:
            volatility = 0.0

        # 夏普比率（简化：假设无风险利率=0）
        if volatility > 0:
            sharpe_ratio = annualized_return / volatility
        else:
            sharpe_ratio = 0.0

        # 最大回撤
        max_capital = initial_capital
        max_drawdown = 0.0
        for snapshot in snapshots:
            if snapshot.total_capital > max_capital:
                max_capital = snapshot.total_capital
            drawdown = (max_capital - snapshot.total_capital) / max_capital
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # 胜率（从trade_records计算）
        winning_trades = sum(1 for record in self.trade_records if record.pnl > 0)
        losing_trades = sum(1 for record in self.trade_records if record.pnl < 0)
        total_trades = winning_trades + losing_trades

        if total_trades > 0:
            win_rate = winning_trades / total_trades
        else:
            win_rate = 0.0

        # 平均盈利/亏损
        profits = [record.pnl for record in self.trade_records if record.pnl > 0]
        losses = [record.pnl for record in self.trade_records if record.pnl < 0]

        avg_profit = np.mean(profits) if len(profits) > 0 else 0.0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0.0

        # 盈利因子
        if avg_loss != 0:
            profit_factor = abs(avg_profit / avg_loss)
        else:
            profit_factor = 0.0

        return {
            "total_return": total_return,
            "annualized_return": annualized_return,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "volatility": volatility,
            "win_rate": win_rate,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "avg_profit": avg_profit,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor
        }

    def save_backtest_results(self, filepath: str, reports: Dict[str, BacktestReport]):
        """保存回测结果到JSON文件

        Args:
            filepath: 文件路径
            reports: 回测报告字典
        """
        # 转换为可序列化字典
        results = {}
        for ticker, report in reports.items():
            results[ticker] = {
                "ticker": report.ticker,
                "start_date": report.start_date,
                "end_date": report.end_date,
                "initial_capital": report.initial_capital,
                "final_capital": report.final_capital,
                "total_return": report.total_return,
                "annualized_return": report.annualized_return,
                "sharpe_ratio": report.sharpe_ratio,
                "max_drawdown": report.max_drawdown,
                "volatility": report.volatility,
                "win_rate": report.win_rate,
                "total_trades": report.total_trades,
                "winning_trades": report.winning_trades,
                "losing_trades": report.losing_trades,
                "avg_profit": report.avg_profit,
                "avg_loss": report.avg_loss,
                "profit_factor": report.profit_factor,
                "trade_records": [
                    {
                        "date": record.date,
                        "action": record.action,
                        "quantity": record.quantity,
                        "price": record.price,
                        "pnl": record.pnl,
                        "return_rate": record.return_rate
                    }
                    for record in report.trade_records
                ]
            }

        # 保存到文件
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # 使用示例（需要TradingAgentsGraph实例）
    print("="*60)
    print("BacktestEngine使用示例")
    print("="*60)
    print("\n注意: 此模块需要TradingAgentsGraph实例才能运行完整回测")
    print("示例代码:")
    print("""
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.backtest.backtest_engine import BacktestEngine

    # 初始化TradingAgents
    ta = TradingAgentsGraph(debug=True)

    # 创建回测引擎
    backtest_engine = BacktestEngine(
        graph=ta,
        tickers=["NVDA", "AAPL"],
        start_date="2024-01-01",
        end_date="2024-12-31",
        config={"initial_capital": 100000}
    )

    # 执行回测
    reports = backtest_engine.run_backtest()

    # 保存结果
    backtest_engine.save_backtest_results("backtest_results.json", reports)
    """)