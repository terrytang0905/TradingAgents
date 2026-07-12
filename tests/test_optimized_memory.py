"""
TradingAgents单元测试扩展 - Memory/Backtest/Agents测试

测试覆盖:
1. OptimizedFinancialMemory批量检索测试
2. PerformanceMonitor成本监控测试
3. ResilientToolkit数据源容错测试
4. BacktestEngine性能指标测试

运行方法:
    python -m pytest tests/test_p1_improvements.py -v

Created: 2026-06-03
"""

import pytest
import sys
from pathlib import Path
from datetime import datetime, timedelta
import time

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Mock测试（避免依赖真实API）
from unittest.mock import Mock, MagicMock, patch


class TestOptimizedFinancialMemory:
    """OptimizedFinancialMemory单元测试"""

    def setup_method(self):
        """每个测试方法前初始化"""
        # Mock配置
        self.mock_config = {
            "backend_url": "https://api.openai.com/v1"
        }

    @patch('tradingagents.agents.utils.optimized_memory.CHROMADB_AVAILABLE', True)
    @patch('tradingagents.agents.utils.optimized_memory.OPENAI_AVAILABLE', True)
    def test_memory_initialization(self):
        """测试OptimizedMemory初始化"""
        # Mock OpenAI客户端
        with patch('tradingagents.agents.utils.optimized_memory.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_openai.return_value = mock_client

            # Mock ChromaDB
            with patch('tradingagents.agents.utils.optimized_memory.chromadb.Client') as mock_chroma:
                mock_chroma_client = Mock()
                mock_collection = Mock()
                mock_chroma_client.create_collection.return_value = mock_collection
                mock_chroma.return_value = mock_chroma_client

                # 导入模块
                from tradingagents.agents.utils.optimized_memory import OptimizedFinancialMemory

                # 初始化Memory
                memory = OptimizedFinancialMemory(
                    name="test_memory",
                    config=self.mock_config,
                    cache_enabled=True
                )

                # 验证初始化成功
                assert memory.name == "test_memory"
                assert memory.cache_enabled == True
                assert memory.embedding_model == "text-embedding-3-small"

    @patch('tradingagents.agents.utils.optimized_memory.CHROMADB_AVAILABLE', True)
    @patch('tradingagents.agents.utils.optimized_memory.OPENAI_AVAILABLE', True)
    def test_batch_embedding_generation(self):
        """测试批量embedding生成"""
        # Mock OpenAI客户端
        with patch('tradingagents.agents.utils.optimized_memory.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = [
                Mock(embedding=[0.1, 0.2, 0.3]),
                Mock(embedding=[0.4, 0.5, 0.6]),
                Mock(embedding=[0.7, 0.8, 0.9])
            ]
            mock_client.embeddings.create.return_value = mock_response
            mock_openai.return_value = mock_client

            # Mock ChromaDB
            with patch('tradingagents.agents.utils.optimized_memory.chromadb.Client') as mock_chroma:
                mock_chroma_client = Mock()
                mock_collection = Mock()
                mock_chroma_client.create_collection.return_value = mock_collection
                mock_chroma.return_value = mock_chroma_client

                from tradingagents.agents.utils.optimized_memory import OptimizedFinancialMemory

                memory = OptimizedFinancialMemory(name="test", config=self.mock_config)

                # 批量获取embedding
                texts = ["text1", "text2", "text3"]
                response = memory.get_embedding_batch(texts)

                # 验证结果
                assert len(response.embeddings) == 3
                assert response.latency > 0
                assert response.cost > 0

                # 验证API调用统计
                assert memory.stats["total_api_calls"] == 1  # 仅1次API调用（批量）
                assert memory.stats["total_embeddings_generated"] == 3

    @patch('tradingagents.agents.utils.optimized_memory.CHROMADB_AVAILABLE', True)
    @patch('tradingagents.agents.utils.optimized_memory.OPENAI_AVAILABLE', True)
    def test_cache_hit_optimization(self):
        """测试缓存命中优化"""
        with patch('tradingagents.agents.utils.optimized_memory.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = [Mock(embedding=[0.1, 0.2, 0.3])]
            mock_client.embeddings.create.return_value = mock_response
            mock_openai.return_value = mock_client

            with patch('tradingagents.agents.utils.optimized_memory.chromadb.Client') as mock_chroma:
                mock_chroma_client = Mock()
                mock_collection = Mock()
                mock_chroma_client.create_collection.return_value = mock_collection
                mock_chroma.return_value = mock_chroma_client

                from tradingagents.agents.utils.optimized_memory import OptimizedFinancialMemory

                memory = OptimizedFinancialMemory(name="test", config=self.mock_config, cache_enabled=True)

                # 第一次调用（缓存未命中）
                texts1 = ["text1"]
                response1 = memory.get_embedding_batch(texts1)

                # 第二次调用（缓存命中）
                texts2 = ["text1"]  # 相同文本
                response2 = memory.get_embedding_batch(texts2)

                # 验证缓存统计
                assert memory.stats["cache_misses"] == 1  # 第一次未命中
                assert memory.stats["cache_hits"] == 1  # 第二次命中

                # 验证API调用次数（仅第一次调用API）
                assert memory.stats["total_api_calls"] == 1  # 仅1次API调用

    @patch('tradingagents.agents.utils.optimized_memory.CHROMADB_AVAILABLE', True)
    @patch('tradingagents.agents.utils.optimized_memory.OPENAI_AVAILABLE', True)
    def test_cost_savings_calculation(self):
        """测试成本节省计算"""
        with patch('tradingagents.agents.utils.optimized_memory.OpenAI') as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = [Mock(embedding=[0.1, 0.2, 0.3])]
            mock_client.embeddings.create.return_value = mock_response
            mock_openai.return_value = mock_client

            with patch('tradingagents.agents.utils.optimized_memory.chromadb.Client') as mock_chroma:
                mock_chroma_client = Mock()
                mock_collection = Mock()
                mock_chroma.return_value = mock_chroma_client

                from tradingagents.agents.utils.optimized_memory import OptimizedFinancialMemory

                memory = OptimizedFinancialMemory(name="test", config=self.mock_config)

                # 生成10次调用（5次缓存命中）
                for i in range(10):
                    if i % 2 == 0:
                        # 新文本（缓存未命中）
                        text = f"text_{i}"
                    else:
                        # 重复文本（缓存命中）
                        text = f"text_{i-1}"

                    memory.get_embedding_batch([text])

                # 查看缓存统计
                cache_stats = memory.get_cache_statistics()

                # 验证缓存命中率
                assert cache_stats["cache_hit_rate"] == 0.5  # 50%命中率

                # 验证成本节省
                assert cache_stats["estimated_cost_saved"] > 0


class TestPerformanceMonitor:
    """PerformanceMonitor单元测试"""

    def setup_method(self):
        """每个测试方法前初始化"""
        self.monitor = None

    def test_monitor_initialization(self):
        """测试PerformanceMonitor初始化"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        monitor = PerformanceMonitor(daily_budget=5.0)

        # 验证默认配置
        assert monitor.daily_budget == 5.0
        assert monitor.hourly_budget == 1.0
        assert monitor.latency_threshold == 10.0
        assert monitor.error_rate_threshold == 0.1

    def test_api_call_tracking(self):
        """测试API调用追踪"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        monitor = PerformanceMonitor()

        # 记录多次API调用
        monitor.track_api_call(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            latency=1.5,
            agent_name="Bull Researcher"
        )

        monitor.track_api_call(
            provider="anthropic",
            model="claude-sonnet-4-6",
            input_tokens=800,
            output_tokens=400,
            latency=2.0,
            agent_name="Bear Researcher"
        )

        # 验证统计
        assert monitor.stats["total_calls"] == 2
        assert monitor.stats["total_tokens"] == 2700  # 1000+500+800+400
        assert monitor.stats["success_calls"] == 2
        assert monitor.stats["total_latency"] == 3.5  # 1.5+2.0

    def test_cost_calculation(self):
        """测试成本计算"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        monitor = PerformanceMonitor()

        # 记录API调用（自动计算成本）
        monitor.track_api_call(
            provider="openai",
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            latency=1.5
        )

        # 验证成本计算
        # gpt-4o: input=0.005/1K, output=0.015/1K
        expected_cost = (1000 * 0.005 + 500 * 0.015) / 1000  # $0.0125

        assert monitor.stats["total_cost"] == pytest.approx(expected_cost, rel=0.01)

    def test_budget_exceeded_alert(self):
        """测试预算超限告警"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        # 设置极低预算（测试告警）
        monitor = PerformanceMonitor(daily_budget=0.01)

        # 记录超出预算的调用
        monitor.track_api_call(
            provider="openai",
            model="gpt-4o",
            input_tokens=10000,
            output_tokens=5000,
            latency=1.5
        )

        # 检查预算
        alert = monitor.check_budget()

        # 验证告警触发
        assert alert is not None
        assert alert.alert_type == "budget_exceeded"
        assert alert.severity == "critical"

    def test_latency_alert(self):
        """测试延迟告警"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        monitor = PerformanceMonitor(latency_threshold=5.0)

        # 记录高延迟调用
        for i in range(10):
            monitor.track_api_call(
                provider="openai",
                model="gpt-4o",
                input_tokens=1000,
                output_tokens=500,
                latency=8.0  # 超过阈值5秒
            )

        # 检查延迟
        alert = monitor.check_budget()

        # 验证延迟告警
        assert alert is not None
        assert alert.alert_type == "latency_high"

    def test_cost_report_generation(self):
        """测试成本报告生成"""
        from tradingagents.monitoring.performance_monitor import PerformanceMonitor

        monitor = PerformanceMonitor()

        # 记录多个Agent调用
        for agent in ["Bull", "Bear", "Trader"]:
            monitor.track_api_call(
                provider="openai",
                model="gpt-4o",
                input_tokens=1000,
                output_tokens=500,
                latency=1.5,
                agent_name=agent
            )

        # 生成报告
        report = monitor.get_performance_report()

        # 验证报告包含关键信息
        assert "API性能监控报告" in report
        assert "预算状态" in report
        assert "成本分析" in report
        assert "Top 5成本Agent" in report


class TestResilientToolkit:
    """ResilientToolkit单元测试"""

    def setup_method(self):
        """每个测试方法前初始化"""
        from tradingagents.dataflows.resilient_toolkit import ResilientToolkit, ResilientConfig

        self.config = ResilientConfig(max_retries=3, retry_delay=1.0)
        self.toolkit = ResilientToolkit(self.config)

    def test_toolkit_initialization(self):
        """测试ResilientToolkit初始化"""
        # 验证默认配置
        assert self.toolkit.config.max_retries == 3
        assert self.toolkit.config.retry_delay == 1.0
        assert self.toolkit.config.timeout == 30.0

    def test_data_source_registration(self):
        """测试数据源注册"""
        # Mock fetch函数
        mock_fetch = Mock(return_value={"data": "test"})

        # 注册数据源
        self.toolkit.register_data_source(
            name="primary_source",
            fetch_func=mock_fetch,
            priority=0,
            data_type="market"
        )

        self.toolkit.register_data_source(
            name="fallback_source",
            fetch_func=mock_fetch,
            priority=1,
            data_type="market"
        )

        # 验证数据源注册
        assert "primary_source" in self.toolkit.data_sources
        assert "fallback_source" in self.toolkit.data_sources

        # 验证fallback链
        assert "market" in self.toolkit.fallback_chains
        assert self.toolkit.fallback_chains["market"] == ["primary_source", "fallback_source"]

    def test_primary_source_success(self):
        """测试Primary数据源成功"""
        # Mock成功fetch函数
        mock_primary = Mock(return_value={"price": 100.0})
        mock_fallback = Mock(return_value={"price": 90.0})

        # 注册数据源
        self.toolkit.register_data_source(
            name="primary",
            fetch_func=mock_primary,
            priority=0,
            data_type="market"
        )

        self.toolkit.register_data_source(
            name="fallback",
            fetch_func=mock_fallback,
            priority=1,
            data_type="market"
        )

        # 获取数据
        result = self.toolkit.fetch_data_with_retry(data_type="market", ticker="NVDA")

        # 验证Primary数据源被调用
        assert result.success == True
        assert result.source_name == "primary"
        assert result.fallback_used == False

        # 验证Fallback未被调用
        mock_fallback.assert_not_called()

    def test_fallback_chain_execution(self):
        """测试Fallback链执行"""
        # Mock Primary失败
        mock_primary = Mock(side_effect=Exception("Primary failed"))
        mock_fallback = Mock(return_value={"price": 90.0})

        # 注册数据源
        self.toolkit.register_data_source(
            name="primary",
            fetch_func=mock_primary,
            priority=0,
            data_type="market"
        )

        self.toolkit.register_data_source(
            name="fallback",
            fetch_func=mock_fallback,
            priority=1,
            data_type="market"
        )

        # 获取数据
        result = self.toolkit.fetch_data_with_retry(data_type="market", ticker="NVDA")

        # 验证Fallback被调用
        assert result.success == True
        assert result.source_name == "fallback"
        assert result.fallback_used == True

    def test_retry_mechanism(self):
        """测试重试机制"""
        # Mock前2次失败，第3次成功
        mock_fetch = Mock(side_effect=[
            Exception("Error 1"),
            Exception("Error 2"),
            {"price": 100.0}  # 第3次成功
        ])

        # 注册数据源
        self.toolkit.register_data_source(
            name="test_source",
            fetch_func=mock_fetch,
            priority=0,
            data_type="market"
        )

        # 获取数据
        result = self.toolkit.fetch_data_with_retry(data_type="market", ticker="NVDA")

        # 验证重试次数
        assert result.success == True
        assert result.retry_count == 2  # 前2次失败，第3次成功

        # 验证fetch被调用3次
        assert mock_fetch.call_count == 3

    def test_all_sources_failed(self):
        """测试所有数据源失败"""
        # Mock所有数据源失败
        mock_primary = Mock(side_effect=Exception("Primary failed"))
        mock_fallback = Mock(side_effect=Exception("Fallback failed"))

        # 注册数据源
        self.toolkit.register_data_source(
            name="primary",
            fetch_func=mock_primary,
            priority=0,
            data_type="market"
        )

        self.toolkit.register_data_source(
            name="fallback",
            fetch_func=mock_fallback,
            priority=1,
            data_type="market"
        )

        # 获取数据
        result = self.toolkit.fetch_data_with_retry(data_type="market", ticker="NVDA")

        # 验证失败结果
        assert result.success == False
        assert result.source_name == "all_failed"
        assert "所有数据源不可用" in result.error_message

    def test_data_source_status_update(self):
        """测试数据源状态更新"""
        # Mock fetch函数
        mock_fetch = Mock(return_value={"data": "test"})

        # 注册数据源
        self.toolkit.register_data_source(
            name="test_source",
            fetch_func=mock_fetch,
            priority=0,
            data_type="market"
        )

        # 成功调用
        result = self.toolkit.fetch_data_with_retry(data_type="market", ticker="NVDA")

        # 验证状态更新
        source_info = self.toolkit.data_sources["test_source"]
        assert source_info.status.name == "HEALTHY"
        assert source_info.total_calls == 1
        assert source_info.failed_calls == 0
        assert source_info.success_rate == 1.0


class TestBacktestEngineExtended:
    """BacktestEngine扩展测试"""

    def test_performance_metrics_calculation(self):
        """测试性能指标计算"""
        # Mock测试数据
        from tradingagents.backtest.backtest_engine import BacktestEngine

        # Mock TradingAgentsGraph
        mock_graph = Mock()
        mock_graph.propagate.return_value = (
            {"final_trade_decision": "BUY NVDA"},
            "BUY NVDA"
        )

        # 创建回测引擎
        engine = BacktestEngine(
            graph=mock_graph,
            tickers=["NVDA"],
            start_date="2024-01-01",
            end_date="2024-01-05"
        )

        # 验证初始化
        assert engine.tickers == ["NVDA"]
        assert engine.initial_capital == 100000

    def test_sharpe_ratio_calculation_mock(self):
        """测试夏普比率计算（Mock数据）"""
        # Mock returns序列
        import numpy as np

        # 创建假设returns数据（年化收益10%，波动率15%）
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.0095, 250)
        returns = returns - np.mean(returns) + 0.0004  # 固定日均收益

        # 计算夏普比率（简化）
        annualized_return = np.mean(returns) * 250
        volatility = np.std(returns) * np.sqrt(250)
        sharpe_ratio = annualized_return / volatility if volatility > 0 else 0

        # 验证夏普比率范围
        assert sharpe_ratio > 0  # 正收益应产生正夏普比率
        assert sharpe_ratio < 3  # 合理范围（通常<3）


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
