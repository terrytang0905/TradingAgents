"""
RiskController - 硬性风险控制模块

功能:
1. 止损控制（Stop Loss）
2. 止盈控制（Take Profit）
3. 仓位管理（Position Sizing）
4. 最大回撤限制（Max Drawdown Limit）

使用方法:
    risk_controller = RiskController()
    safe_decision = risk_controller.enforce_risk_limits(decision, portfolio_state)

Created: 2026-06-03
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime
import json


@dataclass
class RiskLimits:
    """风险限制参数"""
    max_position_size: float = 0.10  # 最大仓位比例（10%）
    max_daily_loss: float = -0.05  # 最大单日亏损（-5%）
    max_total_loss: float = -0.15  # 最大总亏损（-15%）
    stop_loss_threshold: float = -0.08  # 止损阈值（-8%）
    take_profit_threshold: float = 0.15  # 止盈阈值（15%）
    max_drawdown_limit: float = 0.20  # 最大回撤限制（20%）
    max_consecutive_losses: int = 3  # 最大连续亏损次数


@dataclass
class PortfolioState:
    """组合状态"""
    total_capital: float
    current_position_size: float
    current_position_value: float
    current_pnl: float  # 当前盈亏
    current_return: float  # 当前收益率
    daily_pnl: float  # 单日盈亏
    max_drawdown: float  # 最大回撤
    consecutive_losses: int  # 连续亏损次数
    last_trade_date: Optional[datetime] = None


@dataclass
class TradingDecision:
    """交易决策"""
    action: str  # BUY/SELL/HOLD
    ticker: str
    position_size: float  # 建议仓位比例
    confidence: float  # 决策置信度
    reasoning: str  # 决策理由
    raw_decision: str  # 原始LLM决策文本


@dataclass
class RiskControlResult:
    """风控结果"""
    approved: bool  # 是否批准
    final_action: str  # 最终动作（可能被修改）
    final_position_size: float  # 最终仓位（可能被调整）
    risk_warnings: list  # 风险警告列表
    risk_metrics: Dict[str, float]  # 风险指标
    enforcement_reasons: list  # 强制执行原因


class RiskController:
    """硬性风险控制器"""

    def __init__(self, config: Dict[str, Any] = None):
        """初始化风险控制器

        Args:
            config: 配置字典，包含风险限制参数
        """
        self.risk_limits = RiskLimits()

        # 应用自定义配置
        if config:
            for key, value in config.items():
                if hasattr(self.risk_limits, key):
                    setattr(self.risk_limits, key, value)

        self.risk_log = []  # 风控日志

    def enforce_risk_limits(
        self,
        decision: TradingDecision,
        portfolio_state: PortfolioState
    ) -> RiskControlResult:
        """执行硬性风控检查

        Args:
            decision: 交易决策
            portfolio_state: 组合状态

        Returns:
            RiskControlResult: 风控结果
        """
        warnings = []
        enforcement_reasons = []
        risk_metrics = self._calculate_risk_metrics(portfolio_state)

        # Step 1: 仓位限制检查
        if decision.action == "BUY":
            if decision.position_size > self.risk_limits.max_position_size:
                warnings.append(
                    f"仓位超限: 建议{decision.position_size:.2%} > 最大{self.risk_limits.max_position_size:.2%}"
                )
                enforcement_reasons.append("强制限制仓位至最大值")
                final_position_size = self.risk_limits.max_position_size
            else:
                final_position_size = decision.position_size
        else:
            final_position_size = 0.0

        final_action = decision.action
        approved = True

        # Portfolio-level limits are evaluated independently so a trade-level
        # stop cannot hide a more severe portfolio breach.
        if portfolio_state.current_pnl <= self.risk_limits.max_total_loss * portfolio_state.total_capital:
            warnings.append(
                f"总亏损超限: ${portfolio_state.current_pnl:.2f} <= 最大${self.risk_limits.max_total_loss * portfolio_state.total_capital:.2f}"
            )
            enforcement_reasons.append("强制清仓止损")
            final_action = "SELL"
            final_position_size = 0.0
            approved = False

        if portfolio_state.max_drawdown >= self.risk_limits.max_drawdown_limit:
            warnings.append(
                f"回撤超限: {portfolio_state.max_drawdown:.2%} >= 最大{self.risk_limits.max_drawdown_limit:.2%}"
            )
            enforcement_reasons.append("限制交易（降低仓位）")
            final_position_size = min(final_position_size, 0.05)
            approved = False

        # Step 2: 止损检查
        if portfolio_state.current_return <= self.risk_limits.stop_loss_threshold:
            warnings.append(
                f"触发止损: 当前收益率{portfolio_state.current_return:.2%} <= 止损阈值{self.risk_limits.stop_loss_threshold:.2%}"
            )
            enforcement_reasons.append("强制止损卖出")
            final_action = "SELL"
            approved = False

        # Step 3: 止盈检查
        elif portfolio_state.current_return >= self.risk_limits.take_profit_threshold:
            warnings.append(
                f"触发止盈: 当前收益率{portfolio_state.current_return:.2%} >= 止盈阈值{self.risk_limits.take_profit_threshold:.2%}"
            )
            enforcement_reasons.append("强制止盈卖出")
            final_action = "SELL"
            approved = True

        # Step 4: 最大单日亏损检查
        elif portfolio_state.daily_pnl <= self.risk_limits.max_daily_loss * portfolio_state.total_capital:
            warnings.append(
                f"单日亏损超限: ${portfolio_state.daily_pnl:.2f} <= 最大${self.risk_limits.max_daily_loss * portfolio_state.total_capital:.2f}"
            )
            enforcement_reasons.append("限制当日交易（暂停买入）")
            if decision.action == "BUY":
                final_action = "HOLD"
                approved = False
            else:
                final_action = decision.action
                approved = True

        # Step 7: 连续亏损检查
        elif portfolio_state.consecutive_losses >= self.risk_limits.max_consecutive_losses:
            warnings.append(
                f"连续亏损超限: {portfolio_state.consecutive_losses}次 >= 最大{self.risk_limits.max_consecutive_losses}次"
            )
            enforcement_reasons.append("暂停交易（冷却期）")
            final_action = "HOLD"
            approved = False

        # 记录风控日志
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "ticker": decision.ticker,
            "original_action": decision.action,
            "final_action": final_action,
            "approved": approved,
            "warnings": warnings,
            "risk_metrics": risk_metrics
        }
        self.risk_log.append(log_entry)

        # 返回风控结果
        return RiskControlResult(
            approved=approved,
            final_action=final_action,
            final_position_size=final_position_size,
            risk_warnings=warnings,
            risk_metrics=risk_metrics,
            enforcement_reasons=enforcement_reasons
        )

    def _calculate_risk_metrics(self, portfolio_state: PortfolioState) -> Dict[str, float]:
        """计算风险指标

        Args:
            portfolio_state: 组合状态

        Returns:
            Dict[str, float]: 风险指标字典
        """
        return {
            "current_return": portfolio_state.current_return,
            "current_pnl": portfolio_state.current_pnl,
            "daily_pnl": portfolio_state.daily_pnl,
            "max_drawdown": portfolio_state.max_drawdown,
            "position_ratio": portfolio_state.current_position_size,
            "consecutive_losses": portfolio_state.consecutive_losses,
            "sharpe_ratio": self._estimate_sharpe_ratio(portfolio_state),
            "volatility": self._estimate_volatility(portfolio_state)
        }

    def _estimate_sharpe_ratio(self, portfolio_state: PortfolioState) -> float:
        """估算夏普比率（简化版本）

        Args:
            portfolio_state: 组合状态

        Returns:
            float: 夏普比率估算值
        """
        # 简化估算：收益率 / 波动率
        if portfolio_state.current_return == 0:
            return 0.0

        volatility = self._estimate_volatility(portfolio_state)
        if volatility == 0:
            return 0.0

        return portfolio_state.current_return / volatility

    def _estimate_volatility(self, portfolio_state: PortfolioState) -> float:
        """估算波动率（简化版本）

        Args:
            portfolio_state: 组合状态

        Returns:
            float: 波动率估算值
        """
        # 简化估算：基于最大回撤
        if portfolio_state.max_drawdown > 0:
            return portfolio_state.max_drawdown * 1.5  # 保守估算
        else:
            return 0.10  # 默认波动率10%

    def get_risk_report(self) -> str:
        """生成风控报告

        Returns:
            str: 风控报告文本
        """
        report = f"""
