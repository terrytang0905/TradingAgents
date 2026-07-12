"""Pre-flight Risk Check for TradingAgents.

Enforced by Hook before propagate() execution.
Returns exit code 0 (PASS) or 1 (BLOCKED).
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

from .risk_limits import RiskLimits


class PreFlightCheck:
    """Risk validation before propagate() execution.

    Usage:
        checker = PreFlightCheck()
        result = checker.run("NVDA", "2024-05-10")

        if result["passed"]:
            # Proceed with propagate()
        else:
            # Block execution, log reason
    """

    # Log file for all checks
    LOG_DIR = Path(".claude/risk_logs")
    LOG_FILE = LOG_DIR / "pre_flight_checks.log"

    def __init__(self, limits: RiskLimits = None, config: Dict[str, Any] = None):
        """Initialize pre-flight checker.

        Args:
            limits: RiskLimits instance (loads default if None)
            config: Optional config dict for additional settings
        """
        self.limits = limits or RiskLimits.load_from_config(config)
        self.config = config or {}
        self._setup_logging()

    def _setup_logging(self):
        """Ensure log directory exists."""
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

    def run(self, ticker: str, trade_date: str) -> Dict[str, Any]:
        """Execute all pre-flight checks.

        Args:
            ticker: Symbol to trade
            trade_date: Date string YYYY-mm-dd

        Returns:
            Dict with 'passed', 'checks', 'blocked_reason'
        """
        results = {
            "ticker": ticker,
            "trade_date": trade_date,
            "timestamp": datetime.now().isoformat(),
            "checks": [],
            "passed": True,
            "blocked_reason": None,
            "warnings": []
        }

        # Execute all checks in order
        checks = [
            ("position_limit", self._check_position_limit),
            ("daily_trades", self._check_daily_trades),
            ("hourly_trades", self._check_hourly_trades),
            ("portfolio_exposure", self._check_portfolio_exposure),
            ("cash_reserve", self._check_cash_reserve),
            ("api_quota", self._check_api_quota),
            ("risk_score", self._check_risk_score),
        ]
        if self.config.get("enforce_trading_hours", False):
            checks.insert(-1, ("trading_hours", self._check_trading_hours))

        for check_name, check_func in checks:
            try:
                check_result = check_func(ticker, trade_date)
                results["checks"].append(check_result)

                if not check_result["passed"]:
                    results["passed"] = False
                    results["blocked_reason"] = check_result["reason"]

                    # First failure blocks; no need to continue
                    break

                if check_result.get("warning"):
                    results["warnings"].append(check_result["warning"])

            except Exception as e:
                # Exception during check = block with error
                results["checks"].append({
                    "name": check_name,
                    "passed": False,
                    "reason": f"Check error: {str(e)}",
                    "error": True
                })
                results["passed"] = False
                results["blocked_reason"] = f"Check '{check_name}' failed: {str(e)}"
                break

        # Log result
        self._log_result(results)

        return results

    def _check_position_limit(self, ticker: str, trade_date: str) -> Dict:
        """Check if position limit reached for symbol."""
        positions = self._get_current_positions()
        portfolio_value = self._get_portfolio_value()

        if ticker in positions:
            current_pct = positions[ticker] / portfolio_value
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
                    "limit": limit_pct
                }

            # Warning at 80% of limit
            if current_pct >= limit_pct * 0.8:
                return {
                    "name": "position_limit",
                    "passed": True,
                    "warning": f"{ticker} position at {current_pct:.2%} (80% of limit)",
                    "current": current_pct,
                    "limit": limit_pct
                }

        return {
            "name": "position_limit",
            "passed": True,
            "reason": None,
            "current": positions.get(ticker, 0) / portfolio_value if portfolio_value > 0 else 0
        }

    def _check_daily_trades(self, ticker: str, trade_date: str) -> Dict:
        """Check if daily trade limit reached."""
        trades_today = self._get_trades_count(trade_date)
        limit = self.limits.max_daily_trades

        if trades_today >= limit:
            return {
                "name": "daily_trades",
                "passed": False,
                "reason": f"Daily trades: {trades_today} >= limit {limit}",
                "current": trades_today,
                "limit": limit
            }

        # Warning at 80%
        if trades_today >= limit * 0.8:
            return {
                "name": "daily_trades",
                "passed": True,
                "warning": f"Daily trades at {trades_today} (80% of limit)",
                "current": trades_today,
                "limit": limit
            }

        return {
            "name": "daily_trades",
            "passed": True,
            "current": trades_today,
            "limit": limit
        }

    def _check_hourly_trades(self, ticker: str, trade_date: str) -> Dict:
        """Check if hourly trade limit reached."""
        current_hour = datetime.now().hour
        trades_this_hour = self._get_trades_count(trade_date, hour=current_hour)
        limit = self.limits.max_hourly_trades

        if trades_this_hour >= limit:
            return {
                "name": "hourly_trades",
                "passed": False,
                "reason": f"Hourly trades: {trades_this_hour} >= limit {limit}",
                "current": trades_this_hour,
                "limit": limit
            }

        return {
            "name": "hourly_trades",
            "passed": True,
            "current": trades_this_hour,
            "limit": limit
        }

    def _check_portfolio_exposure(self, ticker: str, trade_date: str) -> Dict:
        """Check if portfolio exposure limit reached."""
        positions = self._get_current_positions()
        portfolio_value = self._get_portfolio_value()

        total_exposure = sum(positions.values()) / portfolio_value
        limit = self.limits.max_portfolio_exposure

        if total_exposure >= limit:
            return {
                "name": "portfolio_exposure",
                "passed": False,
                "reason": f"Exposure: {total_exposure:.2%} >= limit {limit:.2%}",
                "current": total_exposure,
                "limit": limit
            }

        return {
            "name": "portfolio_exposure",
            "passed": True,
            "current": total_exposure,
            "limit": limit
        }

    def _check_cash_reserve(self, ticker: str, trade_date: str) -> Dict:
        """Check if minimum cash reserve maintained."""
        positions = self._get_current_positions()
        portfolio_value = self._get_portfolio_value()

        cash = portfolio_value - sum(positions.values())
        cash_pct = cash / portfolio_value
        limit = self.limits.min_cash_reserve

        if cash_pct < limit:
            return {
                "name": "cash_reserve",
                "passed": False,
                "reason": f"Cash reserve: {cash_pct:.2%} < min {limit:.2%}",
                "current": cash_pct,
                "limit": limit
            }

        return {
            "name": "cash_reserve",
            "passed": True,
            "current": cash_pct,
            "limit": limit
        }

    def _check_api_quota(self, ticker: str, trade_date: str) -> Dict:
        """Check API quota reserve."""
        remaining = self._get_api_quota_remaining()
        min_reserve = self.limits.min_api_quota_reserve

        if remaining < min_reserve:
            return {
                "name": "api_quota",
                "passed": False,
                "reason": f"API quota: {remaining} < reserve {min_reserve}",
                "current": remaining,
                "limit": min_reserve
            }

        # Warning at 2x reserve
        if remaining < min_reserve * 2:
            return {
                "name": "api_quota",
                "passed": True,
                "warning": f"API quota low: {remaining} remaining",
                "current": remaining,
                "limit": min_reserve
            }

        return {
            "name": "api_quota",
            "passed": True,
            "current": remaining,
            "limit": min_reserve
        }

    def _check_trading_hours(self, ticker: str, trade_date: str) -> Dict:
        """Check if within valid trading hours."""
        now = datetime.now()
        hour = now.hour

        start = self.limits.trading_start_hour + self.limits.avoid_first_minutes / 60
        end = self.limits.trading_end_hour

        # Skip first N minutes
        if self.limits.avoid_first_minutes > 0:
            effective_start = self.limits.trading_start_hour + self.limits.avoid_first_minutes
            if hour == self.limits.trading_start_hour and now.minute < self.limits.avoid_first_minutes:
                return {
                    "name": "trading_hours",
                    "passed": False,
                    "reason": f"Avoiding first {self.limits.avoid_first_minutes} min volatility",
                    "current_hour": hour,
                    "current_minute": now.minute
                }

        if hour < start or hour >= end:
            return {
                "name": "trading_hours",
                "passed": False,
                "reason": f"Outside trading hours: {hour}:00 (valid {start}-{end})",
                "current_hour": hour
            }

        return {
            "name": "trading_hours",
            "passed": True,
            "current_hour": hour
        }

    def _check_risk_score(self, ticker: str, trade_date: str) -> Dict:
        """Check if symbol risk score acceptable."""
        # This would integrate with a risk scoring system
        # For now, we mock it or skip
        risk_score = self._get_risk_score(ticker)

        if risk_score is None:
            # No risk score available - pass with warning
            return {
                "name": "risk_score",
                "passed": True,
                "warning": "Risk score not available",
                "current": None
            }

        if risk_score > self.limits.max_risk_score:
            return {
                "name": "risk_score",
                "passed": False,
                "reason": f"Risk score: {risk_score} > max {self.limits.max_risk_score}",
                "current": risk_score,
                "limit": self.limits.max_risk_score
            }

        return {
            "name": "risk_score",
            "passed": True,
            "current": risk_score,
            "limit": self.limits.max_risk_score
        }

    # === Integration Stubs ===
    # These should be implemented with actual data sources

    def _get_current_positions(self) -> Dict[str, float]:
        """Fetch current positions from portfolio/broker.

        Returns:
            Dict mapping symbol -> position value (USD)
        """
        # TODO: Integrate with broker API (Alpaca, etc.)
        # For testing, return empty positions
        return self.config.get("mock_positions", {})

    def _get_portfolio_value(self) -> float:
        """Fetch total portfolio value.

        Returns:
            Portfolio value in USD
        """
        # TODO: Integrate with broker API
        return self.config.get("mock_portfolio_value", 1_000_000)

    def _get_trades_count(self, date: str, hour: int = None) -> int:
        """Count trades executed on given date/hour.

        Args:
            date: Date string YYYY-mm-dd
            hour: Optional hour filter

        Returns:
            Number of trades
        """
        # TODO: Integrate with trade log
        return self.config.get("mock_trades_count", 0)

    def _get_api_quota_remaining(self) -> int:
        """Get remaining API quota.

        Returns:
            Number of API calls remaining in current window
        """
        if "mock_api_quota" in self.config:
            return self.config["mock_api_quota"]

        # TODO: Integrate with rate_limiter
        try:
            from tradingagents.monitoring.rate_limiter import RateLimiter
            quota = RateLimiter.get_remaining_quota("openai_chat")
            return quota.get("rpm_remaining", 1000)
        except ImportError:
            return self.config.get("mock_api_quota", 1000)

    def _get_risk_score(self, ticker: str) -> int:
        """Get risk score for symbol.

        Returns:
            Risk score 0-100, or None if unavailable
        """
        # TODO: Integrate with risk scoring model
        return self.config.get("mock_risk_scores", {}).get(ticker)

    def _log_result(self, results: Dict[str, Any]):
        """Log check result to file."""
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.LOG_FILE, "w") as f:
            json.dump(results, f)


def main():
    """CLI entry point for Hook invocation.

    Usage:
        python -m tradingagents.risk_management.pre_flight_check <ticker> <date>

    Exit codes:
        0: PASS - Risk checks cleared
        1: BLOCKED - Trade blocked by risk limit
    """
    if len(sys.argv) < 3:
        print("Usage: pre_flight_check <ticker> <date>")
        print("Example: pre_flight_check NVDA 2024-05-10")
        sys.exit(1)

    ticker = sys.argv[1]
    trade_date = sys.argv[2]

    # Optional: Load config from file
    config_path = Path(".claude/risk_limits.json")
    config = {}
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)

    checker = PreFlightCheck(config=config)
    result = checker.run(ticker, trade_date)

    # Print result
    print(f"\n{'='*50}")
    print(f"Pre-flight Check: {ticker} on {trade_date}")
    print(f"{'='*50}")

    for check in result["checks"]:
        status = "✅ PASS" if check["passed"] else "❌ FAIL"
        print(f"  {status} - {check['name']}")
        if check.get("reason"):
            print(f"    Reason: {check['reason']}")
        if check.get("warning"):
            print(f"    Warning: {check['warning']}")

    print(f"{'='*50}")

    if result["passed"]:
        print("✅ PASS: All checks cleared. Proceed with propagate().")
        sys.exit(0)
    else:
        print(f"❌ BLOCKED: {result['blocked_reason']}")
        sys.exit(1)


if __name__ == "__main__":
    main()
