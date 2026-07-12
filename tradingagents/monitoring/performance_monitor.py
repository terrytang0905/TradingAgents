"""
PerformanceMonitor - API性能监控与成本追踪系统

功能:
1. 实时API调用计数（每10分钟汇总）
2. 成本监控（超预算预警$5/天）
3. 响应延迟监控（识别性能瓶颈）
4. Agent性能分析（对比各Agent效率）
5. 桌面通知（超预算/异常告警）

使用方法:
    monitor = PerformanceMonitor(daily_budget=5.0)
    monitor.track_api_call("openai", "gpt-4o", 1000, 2000, 0.05, 1.5)
    monitor.check_budget()

Created: 2026-06-03
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path
import json
import subprocess
import threading
import time


@dataclass
class APICallRecord:
    """API调用记录"""
    timestamp: datetime
    provider: str  # openai/anthropic/google
    model: str  # gpt-4o/claude-sonnet-4-6/gemini-2.0-flash
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_seconds: float
    agent_name: Optional[str] = None  # Agent名称（可选）
    task_type: Optional[str] = None  # 任务类型（可选）
    success: bool = True  # 是否成功
    error_message: Optional[str] = None  # 错误信息


@dataclass
class CostSummary:
    """成本汇总"""
    period: str  # hourly/daily/weekly
    start_time: datetime
    end_time: datetime
    total_calls: int
    total_cost: float
    total_tokens: int
    avg_latency: float
    success_rate: float
    top_models: List[Dict[str, Any]]  # 成本Top 5模型
    top_agents: List[Dict[str, Any]]  # 成本Top 5 Agent


@dataclass
class PerformanceAlert:
    """性能告警"""
    alert_type: str  # budget_exceeded/latency_high/error_rate_high
    severity: str  # critical/warning/info
    message: str
    current_value: float
    threshold_value: float
    timestamp: datetime
    details: Dict[str, Any] = field(default_factory=dict)


class PerformanceMonitor:
    """API性能监控与成本追踪系统"""

    # 模型定价（2026年6月）
    MODEL_PRICING = {
        # OpenAI
        "gpt-4o": {"input": 0.005, "output": 0.015},
        "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
        "o1-preview": {"input": 0.015, "output": 0.06},
        "o4-mini": {"input": 0.001, "output": 0.004},
        "text-embedding-3-small": {"input": 0.00002, "output": 0},

        # Anthropic
        "claude-opus-4-6": {"input": 0.015, "output": 0.075},
        "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        "claude-haiku-4-5": {"input": 0.001, "output": 0.005},

        # Google
        "gemini-2.0-flash": {"input": 0.000075, "output": 0.0003},
        "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},

        # Ollama（本地免费）
        "nomic-embed-text": {"input": 0, "output": 0},
        "llama3": {"input": 0, "output": 0},
    }

    def __init__(
        self,
        daily_budget: float = 5.0,  # 每日预算$5
        hourly_budget: float = 1.0,  # 每小时预算$1
        latency_threshold: float = 10.0,  # 延迟阈值10秒
        error_rate_threshold: float = 0.1,  # 错误率阈值10%
        config: Dict[str, Any] = None
    ):
        """初始化性能监控

        Args:
            daily_budget: 每日预算（USD）
            hourly_budget: 每小时预算（USD）
            latency_threshold: 延迟阈值（秒）
            error_rate_threshold: 错误率阈值
            config: 配置字典
        """
        self.daily_budget = daily_budget
        self.hourly_budget = hourly_budget
        self.latency_threshold = latency_threshold
        self.error_rate_threshold = error_rate_threshold
        self.config = config or {}

        # API调用记录
        self.call_records: List[APICallRecord] = []

        # 成本汇总缓存
        self.cost_summaries: Dict[str, CostSummary] = {}

        # 告警历史
        self.alerts: List[PerformanceAlert] = []

        # 统计汇总（实时更新）
        self.stats = {
            "total_calls": 0,
            "total_cost": 0.0,
            "total_tokens": 0,
            "total_latency": 0.0,
            "success_calls": 0,
            "failed_calls": 0,
            "models_used": {},
            "agents_used": {}
        }

        # 监控线程（定期检查）
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitoring_enabled = False

        # 锁机制（线程安全）
        self.lock = threading.Lock()

    def track_api_call(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost: Optional[float] = None,
        latency: float = 0.0,
        agent_name: Optional[str] = None,
        task_type: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> None:
        """记录API调用

        Args:
            provider: 提供商（openai/anthropic/google）
            model: 模型名称
            input_tokens: 输入tokens数量
            output_tokens: 输出tokens数量
            cost: 实际成本（可选，如未提供则自动计算）
            latency: 响应延迟（秒）
            agent_name: Agent名称（可选）
            task_type: 任务类型（可选）
            success: 是否成功
            error_message: 错误信息（可选）
        """
        # 计算成本（如未提供）
        if cost is None:
            pricing = self.MODEL_PRICING.get(model, {"input": 0.003, "output": 0.015})
            cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000

        # 创建记录
        record = APICallRecord(
            timestamp=datetime.now(),
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_seconds=latency,
            agent_name=agent_name,
            task_type=task_type,
            success=success,
            error_message=error_message
        )

        # 更新统计
        with self.lock:
            self.call_records.append(record)

            self.stats["total_calls"] += 1
            self.stats["total_cost"] += cost
            self.stats["total_tokens"] += input_tokens + output_tokens
            self.stats["total_latency"] += latency

            if success:
                self.stats["success_calls"] += 1
            else:
                self.stats["failed_calls"] += 1

            # 模型统计
            if model not in self.stats["models_used"]:
                self.stats["models_used"][model] = {"calls": 0, "cost": 0.0, "tokens": 0}
            self.stats["models_used"][model]["calls"] += 1
            self.stats["models_used"][model]["cost"] += cost
            self.stats["models_used"][model]["tokens"] += input_tokens + output_tokens

            # Agent统计
            if agent_name:
                if agent_name not in self.stats["agents_used"]:
                    self.stats["agents_used"][agent_name] = {"calls": 0, "cost": 0.0}
                self.stats["agents_used"][agent_name]["calls"] += 1
                self.stats["agents_used"][agent_name]["cost"] += cost

    def check_budget(self) -> Optional[PerformanceAlert]:
        """检查预算状态

        Returns:
            Optional[PerformanceAlert]: 告警（如超预算）
        """
        # 计算当日成本
        today = datetime.now().date()
        today_cost = sum(
            record.cost_usd for record in self.call_records
            if record.timestamp.date() == today
        )

        # 计算当前小时成本
        current_hour = datetime.now().replace(minute=0, second=0, microsecond=0)
        hourly_cost = sum(
            record.cost_usd for record in self.call_records
            if record.timestamp.replace(minute=0, second=0, microsecond=0) == current_hour
        )

        # 检查每日预算
        if today_cost > self.daily_budget:
            alert = PerformanceAlert(
                alert_type="budget_exceeded",
                severity="critical",
                message=f"每日预算超限: $%.2f > $%.2f" % (today_cost, self.daily_budget),
                current_value=today_cost,
                threshold_value=self.daily_budget,
                timestamp=datetime.now(),
                details={"hourly_cost": hourly_cost}
            )

            with self.lock:
                self.alerts.append(alert)

            # 发送桌面通知
            self._send_notification(alert)

            return alert

        # 检查每小时预算
        if hourly_cost > self.hourly_budget:
            alert = PerformanceAlert(
                alert_type="budget_exceeded",
                severity="warning",
                message=f"每小时预算超限: $%.2f > $%.2f" % (hourly_cost, self.hourly_budget),
                current_value=hourly_cost,
                threshold_value=self.hourly_budget,
                timestamp=datetime.now(),
                details={"daily_cost": today_cost}
            )

            with self.lock:
                self.alerts.append(alert)

            self._send_notification(alert)

            return alert

        # 检查延迟（最近10次调用平均延迟）
        recent_calls = self.call_records[-10:]
        if len(recent_calls) > 0:
            avg_latency = sum(call.latency_seconds for call in recent_calls) / len(recent_calls)

            if avg_latency > self.latency_threshold:
                alert = PerformanceAlert(
                    alert_type="latency_high",
                    severity="warning",
                    message=f"平均延迟过高: %.2f秒 > %.2f秒" % (avg_latency, self.latency_threshold),
                    current_value=avg_latency,
                    threshold_value=self.latency_threshold,
                    timestamp=datetime.now()
                )

                with self.lock:
                    self.alerts.append(alert)

                self._send_notification(alert)

                return alert

        # 检查错误率（最近10次调用）
        if len(recent_calls) > 0:
            error_rate = sum(1 for call in recent_calls if not call.success) / len(recent_calls)

            if error_rate > self.error_rate_threshold:
                alert = PerformanceAlert(
                    alert_type="error_rate_high",
                    severity="warning",
                    message=f"错误率过高: %.2f > %.2f" % (error_rate, self.error_rate_threshold),
                    current_value=error_rate,
                    threshold_value=self.error_rate_threshold,
                    timestamp=datetime.now()
                )

                with self.lock:
                    self.alerts.append(alert)

                self._send_notification(alert)

                return alert

        return None

    def generate_cost_report(self, period: str = "daily") -> CostSummary:
        """生成成本报告

        Args:
            period: 时间周期（hourly/daily/weekly）

        Returns:
            CostSummary: 成本汇总
        """
        now = datetime.now()

        # 确定时间范围
        if period == "hourly":
            start_time = now.replace(minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=1)

        elif period == "daily":
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(days=1)

        elif period == "weekly":
            start_time = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
            end_time = start_time + timedelta(days=7)

        else:
            raise ValueError(f"不支持的period: {period}")

        # 筛选记录
        period_records = [
            record for record in self.call_records
            if start_time <= record.timestamp < end_time
        ]

        # 计算汇总
        total_calls = len(period_records)
        total_cost = sum(record.cost_usd for record in period_records)
        total_tokens = sum(record.input_tokens + record.output_tokens for record in period_records)

        avg_latency = (
            sum(record.latency_seconds for record in period_records) / total_calls
            if total_calls > 0 else 0
        )

        success_rate = (
            sum(1 for record in period_records if record.success) / total_calls
            if total_calls > 0 else 0
        )

        # Top 5模型成本
        model_costs = {}
        for record in period_records:
            if record.model not in model_costs:
                model_costs[record.model] = 0.0
            model_costs[record.model] += record.cost_usd

        top_models = sorted(
            [{"model": model, "cost": cost} for model, cost in model_costs.items()],
            key=lambda x: x["cost"],
            reverse=True
        )[:5]

        # Top 5 Agent成本
        agent_costs = {}
        for record in period_records:
            if record.agent_name:
                if record.agent_name not in agent_costs:
                    agent_costs[record.agent_name] = 0.0
                agent_costs[record.agent_name] += record.cost_usd

        top_agents = sorted(
            [{"agent": agent, "cost": cost} for agent, cost in agent_costs.items()],
            key=lambda x: x["cost"],
            reverse=True
        )[:5]

        return CostSummary(
            period=period,
            start_time=start_time,
            end_time=end_time,
            total_calls=total_calls,
            total_cost=total_cost,
            total_tokens=total_tokens,
            avg_latency=avg_latency,
            success_rate=success_rate,
            top_models=top_models,
            top_agents=top_agents
        )

    def get_performance_report(self) -> str:
        """生成性能报告

        Returns:
            str: 性能报告文本
        """
        daily_summary = self.generate_cost_report("daily")

        report = f"""
