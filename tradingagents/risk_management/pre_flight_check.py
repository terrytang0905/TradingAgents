"""Fail-closed pre-flight risk checks for TradingAgents."""

import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from tradingagents.default_config import DEFAULT_CONFIG

from .risk_data import (
    MARKET_TIMEZONE,
    QuotaProvider,
    RateLimiterQuotaProvider,
    RiskDataProvider,
    RiskDataUnavailable,
    RiskSnapshot,
    calculate_risk_score,
    default_risk_data_provider,
)
from .risk_limits import RiskLimits


class PreFlightCheck:
    """Validate authoritative account state before graph execution."""

    LOG_DIR = Path(".claude/risk_logs")
    LOG_FILE = LOG_DIR / "pre_flight_checks.log"

    def __init__(
        self,
        limits: Optional[RiskLimits] = None,
        config: Optional[Dict[str, Any]] = None,
        data_provider: Optional[RiskDataProvider] = None,
        quota_provider: Optional[QuotaProvider] = None,
    ):
        self.config = dict(config or {})
        self.limits = limits or RiskLimits.load_from_config(self.config)
        self.data_provider = data_provider or default_risk_data_provider()
        api_type = self.config.get("risk_api_type", DEFAULT_CONFIG["risk_api_type"])
        self.quota_provider = quota_provider or RateLimiterQuotaProvider(api_type)
        self._snapshot: Optional[RiskSnapshot] = None
        self._api_quota_remaining: Optional[int] = None
        self._setup_logging()

    def _setup_logging(self) -> None:
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        ticker: str,
        trade_date: str,
        action: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute all checks against one fresh broker snapshot."""
        ticker = ticker.upper()
        results: Dict[str, Any] = {
            "ticker": ticker,
            "trade_date": trade_date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": [],
            "passed": True,
            "blocked_reason": None,
            "warnings": [],
        }
        self._snapshot = None
        self._api_quota_remaining = None

        try:
            date.fromisoformat(trade_date)
            self._snapshot = self.data_provider.capture(ticker, trade_date)
            freshness = self._check_snapshot_freshness()
            results["checks"].append(freshness)
            if not freshness["passed"]:
                results["passed"] = False
                results["blocked_reason"] = freshness["reason"]
                self._log_result(results)
                return results
        except (ValueError, RiskDataUnavailable) as exc:
            self._block_for_data_error(results, "risk_data", str(exc))
            self._log_result(results)
            return results
        except Exception:
            self._block_for_data_error(
                results,
                "risk_data",
                "Authoritative broker risk data is unavailable",
            )
            self._log_result(results)
            return results

        normalized_action = action.lower() if action else None
        if normalized_action not in {None, "buy", "sell"}:
            self._block_for_data_error(results, "risk_data", "Invalid execution action")
            self._log_result(results)
            return results

        checks = [
            ("account_status", self._check_account_status),
            ("daily_trades", self._check_daily_trades),
            ("hourly_trades", self._check_hourly_trades),
        ]
        if normalized_action != "sell":
            checks.extend(
                [
                    ("position_limit", self._check_position_limit),
                    ("portfolio_exposure", self._check_portfolio_exposure),
                    ("cash_reserve", self._check_cash_reserve),
                    ("risk_score", self._check_risk_score),
                ]
            )
        if normalized_action is None:
            checks.append(("api_quota", self._check_api_quota))
        enforce_hours = self.config.get(
            "enforce_trading_hours", DEFAULT_CONFIG["enforce_trading_hours"]
        )
        if enforce_hours:
            checks.append(("trading_hours", self._check_trading_hours))

        for check_name, check_func in checks:
            try:
                check_result = check_func(ticker, trade_date)
                check_result.setdefault("source", self._require_snapshot().source)
                results["checks"].append(check_result)
                if not check_result["passed"]:
                    results["passed"] = False
                    results["blocked_reason"] = check_result["reason"]
                    break
                if check_result.get("warning"):
                    results["warnings"].append(check_result["warning"])
            except RiskDataUnavailable as exc:
                self._block_for_data_error(results, check_name, str(exc))
                break
            except Exception:
                self._block_for_data_error(
                    results,
                    check_name,
                    f"Check '{check_name}' could not be completed safely",
                )
                break

        self._log_result(results)
        return results

    @property
    def snapshot(self) -> Optional[RiskSnapshot]:
        """Return the snapshot used by the most recent completed run."""
        return self._snapshot

    def _check_snapshot_freshness(self) -> Dict[str, Any]:
        snapshot = self._require_snapshot()
        captured_at = snapshot.captured_at
        if captured_at.tzinfo is None:
            raise RiskDataUnavailable("Broker snapshot timestamp has no timezone")

        age_seconds = (
            datetime.now(timezone.utc) - captured_at.astimezone(timezone.utc)
        ).total_seconds()
        max_age = int(
            self.config.get(
                "risk_snapshot_max_age_seconds",
                DEFAULT_CONFIG["risk_snapshot_max_age_seconds"],
            )
        )
        if max_age <= 0:
            raise RiskDataUnavailable("risk_snapshot_max_age_seconds must be positive")
        if age_seconds < -5:
            return {
                "name": "risk_data",
                "passed": False,
                "reason": "Broker snapshot timestamp is in the future",
                "source": snapshot.source,
                "age_seconds": round(age_seconds, 3),
            }
        if age_seconds > max_age:
            return {
                "name": "risk_data",
                "passed": False,
                "reason": (
                    f"Broker risk data is stale: {age_seconds:.1f}s old "
                    f"(max {max_age}s)"
                ),
                "source": snapshot.source,
                "age_seconds": round(age_seconds, 3),
            }
        return {
            "name": "risk_data",
            "passed": True,
            "reason": None,
            "source": snapshot.source,
            "age_seconds": round(max(0.0, age_seconds), 3),
        }

    def _check_account_status(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker, trade_date
        snapshot = self._require_snapshot()
        if not snapshot.account_ready:
            return {
                "name": "account_status",
                "passed": False,
                "reason": (
                    "Broker account is not ready: "
                    f"status={snapshot.account_status}, "
                    f"trading_blocked={snapshot.trading_blocked}, "
                    f"account_blocked={snapshot.account_blocked}"
                ),
            }
        return {
            "name": "account_status",
            "passed": True,
            "reason": None,
            "status": snapshot.account_status,
        }

    def _check_position_limit(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del trade_date
        positions = self._get_current_positions()
        portfolio_value = self._get_portfolio_value()
        current_pct = abs(positions.get(ticker, 0.0)) / portfolio_value
        limit_pct = self.limits.max_position_per_symbol
        if current_pct >= limit_pct:
            return {
                "name": "position_limit",
                "passed": False,
                "reason": (
                    f"Position limit: {ticker} at {current_pct:.2%} "
                    f">= limit {limit_pct:.2%}"
                ),
                "current": current_pct,
                "limit": limit_pct,
            }
        if current_pct >= limit_pct * 0.8:
            return {
                "name": "position_limit",
                "passed": True,
                "warning": f"{ticker} position at {current_pct:.2%} (80% of limit)",
                "current": current_pct,
                "limit": limit_pct,
            }
        return {
            "name": "position_limit",
            "passed": True,
            "reason": None,
            "current": current_pct,
            "limit": limit_pct,
        }

    def _check_daily_trades(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker
        trades_today = self._get_trades_count(trade_date)
        limit = self.limits.max_daily_trades
        if trades_today >= limit:
            return {
                "name": "daily_trades",
                "passed": False,
                "reason": f"Daily trades: {trades_today} >= limit {limit}",
                "current": trades_today,
                "limit": limit,
            }
        if trades_today >= limit * 0.8:
            return {
                "name": "daily_trades",
                "passed": True,
                "warning": f"Daily trades at {trades_today} (80% of limit)",
                "current": trades_today,
                "limit": limit,
            }
        return {
            "name": "daily_trades",
            "passed": True,
            "reason": None,
            "current": trades_today,
            "limit": limit,
        }

    def _check_hourly_trades(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker
        current_hour = self._require_snapshot().captured_at.astimezone(MARKET_TIMEZONE).hour
        trades_this_hour = self._get_trades_count(trade_date, hour=current_hour)
        limit = self.limits.max_hourly_trades
        if trades_this_hour >= limit:
            return {
                "name": "hourly_trades",
                "passed": False,
                "reason": f"Hourly trades: {trades_this_hour} >= limit {limit}",
                "current": trades_this_hour,
                "limit": limit,
            }
        return {
            "name": "hourly_trades",
            "passed": True,
            "reason": None,
            "current": trades_this_hour,
            "limit": limit,
        }

    def _check_portfolio_exposure(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker, trade_date
        total_exposure = self._require_snapshot().gross_exposure / self._get_portfolio_value()
        limit = self.limits.max_portfolio_exposure
        if total_exposure >= limit:
            return {
                "name": "portfolio_exposure",
                "passed": False,
                "reason": f"Exposure: {total_exposure:.2%} >= limit {limit:.2%}",
                "current": total_exposure,
                "limit": limit,
            }
        return {
            "name": "portfolio_exposure",
            "passed": True,
            "reason": None,
            "current": total_exposure,
            "limit": limit,
        }

    def _check_cash_reserve(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker, trade_date
        snapshot = self._require_snapshot()
        cash_pct = snapshot.cash / snapshot.portfolio_value
        limit = self.limits.min_cash_reserve
        if cash_pct < limit:
            return {
                "name": "cash_reserve",
                "passed": False,
                "reason": f"Cash reserve: {cash_pct:.2%} < min {limit:.2%}",
                "current": cash_pct,
                "limit": limit,
            }
        return {
            "name": "cash_reserve",
            "passed": True,
            "reason": None,
            "current": cash_pct,
            "limit": limit,
        }

    def _check_api_quota(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker, trade_date
        remaining = self._get_api_quota_remaining()
        min_reserve = self.limits.min_api_quota_reserve
        if remaining < min_reserve:
            return {
                "name": "api_quota",
                "passed": False,
                "reason": f"API quota: {remaining} < reserve {min_reserve}",
                "current": remaining,
                "limit": min_reserve,
            }
        if remaining < min_reserve * 2:
            return {
                "name": "api_quota",
                "passed": True,
                "warning": f"API quota low: {remaining} remaining",
                "current": remaining,
                "limit": min_reserve,
            }
        return {
            "name": "api_quota",
            "passed": True,
            "reason": None,
            "current": remaining,
            "limit": min_reserve,
        }

    def _check_trading_hours(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del ticker
        snapshot = self._require_snapshot()
        broker_time = snapshot.captured_at.astimezone(MARKET_TIMEZONE)
        if broker_time.date() != date.fromisoformat(trade_date):
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": "Trade date does not match the broker market date",
                "market_time": broker_time.isoformat(),
            }
        if not snapshot.market_open:
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": "Broker reports that the market is closed",
                "market_time": broker_time.isoformat(),
            }

        regular_open = datetime.combine(
            broker_time.date(),
            time(self.limits.trading_start_hour, 30),
            tzinfo=MARKET_TIMEZONE,
        )
        effective_start = regular_open + timedelta(minutes=self.limits.avoid_first_minutes)
        configured_end = datetime.combine(
            broker_time.date(),
            time(self.limits.trading_end_hour),
            tzinfo=MARKET_TIMEZONE,
        )
        if broker_time < effective_start:
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": f"Avoiding first {self.limits.avoid_first_minutes} min volatility",
                "market_time": broker_time.isoformat(),
            }
        if broker_time >= configured_end:
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": "Outside configured trading hours",
                "market_time": broker_time.isoformat(),
            }
        return {
            "name": "trading_hours",
            "passed": True,
            "reason": None,
            "market_time": broker_time.isoformat(),
        }

    def _check_risk_score(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        del trade_date
        risk_score = self._get_risk_score(ticker)
        if risk_score > self.limits.max_risk_score:
            return {
                "name": "risk_score",
                "passed": False,
                "reason": f"Risk score: {risk_score} > max {self.limits.max_risk_score}",
                "current": risk_score,
                "limit": self.limits.max_risk_score,
            }
        return {
            "name": "risk_score",
            "passed": True,
            "reason": None,
            "current": risk_score,
            "limit": self.limits.max_risk_score,
        }

    def _get_current_positions(self) -> Dict[str, float]:
        return dict(self._require_snapshot().positions)

    def _get_portfolio_value(self) -> float:
        value = self._require_snapshot().portfolio_value
        if value <= 0:
            raise RiskDataUnavailable("Broker portfolio value must be positive")
        return value

    def _get_trades_count(self, trade_date: str, hour: Optional[int] = None) -> int:
        del trade_date
        snapshot = self._require_snapshot()
        return snapshot.trades_this_hour if hour is not None else snapshot.trades_today

    def _get_api_quota_remaining(self) -> int:
        if self._api_quota_remaining is None:
            remaining = self.quota_provider.remaining()
            if not isinstance(remaining, int) or remaining < 0:
                raise RiskDataUnavailable("API quota provider returned invalid data")
            self._api_quota_remaining = remaining
        return self._api_quota_remaining

    def _get_risk_score(self, ticker: str) -> int:
        return calculate_risk_score(self._require_snapshot(), self.limits, ticker)

    def _require_snapshot(self) -> RiskSnapshot:
        if self._snapshot is None:
            raise RiskDataUnavailable("Broker risk snapshot has not been captured")
        return self._snapshot

    def _block_for_data_error(
        self,
        results: Dict[str, Any],
        check_name: str,
        reason: str,
    ) -> None:
        source = self._snapshot.source if self._snapshot else "unavailable"
        results["checks"].append(
            {
                "name": check_name,
                "passed": False,
                "reason": reason,
                "error": True,
                "source": source,
            }
        )
        results["passed"] = False
        results["blocked_reason"] = reason

    def _log_result(self, results: Dict[str, Any]) -> None:
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with self.LOG_FILE.open("w") as file:
            json.dump(results, file)


def main() -> None:
    """CLI entry point for hook invocation."""
    if len(sys.argv) < 3:
        print("Usage: pre_flight_check <ticker> <date>")
        print("Example: pre_flight_check NVDA 2024-05-10")
        sys.exit(1)

    ticker = sys.argv[1]
    trade_date = sys.argv[2]
    config_path = Path(".claude/risk_limits.json")
    config: Dict[str, Any] = {}
    if config_path.exists():
        with config_path.open() as file:
            config = json.load(file)

    result = PreFlightCheck(config=config).run(ticker, trade_date)
    print(f"\n{'=' * 50}")
    print(f"Pre-flight Check: {ticker} on {trade_date}")
    print(f"{'=' * 50}")
    for check in result["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"  {status} - {check['name']}")
        if check.get("reason"):
            print(f"    Reason: {check['reason']}")
        if check.get("warning"):
            print(f"    Warning: {check['warning']}")
    print(f"{'=' * 50}")

    if result["passed"]:
        print("PASS: All checks cleared. Proceed with propagate().")
        sys.exit(0)
    print(f"BLOCKED: {result['blocked_reason']}")
    sys.exit(1)


if __name__ == "__main__":
    main()
