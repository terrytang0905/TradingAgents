"""
TradingAgents单元测试 - 测试核心模块逻辑正确性

测试覆盖:
1. RiskController风控逻辑测试
2. Memory记忆检索测试
3. Agent决策逻辑测试
4. BacktestEngine回测逻辑测试

运行方法:
    python -m pytest tests/ -v

Created: 2026-06-03
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tradingagents.risk_management.risk_controller import (
    RiskController,
    RiskLimits,
    PortfolioState,
    TradingDecision,
    RiskControlResult
)


class TestRiskController:
    """RiskController单元测试"""

    def setup_method(self):
        """每个测试方法前初始化"""
        self.risk_controller = RiskController()

        # 创建测试组合状态（正常情况）
        self.normal_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=5000,
            current_return=0.05,
            daily_pnl=1000,
            max_drawdown=0.10,
            consecutive_losses=0
        )

        # 创建测试决策（BUY建议）
        self.buy_decision = TradingDecision(
            action="BUY",
            ticker="NVDA",
            position_size=0.12,  # 超过限制（10%）
            confidence=0.85,
            reasoning="市场趋势向上",
            raw_decision="BUY NVDA"
        )

    def test_risk_controller_initialization(self):
        """测试RiskController初始化"""
        controller = RiskController()

        # 验证默认风险限制参数
        assert controller.risk_limits.max_position_size == 0.10
        assert controller.risk_limits.stop_loss_threshold == -0.08
        assert controller.risk_limits.take_profit_threshold == 0.15
        assert controller.risk_limits.max_drawdown_limit == 0.20

    def test_risk_controller_custom_config(self):
        """测试自定义配置"""
        custom_config = {
            "max_position_size": 0.15,
            "stop_loss_threshold": -0.10,
            "take_profit_threshold": 0.20
        }

        controller = RiskController(config=custom_config)

        # 验证自定义参数生效
        assert controller.risk_limits.max_position_size == 0.15
        assert controller.risk_limits.stop_loss_threshold == -0.10
        assert controller.risk_limits.take_profit_threshold == 0.20

    def test_position_size_limit_enforcement(self):
        """测试仓位限制强制执行"""
        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            self.normal_portfolio
        )

        # 验证仓位被限制到最大值
        assert result.final_position_size <= self.risk_controller.risk_limits.max_position_size
        assert "仓位超限" in str(result.risk_warnings)

    def test_stop_loss_trigger(self):
        """测试止损触发"""
        # 创建触发止损的组合状态
        stop_loss_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=-8500,
            current_return=-0.085,  # 超过止损阈值-8%
            daily_pnl=-8500,
            max_drawdown=0.085,
            consecutive_losses=0
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            stop_loss_portfolio
        )

        # 验证强制止损卖出
        assert result.final_action == "SELL"
        assert "止损" in str(result.risk_warnings)
        assert result.approved == False

    def test_take_profit_trigger(self):
        """测试止盈触发"""
        # 创建触发止盈的组合状态
        take_profit_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=16000,
            current_return=0.16,  # 超过止盈阈值15%
            daily_pnl=16000,
            max_drawdown=0.05,
            consecutive_losses=0
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            take_profit_portfolio
        )

        # 验证强制止盈卖出
        assert result.final_action == "SELL"
        assert "止盈" in str(result.risk_warnings)
        assert result.approved == True

    def test_max_daily_loss_limit(self):
        """测试最大单日亏损限制"""
        # 创建触发单日亏损限制的组合状态
        daily_loss_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=-5000,
            current_return=-0.05,
            daily_pnl=-5500,  # 超过单日亏损限制（-5% * 100000 = -5000）
            max_drawdown=0.10,
            consecutive_losses=0
        )

        # 执行风控检查（BUY决策）
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            daily_loss_portfolio
        )

        # 验证限制买入
        assert result.final_action == "HOLD"
        assert "单日亏损超限" in str(result.risk_warnings)
        assert result.approved == False

    def test_max_total_loss_limit(self):
        """测试最大总亏损限制"""
        # 创建触发总亏损限制的组合状态
        total_loss_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=-16000,  # 超过总亏损限制（-15% * 100000 = -15000）
            current_return=-0.16,
            daily_pnl=-2000,
            max_drawdown=0.16,
            consecutive_losses=0
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            total_loss_portfolio
        )

        # 验证强制清仓
        assert result.final_action == "SELL"
        assert "总亏损超限" in str(result.risk_warnings)
        assert result.approved == False

    def test_max_drawdown_limit(self):
        """测试最大回撤限制"""
        # 创建触发回撤限制的组合状态
        drawdown_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=-20000,
            current_return=-0.20,
            daily_pnl=-1000,
            max_drawdown=0.21,  # 超过回撤限制20%
            consecutive_losses=0
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            drawdown_portfolio
        )

        # 验证仓位被强制降低
        assert result.final_position_size <= 0.05
        assert "回撤超限" in str(result.risk_warnings)
        assert result.approved == False

    def test_consecutive_losses_limit(self):
        """测试连续亏损次数限制"""
        # 创建触发连续亏损限制的组合状态
        consecutive_losses_portfolio = PortfolioState(
            total_capital=100000,
            current_position_size=0.08,
            current_position_value=8000,
            current_pnl=-5000,
            current_return=-0.05,
            daily_pnl=-1000,
            max_drawdown=0.10,
            consecutive_losses=3  # 达到连续亏损限制
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            consecutive_losses_portfolio
        )

        # 验证暂停交易
        assert result.final_action == "HOLD"
        assert "连续亏损超限" in str(result.risk_warnings)
        assert result.approved == False

    def test_normal_decision_approval(self):
        """测试正常决策批准"""
        # 创建正常决策（不触发任何风控限制）
        normal_decision = TradingDecision(
            action="BUY",
            ticker="AAPL",
            position_size=0.08,  # 在限制范围内
            confidence=0.85,
            reasoning="基本面良好",
            raw_decision="BUY AAPL"
        )

        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            normal_decision,
            self.normal_portfolio
        )

        # 验证决策被批准
        assert result.approved == True
        assert result.final_action == "BUY"
        assert len(result.risk_warnings) == 0

    def test_risk_metrics_calculation(self):
        """测试风险指标计算"""
        # 执行风控检查
        result = self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            self.normal_portfolio
        )

        # 验证风险指标存在
        assert "current_return" in result.risk_metrics
        assert "current_pnl" in result.risk_metrics
        assert "max_drawdown" in result.risk_metrics
        assert "sharpe_ratio" in result.risk_metrics
        assert "volatility" in result.risk_metrics

    def test_risk_log_recording(self):
        """测试风控日志记录"""
        # 执行多次风控检查
        for i in range(5):
            decision = TradingDecision(
                action="BUY",
                ticker="TEST",
                position_size=0.10,
                confidence=0.85,
                reasoning="测试",
                raw_decision="BUY TEST"
            )
            self.risk_controller.enforce_risk_limits(decision, self.normal_portfolio)

        # 验证日志记录数量
        assert len(self.risk_controller.risk_log) == 5

    def test_risk_report_generation(self):
        """测试风控报告生成"""
        # 执行风控检查
        self.risk_controller.enforce_risk_limits(
            self.buy_decision,
            self.normal_portfolio
        )

        # 生成报告
        report = self.risk_controller.get_risk_report()

        # 验证报告包含关键信息
        assert "风险控制报告" in report
        assert "风险限制参数" in report
        assert "风控日志统计" in report


class TestMemory:
    """FinancialSituationMemory单元测试（待实现）"""

    def test_memory_initialization(self):
        """测试Memory初始化"""
        # 待实现：需要mock OpenAI和ChromaDB
        pass

    def test_memory_add_situations(self):
        """测试添加情境"""
        # 待实现：需要mock embedding API
        pass

    def test_memory_similarity_search(self):
        """测试相似性检索"""
        # 待实现：需要mock ChromaDB查询
        pass


class TestAgents:
    """Agent逻辑单元测试（待实现）"""

    def test_bull_researcher_argument_generation(self):
        """测试Bull研究员论点生成"""
        # 待实现：需要mock LLM
        pass

    def test_bear_researcher_argument_generation(self):
        """测试Bear研究员论点生成"""
        # 待实现：需要mock LLM
        pass

    def test_trader_decision_generation(self):
        """测试交易员决策生成"""
        # 待实现：需要mock LLM和Memory
        pass

    def test_risk_manager_final_decision(self):
        """测试风险管理最终决策"""
        # 待实现：需要mock LLM
        pass


class TestBacktestEngine:
    """BacktestEngine单元测试（待实现）"""

    def test_backtest_engine_initialization(self):
        """测试BacktestEngine初始化"""
        # 待实现：需要mock TradingAgentsGraph
        pass

    def test_performance_metrics_calculation(self):
        """测试性能指标计算"""
        # 待实现：需要mock portfolio snapshots
        pass

    def test_sharpe_ratio_calculation(self):
        """测试夏普比率计算"""
        # 待实现：需要mock returns数据
        pass

    def test_max_drawdown_calculation(self):
        """测试最大回撤计算"""
        # 待实现：需要mock capital曲线
        pass


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])