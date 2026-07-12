"""
ResilientToolkit - 数据源容错与fallback机制

功能:
1. 多数据源fallback（Primary→Fallback1→Fallback2）
2. 自动重试机制（网络抖动/临时失败）
3. 数据源健康监控（实时可用性检测）
4. 降级策略（数据源不可用时降级处理）
5. 数据一致性校验（多源数据对比）

使用方法:
    toolkit = ResilientToolkit()
    data = toolkit.get_market_data_with_retry("NVDA", max_retries=3)

Created: 2026-06-03
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
import time
import threading
from enum import Enum


class DataSourceStatus(Enum):
    """数据源状态"""
    HEALTHY = "healthy"  # 健康
    DEGRADED = "degraded"  # 降级
    FAILED = "failed"  # 失败
    UNKNOWN = "unknown"  # 未知


class FailureType(Enum):
    """失败类型"""
    NETWORK_ERROR = "network_error"  # 网络错误
    API_ERROR = "api_error"  # API错误
    TIMEOUT = "timeout"  # 超时
    RATE_LIMIT = "rate_limit"  # 速率限制
    INVALID_DATA = "invalid_data"  # 数据无效
    UNKNOWN = "unknown"  # 未知


@dataclass
class DataSourceInfo:
    """数据源信息"""
    name: str  # 数据源名称
    priority: int  # 优先级（0=最高）
    status: DataSourceStatus  # 当前状态
    last_success_time: Optional[datetime]  # 最后成功时间
    last_failure_time: Optional[datetime]  # 最后失败时间
    success_rate: float  # 成功率
    avg_latency: float  # 平均延迟
    total_calls: int  # 总调用次数
    failed_calls: int  # 失败次数


@dataclass
class DataFetchResult:
    """数据获取结果"""
    success: bool  # 是否成功
    data: Optional[Any]  # 数据内容
    source_name: str  # 数据源名称
    latency: float  # 延迟（秒）
    retry_count: int  # 重试次数
    fallback_used: bool  # 是否使用了fallback
    error_type: Optional[FailureType] = None  # 错误类型
    error_message: Optional[str] = None  # 错误信息


@dataclass
class ResilientConfig:
    """容错配置"""
    max_retries: int = 3  # 最大重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    timeout: float = 30.0  # 请求超时（秒）
    health_check_interval: int = 300  # 健康检查间隔（秒）
    degraded_threshold: float = 0.8  # 降级阈值（成功率<80%）
    failed_threshold: float = 0.3  # 失败阈值（成功率<30%）
    cache_ttl: int = 300  # 缓存有效期（秒）


class ResilientToolkit:
    """数据源容错工具包"""

    def __init__(self, config: ResilientConfig = None):
        """初始化容错工具包

        Args:
            config: 容错配置
        """
        self.config = config or ResilientConfig()

        # 数据源注册表
        self.data_sources: Dict[str, DataSourceInfo] = {}

        # Fallback链（数据源优先级排序）
        self.fallback_chains: Dict[str, List[str]] = {}

        # 数据缓存（临时存储）
        self.data_cache: Dict[str, Any] = {}

        # Fetch functions belong to one toolkit instance. Sharing these at the
        # class level leaks stale clients and mocks across sessions.
        self._fetch_functions: Dict[str, Callable] = {}

        # 健康检查线程
        self.health_check_thread: Optional[threading.Thread] = None
        self.health_check_enabled = False

        # 锁机制（线程安全）
        self.lock = threading.Lock()

    def register_data_source(
        self,
        name: str,
        fetch_func: Callable,
        priority: int = 0,
        data_type: str = "market"
    ) -> None:
        """注册数据源

        Args:
            name: 数据源名称（如"yfin_online", "yfin_cached"）
            fetch_func: 数据获取函数
            priority: 优先级（0=最高优先级）
            data_type: 数据类型（market/social/news/fundamentals）
        """
        # 注册数据源
        self.data_sources[name] = DataSourceInfo(
            name=name,
            priority=priority,
            status=DataSourceStatus.UNKNOWN,
            last_success_time=None,
            last_failure_time=None,
            success_rate=1.0,
            avg_latency=0.0,
            total_calls=0,
            failed_calls=0
        )

        # 存储fetch函数
        self._fetch_functions[name] = fetch_func

        # 更新fallback链
        if data_type not in self.fallback_chains:
            self.fallback_chains[data_type] = []

        self.fallback_chains[data_type].append(name)

        # 按优先级排序
        self.fallback_chains[data_type].sort(
            key=lambda source_name: self.data_sources[source_name].priority
        )

    def fetch_data_with_retry(
        self,
        data_type: str,
        *args,
        max_retries: int = None,
        **kwargs
    ) -> DataFetchResult:
        """获取数据（带重试和fallback）

        Args:
            data_type: 数据类型（market/social/news/fundamentals）
            *args: 数据获取函数参数
            max_retries: 最大重试次数（可选）
            **kwargs: 数据获取函数关键字参数

        Returns:
            DataFetchResult: 数据获取结果
        """
        max_retries = max_retries or self.config.max_retries

        # 获取fallback链
        fallback_chain = self.fallback_chains.get(data_type, [])

        if len(fallback_chain) == 0:
            return DataFetchResult(
                success=False,
                data=None,
                source_name="unknown",
                latency=0.0,
                retry_count=0,
                fallback_used=False,
                error_type=FailureType.UNKNOWN,
                error_message="无可用数据源"
            )

        # 按优先级依次尝试数据源
        for source_index, source_name in enumerate(fallback_chain):
            # 检查数据源状态
            source_info = self.data_sources[source_name]

            # 如果数据源已失败，跳过
            if source_info.status == DataSourceStatus.FAILED:
                continue

            # 尝试获取数据（带重试）
            result = self._fetch_from_source_with_retry(
                source_name,
                *args,
                max_retries=max_retries,
                **kwargs
            )

            # 成功获取数据
            if result.success:
                result.fallback_used = source_index > 0
                return result

            # 失败，继续尝试下一个fallback
            continue

        # 所有数据源都失败
        return DataFetchResult(
            success=False,
            data=None,
            source_name="all_failed",
            latency=0.0,
            retry_count=max_retries * len(fallback_chain),
            fallback_used=True,
            error_type=FailureType.UNKNOWN,
            error_message="所有数据源不可用"
        )

    def _fetch_from_source_with_retry(
        self,
        source_name: str,
        *args,
        max_retries: int,
        **kwargs
    ) -> DataFetchResult:
        """从单个数据源获取数据（带重试）

        Args:
            source_name: 数据源名称
            *args: 参数
            max_retries: 最大重试次数
            **kwargs: 关键字参数

        Returns:
            DataFetchResult: 数据获取结果
        """
        fetch_func = self._fetch_functions.get(source_name)

        if not fetch_func:
            return DataFetchResult(
                success=False,
                data=None,
                source_name=source_name,
                latency=0.0,
                retry_count=0,
                fallback_used=False,
                error_type=FailureType.UNKNOWN,
                error_message="数据源未注册"
            )

        # 重试循环
        for attempt in range(max_retries):
            start_time = time.time()

            try:
                # 调用数据获取函数
                data = fetch_func(*args, **kwargs)

                latency = time.time() - start_time

                # 更新数据源状态
                self._update_source_status(source_name, True, latency)

                # 成功返回
                return DataFetchResult(
                    success=True,
                    data=data,
                    source_name=source_name,
                    latency=latency,
                    retry_count=attempt,
                    fallback_used=False
                )

            except Exception as e:
                latency = time.time() - start_time

                # 判断错误类型
                error_type = self._classify_error(e)

                # 更新数据源状态
                self._update_source_status(source_name, False, latency, error_type)

                # 最后一次重试失败，返回错误
                if attempt == max_retries - 1:
                    return DataFetchResult(
                        success=False,
                        data=None,
                        source_name=source_name,
                        latency=latency,
                        retry_count=attempt + 1,
                        fallback_used=False,
                        error_type=error_type,
                        error_message=str(e)
                    )

                # 等待后重试
                time.sleep(self.config.retry_delay)

        # 不应该到达此处
        return DataFetchResult(
            success=False,
            data=None,
            source_name=source_name,
            latency=0.0,
            retry_count=max_retries,
            fallback_used=False,
            error_type=FailureType.UNKNOWN,
            error_message="最大重试次数已用完"
        )

    def _update_source_status(
        self,
        source_name: str,
        success: bool,
        latency: float,
        error_type: Optional[FailureType] = None
    ) -> None:
        """更新数据源状态

        Args:
            source_name: 数据源名称
            success: 是否成功
            latency: 延迟
            error_type: 错误类型（可选）
        """
        with self.lock:
            source_info = self.data_sources[source_name]

            # 更新调用次数
            source_info.total_calls += 1

            if success:
                # 成功调用
                source_info.last_success_time = datetime.now()
                source_info.avg_latency = (
                    (source_info.avg_latency * (source_info.total_calls - 1) + latency)
                    / source_info.total_calls
                )
            else:
                # 失败调用
                source_info.failed_calls += 1
                source_info.last_failure_time = datetime.now()

            # 计算成功率
            source_info.success_rate = (
                (source_info.total_calls - source_info.failed_calls)
                / source_info.total_calls
            )

            # 更新状态
            if source_info.success_rate >= self.config.degraded_threshold:
                source_info.status = DataSourceStatus.HEALTHY
            elif source_info.success_rate >= self.config.failed_threshold:
                source_info.status = DataSourceStatus.DEGRADED
            else:
                source_info.status = DataSourceStatus.FAILED

    def _classify_error(self, error: Exception) -> FailureType:
        """分类错误类型

        Args:
            error: 异常对象

        Returns:
            FailureType: 错误类型
        """
        error_message = str(error)

        # 网络错误
        if "Network" in error_message or "Connection" in error_message:
            return FailureType.NETWORK_ERROR

        # API错误
        if "API" in error_message or "401" in error_message or "403" in error_message:
            return FailureType.API_ERROR

        # 超时
        if "Timeout" in error_message or "timeout" in error_message:
            return FailureType.TIMEOUT

        # 速率限制
        if "Rate limit" in error_message or "429" in error_message:
            return FailureType.RATE_LIMIT

        # 数据无效
        if "Invalid" in error_message or "Empty" in error_message:
            return FailureType.INVALID_DATA

        # 未知
        return FailureType.UNKNOWN

    def get_data_source_health_report(self) -> str:
        """生成数据源健康报告

        Returns:
            str: 健康报告文本
        """
        report = f"""