风险控制报告
生成时间: {datetime.now().isoformat()}

风险限制参数:
- 最大仓位比例: {self.risk_limits.max_position_size:.2%}
- 最大单日亏损: {self.risk_limits.max_daily_loss:.2%}
- 最大总亏损: {self.risk_limits.max_total_loss:.2%}
- 止损阈值: {self.risk_limits.stop_loss_threshold:.2%}
- 止盈阈值: {self.risk_limits.take_profit_threshold:.2%}
- 最大回撤限制: {self.risk_limits.max_drawdown_limit:.2%}
- 最大连续亏损次数: {self.risk_limits.max_consecutive_losses}

风控日志统计:
- 总检查次数: {len(self.risk_log)}
- 批准次数: {sum(1 for log in self.risk_log if log['approved'])}
- 拒绝次数: {sum(1 for log in self.risk_log if not log['approved'])}
- 止损触发次数: {sum(1 for log in self.risk_log if '止损' in str(log['warnings']))}
- 止盈触发次数: {sum(1 for log in self.risk_log if '止盈' in str(log['warnings']))}

最近5次风控记录:
"""
        # 添加最近5次记录
        for log in self.risk_log[-5:]:
            report += f"""
时间: {log['timestamp']}
Ticker: {log['ticker']}
原始动作: {log['original_action']} -> 最终动作: {log['final_action']}
批准状态: {log['approved']}
警告: {log['warnings']}
"""
        return report

    def save_risk_log(self, filepath: str):
        """保存风控日志到JSON文件

        Args:
            filepath: 文件路径
        """
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.risk_log, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("RiskController使用示例")
    print("="*60)

    # 初始化风控器
    risk_controller = RiskController()

    # 创建测试组合状态
    portfolio_state = PortfolioState(
        total_capital=100000,
        current_position_size=0.12,  # 当前仓位12%
        current_position_value=12000,
        current_pnl=-5000,  # 当前亏损$5000
        current_return=-0.05,  # 当前收益率-5%
        daily_pnl=-3000,  # 单日亏损$3000
        max_drawdown=0.15,  # 最大回撤15%
        consecutive_losses=2  # 连续亏损2次
    )

    # 创建测试决策
    decision = TradingDecision(
        action="BUY",
        ticker="NVDA",
        position_size=0.15,  # 建议仓位15%（超限）
        confidence=0.85,
        reasoning="市场趋势向上，技术指标看涨",
        raw_decision="BUY NVDA with high confidence"
    )

    # 执行风控检查
    result = risk_controller.enforce_risk_limits(decision, portfolio_state)

    # 打印结果
    print(f"\n原始决策: {decision.action} {decision.ticker} (建议仓位{decision.position_size:.2%})")
    print(f"风控结果: {result.final_action} (最终仓位{result.final_position_size:.2%})")
    print(f"批准状态: {result.approved}")
    print(f"\n风险警告:")
    for warning in result.risk_warnings:
        print(f"  - {warning}")

    print(f"\n强制执行原因:")
    for reason in result.enforcement_reasons:
        print(f"  - {reason}")

    # 生成风控报告
    print("\n" + "="*60)
    print(risk_controller.get_risk_report())