API性能监控报告
生成时间: {datetime.now().isoformat()}

预算状态:
- 每日预算: $%.2f" % self.daily_budget
- 今日成本: $%.2f" % daily_summary.total_cost
- 预算状态: {"✅ 正常" if daily_summary.total_cost <= self.daily_budget else "⚠️ 超预算"}
- 预算使用率: {(daily_summary.total_cost / self.daily_budget * 100):.1f}%

API调用统计（今日）:
- 总调用次数: {daily_summary.total_calls}
- 总tokens: {daily_summary.total_tokens:,}
- 成功次数: {int(daily_summary.total_calls * daily_summary.success_rate)}
- 失败次数: {int(daily_summary.total_calls * (1 - daily_summary.success_rate))}
- 成功率: {daily_summary.success_rate:.2%}
- 平均延迟: {daily_summary.avg_latency:.2f}秒

成本分析（今日）:
- 总成本: $%.2f" % daily_summary.total_cost
- 平均单次成本: $%.4f" % (daily_summary.total_cost / max(1, daily_summary.total_calls))
- 平均每1K tokens成本: $%.4f" % (daily_summary.total_cost / max(1, daily_summary.total_tokens / 1000))

Top 5成本模型:
"""
        # 添加Top 5模型
        for model_info in daily_summary.top_models:
            report += f"  - {model_info['model']}: $%.4f (%.1f%%)\n" % (
                model_info['cost'],
                model_info['cost'] / daily_summary.total_cost * 100 if daily_summary.total_cost > 0 else 0
            )

        report += "\nTop 5成本Agent:\n"

        # 添加Top 5 Agent
        for agent_info in daily_summary.top_agents:
            report += f"  - {agent_info['agent']}: $%.4f (%.1f%%)\n" % (
                agent_info['cost'],
                agent_info['cost'] / daily_summary.total_cost * 100 if daily_summary.total_cost > 0 else 0
            )

        report += "\n最近告警:\n"

        # 添加最近5次告警
        for alert in self.alerts[-5:]:
            report += f"  - [{alert.severity}] {alert.message} ({alert.timestamp.strftime('%H:%M:%S')})\n"

        return report

    def save_cost_log(self, filepath: str) -> None:
        """保存成本日志到JSON文件

        Args:
            filepath: 文件路径
        """
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "call_records": [
                {
                    "timestamp": record.timestamp.isoformat(),
                    "provider": record.provider,
                    "model": record.model,
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "cost_usd": record.cost_usd,
                    "latency_seconds": record.latency_seconds,
                    "agent_name": record.agent_name,
                    "success": record.success
                }
                for record in self.call_records
            ],
            "stats": self.stats,
            "alerts": [
                {
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "message": alert.message,
                    "timestamp": alert.timestamp.isoformat()
                }
                for alert in self.alerts
            ]
        }

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, indent=2)

    def start_monitoring(self, interval: int = 600) -> None:
        """启动监控线程（定期检查预算）

        Args:
            interval: 检查间隔（秒，默认600秒=10分钟）
        """
        if self.monitoring_enabled:
            return

        self.monitoring_enabled = True

        def monitor_loop():
            while self.monitoring_enabled:
                # 检查预算
                self.check_budget()

                # 等待下一次检查
                time.sleep(interval)

        # 启动监控线程
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()

        print(f"✓ 性能监控已启动（每{interval}秒检查一次）")

    def stop_monitoring(self) -> None:
        """停止监控线程"""
        self.monitoring_enabled = False

        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)

        print("✓ 性能监控已停止")

    def _send_notification(self, alert: PerformanceAlert) -> None:
        """发送桌面通知

        Args:
            alert: 告警信息
        """
        try:
            # macOS桌面通知
            subprocess.run([
                'osascript', '-e',
                f'display notification "{alert.message}" with title "⚠️ TradingAgents性能告警" sound name "Glass"'
            ], check=True)

        except subprocess.CalledProcessError as e:
            print(f"通知发送失败: {str(e)}")


if __name__ == "__main__":
    # 使用示例
    print("="*60)
    print("PerformanceMonitor使用示例")
    print("="*60)

    monitor = PerformanceMonitor(daily_budget=5.0)

    print("\n示例代码:")
    print("""
    from tradingagents.monitoring.performance_monitor import PerformanceMonitor

    # 初始化监控（每日预算$5）
    monitor = PerformanceMonitor(daily_budget=5.0)

    # 启动自动监控（每10分钟检查预算）
    monitor.start_monitoring(interval=600)

    # 记录API调用
    monitor.track_api_call(
        provider="openai",
        model="gpt-4o",
        input_tokens=1000,
        output_tokens=500,
        cost=0.015,  # 或自动计算
        latency=1.5,
        agent_name="Bull Researcher",
        task_type="argument_generation"
    )

    # 手动检查预算
    alert = monitor.check_budget()
    if alert:
        print(f"⚠️ {alert.message}")

    # 查看性能报告
    print(monitor.get_performance_report())

    # 保存日志
    monitor.save_cost_log("performance_log.json")

    # 停止监控
    monitor.stop_monitoring()
    """)