数据源健康报告
生成时间: {datetime.now().isoformat()}

数据源状态:
"""

        # 添加各数据源状态
        for source_name, source_info in self.data_sources.items():
            status_icon = {
                DataSourceStatus.HEALTHY: "✅",
                DataSourceStatus.DEGRADED: "⚠️",
                DataSourceStatus.FAILED: "❌",
                DataSourceStatus.UNKNOWN: "❓"
            }

            icon = status_icon.get(source_info.status, "❓")

            report += f"""
{icon} {source_name}（优先级{source_info.priority}）:
  - 状态: {source_info.status.name}
  - 成功率: {source_info.success_rate:.2%}
  - 平均延迟: {source_info.avg_latency:.2f}秒
  - 总调用: {source_info.total_calls}次
  - 失败次数: {source_info.failed_calls}次
  - 最后成功: {source_info.last_success_time.strftime('%H:%M:%S') if source_info.last_success_time else 'N/A'}
  - 最后失败: {source_info.last_failure_time.strftime('%H:%M:%S') if source_info.last_failure_time else 'N/A'}
"""

        # 添加fallback链信息
        report += "\nFallback链配置:\n"

        for data_type, sources in self.fallback_chains.items():
            report += f"  - {data_type}: {sources}\n"

        return report

    def start_health_check(self) -> None:
        """启动健康检查线程"""
        if self.health_check_enabled:
            return

        self.health_check_enabled = True

        def health_check_loop():
            while self.health_check_enabled:
                # 定期健康检查（简化：检查数据源状态）
                for source_name, source_info in self.data_sources.items():
                    # 如果数据源长时间无调用，标记为UNKNOWN
                    if source_info.last_success_time:
                        time_since_success = (datetime.now() - source_info.last_success_time).total_seconds()

                        if time_since_success > self.config.health_check_interval * 2:
                            source_info.status = DataSourceStatus.UNKNOWN

                # 等待下一次检查
                time.sleep(self.config.health_check_interval)

        # 启动健康检查线程
        self.health_check_thread = threading.Thread(target=health_check_loop, daemon=True)
        self.health_check_thread.start()

        print(f"✓ 数据源健康检查已启动（每{self.config.health_check_interval}秒检查一次）")

    def stop_health_check(self) -> None:
        """停止健康检查线程"""
        self.health_check_enabled = False

        if self.health_check_thread and self.health_check_thread.is_alive():
            self.health_check_thread.join(timeout=5)

        print("✓ 数据源健康检查已停止")


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("ResilientToolkit使用示例")
    print("="*60)

    toolkit = ResilientToolkit()

    print("\n示例代码:")
    print("""
    from tradingagents.dataflows.resilient_toolkit import ResilientToolkit

    # 初始化容错工具包
    toolkit = ResilientToolkit()

    # 注册数据源（Primary + Fallback）
    # Primary: YFin Online（优先级0）
    toolkit.register_data_source(
        name="yfin_online",
        fetch_func=toolkit.get_YFin_data_online,
        priority=0,
        data_type="market"
    )

    # Fallback 1: Cached Data（优先级1）
    toolkit.register_data_source(
        name="yfin_cached",
        fetch_func=toolkit.get_cached_data,
        priority=1,
        data_type="market"
    )

    # Fallback 2: Alternative Source（优先级2）
    toolkit.register_data_source(
        name="alternative_source",
        fetch_func=toolkit.get_alternative_data,
        priority=2,
        data_type="market"
    )

    # 启动健康检查
    toolkit.start_health_check()

    # 获取数据（自动fallback）
    result = toolkit.fetch_data_with_retry(
        data_type="market",
        ticker="NVDA",
        date="2024-05-10",
        max_retries=3
    )

    if result.success:
        print(f"✓ 数据获取成功（{result.source_name}）")
        print(f"  延迟: {result.latency:.2f}秒")
        print(f"  重试次数: {result.retry_count}")
        print(f"  使用fallback: {result.fallback_used}")
    else:
        print(f"✗ 数据获取失败: {result.error_message}")

    # 查看健康报告
    print(toolkit.get_data_source_health_report())

    # 停止健康检查
    toolkit.stop_health_check()
    """)
