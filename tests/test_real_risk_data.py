"""Regression tests for production pre-flight risk data."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_data import (
    AlpacaRiskDataProvider,
    RiskDataUnavailable,
    RiskSnapshot,
    UnavailableRiskDataProvider,
    calculate_risk_score,
)
from tradingagents.risk_management.risk_limits import RiskLimits


def test_trading_hours_are_enforced_by_default():
    assert DEFAULT_CONFIG["enforce_trading_hours"] is True


def _alpaca_client() -> Mock:
    client = Mock()
    client.get_account.return_value = SimpleNamespace(
        portfolio_value="100000",
        cash="90000",
        status="ACTIVE",
        trading_blocked=False,
        account_blocked=False,
    )
    client.list_positions.return_value = [
        SimpleNamespace(symbol="AAPL", market_value="5000", qty="50"),
        SimpleNamespace(symbol="TSLA", market_value="-2000", qty="-10"),
    ]
    client.get_activities.return_value = [
        SimpleNamespace(
            transaction_time=datetime(2025, 1, 2, 15, 10, tzinfo=timezone.utc)
        ),
        SimpleNamespace(
            transaction_time=datetime(2025, 1, 2, 14, 40, tzinfo=timezone.utc)
        ),
    ]
    client.get_clock.return_value = SimpleNamespace(
        is_open=True,
        timestamp=datetime(2025, 1, 2, 15, 45, tzinfo=timezone.utc),
    )
    return client


def test_alpaca_provider_captures_real_account_orders_and_market_clock():
    client = _alpaca_client()

    snapshot = AlpacaRiskDataProvider(client=client).capture("AAPL", "2025-01-02")

    assert snapshot.source == "alpaca"
    assert snapshot.portfolio_value == 100000
    assert snapshot.cash == 90000
    assert snapshot.positions == {"AAPL": 5000, "TSLA": -2000}
    assert snapshot.position_quantities == {"AAPL": 50, "TSLA": -10}
    assert snapshot.gross_exposure == 7000
    assert snapshot.trades_today == 2
    assert snapshot.trades_this_hour == 1
    assert snapshot.market_open is True
    assert snapshot.account_ready is True
    client.get_activities.assert_called_once_with(
        activity_types="FILL",
        date="2025-01-02",
        direction="asc",
        page_size=100,
    )


def test_alpaca_provider_does_not_expose_low_level_request_errors():
    client = _alpaca_client()
    client.get_account.side_effect = RuntimeError("request included secret-key")

    with pytest.raises(RiskDataUnavailable, match="snapshot request failed") as error:
        AlpacaRiskDataProvider(client=client).capture("AAPL", "2025-01-02")

    assert "secret-key" not in str(error.value)


def test_alpaca_provider_fails_closed_when_fill_page_is_saturated():
    client = _alpaca_client()
    client.get_activities.return_value = [
        SimpleNamespace(
            transaction_time=datetime(2025, 1, 2, 15, 10, tzinfo=timezone.utc)
        )
        for _ in range(100)
    ]

    with pytest.raises(RiskDataUnavailable, match="exact trade count unavailable"):
        AlpacaRiskDataProvider(client=client).capture("AAPL", "2025-01-02")


def test_alpaca_provider_rejects_non_positive_portfolio_value():
    client = _alpaca_client()
    client.get_account.return_value.portfolio_value = "0"

    with pytest.raises(RiskDataUnavailable, match="portfolio value"):
        AlpacaRiskDataProvider(client=client).capture("AAPL", "2025-01-02")


@pytest.mark.parametrize("invalid_value", ["nan", "inf", "-inf"])
def test_alpaca_provider_rejects_non_finite_account_values(invalid_value):
    client = _alpaca_client()
    client.get_account.return_value.portfolio_value = invalid_value

    with pytest.raises(RiskDataUnavailable, match="portfolio value"):
        AlpacaRiskDataProvider(client=client).capture("AAPL", "2025-01-02")


def test_alpaca_provider_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)

    with pytest.raises(RiskDataUnavailable, match="credentials"):
        AlpacaRiskDataProvider.from_environment()


def test_alpaca_provider_rejects_untrusted_base_url(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://attacker.invalid")

    with pytest.raises(RiskDataUnavailable, match="ALPACA_BASE_URL"):
        AlpacaRiskDataProvider.from_environment()


def test_risk_score_is_derived_from_real_snapshot_utilization():
    snapshot = AlpacaRiskDataProvider(client=_alpaca_client()).capture(
        "AAPL", "2025-01-02"
    )

    assert calculate_risk_score(snapshot, RiskLimits(), "AAPL") == 50

    concentrated = replace(snapshot, positions={"AAPL": 80000})
    assert calculate_risk_score(concentrated, RiskLimits(), "AAPL") == 100


def test_account_ready_rejects_broker_trading_blocks():
    snapshot = RiskSnapshot(
        source="alpaca",
        captured_at=datetime.now(timezone.utc),
        portfolio_value=100000,
        cash=90000,
        positions={},
        position_quantities={},
        trades_today=0,
        trades_this_hour=0,
        market_open=True,
        account_status="ACTIVE",
        trading_blocked=True,
        account_blocked=False,
    )

    assert snapshot.account_ready is False


class StaticRiskDataProvider:
    def __init__(self, snapshot: RiskSnapshot):
        self.snapshot = snapshot
        self.calls = 0

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        self.calls += 1
        return self.snapshot


class StaticQuotaProvider:
    def __init__(self, remaining: int):
        self.value = remaining
        self.calls = 0

    def remaining(self) -> int:
        self.calls += 1
        return self.value


def _current_snapshot(**overrides) -> RiskSnapshot:
    values = {
        "source": "test-broker",
        "captured_at": datetime.now(timezone.utc),
        "portfolio_value": 100000,
        "cash": 90000,
        "positions": {"AAPL": 5000},
        "position_quantities": {"AAPL": 50},
        "trades_today": 2,
        "trades_this_hour": 1,
        "market_open": True,
        "account_status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
    }
    values.update(overrides)
    return RiskSnapshot(**values)


def _run_preflight(snapshot: RiskSnapshot, quota: int = 500, **config):
    risk_provider = StaticRiskDataProvider(snapshot)
    quota_provider = StaticQuotaProvider(quota)
    checker = PreFlightCheck(
        config=config,
        data_provider=risk_provider,
        quota_provider=quota_provider,
    )
    result = checker.run("AAPL", date.today().isoformat())
    return result, risk_provider, quota_provider


def test_preflight_uses_one_authoritative_snapshot_for_all_checks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result, risk_provider, quota_provider = _run_preflight(
        _current_snapshot(),
        enforce_trading_hours=False,
    )

    assert result["passed"] is True
    assert risk_provider.calls == 1
    assert quota_provider.calls == 1
    assert all(check["source"] == "test-broker" for check in result["checks"])


def test_preflight_blocks_stale_broker_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stale = _current_snapshot(captured_at=datetime.now(timezone.utc) - timedelta(minutes=2))

    result, _, _ = _run_preflight(
        stale,
        enforce_trading_hours=False,
        risk_snapshot_max_age_seconds=30,
    )

    assert result["passed"] is False
    assert result["checks"][0]["name"] == "risk_data"
    assert "stale" in result["blocked_reason"].lower()


def test_preflight_blocks_broker_restricted_account(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    blocked = _current_snapshot(trading_blocked=True)

    result, _, _ = _run_preflight(blocked, enforce_trading_hours=False)

    assert result["passed"] is False
    assert result["checks"][1]["name"] == "account_status"


def test_preflight_blocks_closed_market_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result, _, _ = _run_preflight(_current_snapshot(market_open=False))

    assert result["passed"] is False
    assert result["blocked_reason"] == "Broker reports that the market is closed"


def test_preflight_blocks_low_real_api_quota(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result, _, _ = _run_preflight(
        _current_snapshot(),
        quota=50,
        enforce_trading_hours=False,
    )

    assert result["passed"] is False
    assert result["blocked_reason"] == "API quota: 50 < reserve 100"


def test_legacy_mock_config_cannot_bypass_missing_broker_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    checker = PreFlightCheck(
        config={
            "enforce_trading_hours": False,
            "mock_positions": {},
            "mock_portfolio_value": 1_000_000,
            "mock_trades_count": 0,
            "mock_api_quota": 1_000,
            "mock_risk_scores": {"AAPL": 0},
        },
        data_provider=UnavailableRiskDataProvider("broker unavailable"),
        quota_provider=StaticQuotaProvider(500),
    )

    result = checker.run("AAPL", date.today().isoformat())

    assert result["passed"] is False
    assert result["blocked_reason"] == "broker unavailable"
