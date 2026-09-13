"""Production data providers for pre-flight trading risk checks."""

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Dict, Protocol
from zoneinfo import ZoneInfo

from .risk_limits import RiskLimits

MARKET_TIMEZONE = ZoneInfo("America/New_York")
ALLOWED_ALPACA_BASE_URLS = {
    "https://paper-api.alpaca.markets",
    "https://api.alpaca.markets",
}
FILL_PAGE_SIZE = 100


class RiskDataUnavailable(RuntimeError):
    """Raised when authoritative risk data cannot be obtained safely."""


@dataclass(frozen=True)
class RiskSnapshot:
    """Point-in-time broker state used by every check in one pre-flight run."""

    source: str
    captured_at: datetime
    portfolio_value: float
    cash: float
    positions: Dict[str, float]
    position_quantities: Dict[str, float]
    trades_today: int
    trades_this_hour: int
    market_open: bool
    account_status: str
    trading_blocked: bool
    account_blocked: bool

    @property
    def gross_exposure(self) -> float:
        return sum(abs(value) for value in self.positions.values())

    @property
    def account_ready(self) -> bool:
        return (
            self.account_status.upper() == "ACTIVE"
            and not self.trading_blocked
            and not self.account_blocked
        )


class RiskDataProvider(Protocol):
    """Authoritative source for account and market risk state."""

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        """Capture a fresh snapshot for one pre-flight run."""


class QuotaProvider(Protocol):
    """Authoritative source for remaining API request capacity."""

    def remaining(self) -> int:
        """Return remaining calls in the active rate-limit window."""


class UnavailableRiskDataProvider:
    """Deferred fail-closed provider for missing startup configuration."""

    def __init__(self, reason: str):
        self.reason = reason

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        raise RiskDataUnavailable(self.reason)


class AlpacaRiskDataProvider:
    """Read-only Alpaca adapter for account, positions, fills, and market clock."""

    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def from_environment(cls) -> "AlpacaRiskDataProvider":
        api_key = os.getenv("ALPACA_API_KEY", "").strip()
        secret_key = os.getenv("ALPACA_SECRET_KEY", "").strip()
        if not api_key or not secret_key:
            raise RiskDataUnavailable("Alpaca credentials are not configured")

        base_url = os.getenv(
            "ALPACA_BASE_URL", "https://paper-api.alpaca.markets"
        ).rstrip("/")
        if base_url not in ALLOWED_ALPACA_BASE_URLS:
            raise RiskDataUnavailable(
                "ALPACA_BASE_URL must be an approved Alpaca paper or live endpoint"
            )

        try:
            import alpaca_trade_api as tradeapi
        except ImportError as exc:
            raise RiskDataUnavailable("alpaca-trade-api is not installed") from exc

        client = tradeapi.REST(
            key_id=api_key,
            secret_key=secret_key,
            base_url=base_url,
            api_version="v2",
        )
        return cls(client=client)

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        del ticker  # Snapshot contains all current positions.
        try:
            target_date = date.fromisoformat(trade_date)
        except ValueError as exc:
            raise RiskDataUnavailable("trade_date must use YYYY-MM-DD") from exc

        try:
            account = self.client.get_account()
            positions = self.client.list_positions()
            clock = self.client.get_clock()
            captured_at = _as_datetime(clock.timestamp)
            fills = self.client.get_activities(
                activity_types="FILL",
                date=target_date.isoformat(),
                direction="asc",
                page_size=FILL_PAGE_SIZE,
            )
        except RiskDataUnavailable:
            raise
        except Exception as exc:
            raise RiskDataUnavailable("Alpaca risk snapshot request failed") from exc

        portfolio_value = _as_float(account.portfolio_value, "portfolio value")
        if portfolio_value <= 0:
            raise RiskDataUnavailable("Alpaca portfolio value must be positive")

        cash = _as_float(account.cash, "cash balance")
        position_values = {
            str(position.symbol).upper(): _as_float(
                position.market_value, f"{position.symbol} market value"
            )
            for position in positions
        }
        position_quantities = {
            str(position.symbol).upper(): _as_float(
                position.qty, f"{position.symbol} quantity"
            )
            for position in positions
        }
        broker_time = captured_at.astimezone(MARKET_TIMEZONE)
        if len(fills) >= FILL_PAGE_SIZE:
            raise RiskDataUnavailable(
                "Alpaca fill activity page is saturated; exact trade count unavailable"
            )
        filled_times = [
            _as_datetime(fill.transaction_time).astimezone(MARKET_TIMEZONE)
            for fill in fills
        ]
        trades_today = sum(filled.date() == target_date for filled in filled_times)
        trades_this_hour = sum(
            filled.date() == target_date
            and broker_time.date() == target_date
            and filled.hour == broker_time.hour
            for filled in filled_times
        )

        return RiskSnapshot(
            source="alpaca",
            captured_at=captured_at,
            portfolio_value=portfolio_value,
            cash=cash,
            positions=position_values,
            position_quantities=position_quantities,
            trades_today=trades_today,
            trades_this_hour=trades_this_hour,
            market_open=bool(clock.is_open),
            account_status=str(account.status),
            trading_blocked=bool(getattr(account, "trading_blocked", False)),
            account_blocked=bool(getattr(account, "account_blocked", False)),
        )


class RateLimiterQuotaProvider:
    """Adapter for the process-wide LLM API rate limiter."""

    def __init__(self, api_type: str):
        self.api_type = api_type

    def remaining(self) -> int:
        from tradingagents.monitoring.rate_limiter import RateLimiter

        if self.api_type not in RateLimiter.LIMITS:
            raise RiskDataUnavailable(
                f"Rate limiter is not configured for {self.api_type}"
            )
        quota = RateLimiter.get_remaining_quota(self.api_type)
        remaining = quota.get("rpm_remaining")
        if not isinstance(remaining, int) or remaining < 0:
            raise RiskDataUnavailable("Rate limiter returned invalid quota data")
        return remaining


def default_risk_data_provider() -> RiskDataProvider:
    """Build the broker provider without allowing synthetic fallbacks."""
    try:
        return AlpacaRiskDataProvider.from_environment()
    except RiskDataUnavailable as exc:
        return UnavailableRiskDataProvider(str(exc))


def calculate_risk_score(
    snapshot: RiskSnapshot,
    limits: RiskLimits,
    ticker: str,
) -> int:
    """Calculate 0-100 risk from utilization of hard account limits."""
    if snapshot.portfolio_value <= 0 or not snapshot.account_ready:
        return 100

    target_position = abs(snapshot.positions.get(ticker.upper(), 0.0))
    utilization = [
        _ratio(
            target_position / snapshot.portfolio_value,
            limits.max_position_per_symbol,
        ),
        _ratio(
            snapshot.gross_exposure / snapshot.portfolio_value,
            limits.max_portfolio_exposure,
        ),
        _ratio(snapshot.trades_today, limits.max_daily_trades),
        _ratio(snapshot.trades_this_hour, limits.max_hourly_trades),
    ]

    cash_ratio = snapshot.cash / snapshot.portfolio_value
    if cash_ratio < limits.min_cash_reserve:
        utilization.append(1.0)

    return round(min(1.0, max(utilization, default=0.0)) * 100)


def _ratio(value: float, limit: float) -> float:
    if limit <= 0:
        return 1.0
    return max(0.0, value / limit)


def _as_float(value: Any, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RiskDataUnavailable(f"Invalid Alpaca {field_name}") from exc
    if not isfinite(parsed):
        raise RiskDataUnavailable(f"Invalid Alpaca {field_name}")
    return parsed


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise RiskDataUnavailable("Invalid Alpaca timestamp") from exc

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
