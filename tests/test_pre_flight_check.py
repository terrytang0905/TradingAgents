"""Unit tests for fail-closed pre-flight risk checks."""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tradingagents.risk_management.pre_flight_check import PreFlightCheck, main
from tradingagents.risk_management.risk_data import RiskSnapshot
from tradingagents.risk_management.risk_limits import RiskLimits


class StaticProvider:
    def __init__(self, snapshot: RiskSnapshot):
        self.snapshot = snapshot

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        return self.snapshot


class StaticQuota:
    def __init__(self, remaining: int):
        self.value = remaining

    def remaining(self) -> int:
        return self.value


def snapshot(**overrides) -> RiskSnapshot:
    values = {
        "source": "test-broker",
        "captured_at": datetime.now(timezone.utc),
        "portfolio_value": 1_000_000,
        "cash": 700_000,
        "positions": {"AAPL": 50_000},
        "position_quantities": {"AAPL": 500},
        "trades_today": 2,
        "trades_this_hour": 1,
        "market_open": True,
        "account_status": "ACTIVE",
        "trading_blocked": False,
        "account_blocked": False,
    }
    values.update(overrides)
    return RiskSnapshot(**values)


def checker(
    broker_snapshot: RiskSnapshot | None = None,
    quota: int = 500,
    limits: RiskLimits | None = None,
    **config,
) -> PreFlightCheck:
    instance = PreFlightCheck(
        limits=limits,
        config={"enforce_trading_hours": False, **config},
        data_provider=StaticProvider(broker_snapshot or snapshot()),
        quota_provider=StaticQuota(quota),
    )
    instance._snapshot = broker_snapshot or snapshot()
    return instance


class TestPreFlightCheckInit:
    def test_default_init(self):
        instance = PreFlightCheck()
        assert instance.limits.max_daily_trades == 50

    def test_init_with_limits(self):
        instance = PreFlightCheck(limits=RiskLimits(max_daily_trades=30))
        assert instance.limits.max_daily_trades == 30

    def test_init_preserves_internal_config(self):
        config = {"enforce_trading_hours": False}
        instance = PreFlightCheck(config=config)
        assert instance.config == config


class TestPreFlightCheckRun:
    def test_pass_all_checks(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = checker().run("AAPL", datetime.now().date().isoformat())

        assert result["passed"] is True
        assert result["ticker"] == "AAPL"
        assert len(result["checks"]) == 9

    def test_block_on_first_limit_failure(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = checker(snapshot(positions={"AAPL": 150_000})).run(
            "AAPL", datetime.now().date().isoformat()
        )

        assert result["passed"] is False
        assert "position" in result["blocked_reason"].lower()
        assert result["checks"][-1]["name"] == "position_limit"

    def test_internal_historical_mode_can_disable_hours(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        instance = checker(enforce_trading_hours=False)
        with patch.object(instance, "_check_trading_hours") as trading_hours:
            result = instance.run("AAPL", "2024-05-10")

        assert result["passed"] is True
        trading_hours.assert_not_called()


class TestPositionAndPortfolioChecks:
    def test_position_within_limit(self):
        result = checker()._check_position_limit("AAPL", "2024-05-10")
        assert result["passed"] is True

    def test_absolute_short_position_at_limit_is_blocked(self):
        result = checker(snapshot(positions={"AAPL": -100_000}))._check_position_limit(
            "AAPL", "2024-05-10"
        )
        assert result["passed"] is False

    def test_position_warning_threshold(self):
        result = checker(snapshot(positions={"AAPL": 85_000}))._check_position_limit(
            "AAPL", "2024-05-10"
        )
        assert result["passed"] is True
        assert result["warning"]

    def test_gross_exposure_does_not_net_long_and_short_positions(self):
        broker_snapshot = snapshot(
            positions={"AAPL": 400_000, "TSLA": -400_000},
            cash=200_000,
        )
        result = checker(broker_snapshot)._check_portfolio_exposure(
            "AAPL", "2024-05-10"
        )
        assert result["passed"] is False
        assert result["current"] == 0.8

    @pytest.mark.parametrize(
        ("cash", "passed"),
        [(300_000, True), (150_000, False)],
    )
    def test_cash_reserve_uses_broker_cash(self, cash, passed):
        result = checker(snapshot(cash=cash))._check_cash_reserve("AAPL", "2024-05-10")
        assert result["passed"] is passed


class TestTradeAndQuotaChecks:
    @pytest.mark.parametrize(
        ("count", "passed"),
        [(30, True), (50, False)],
    )
    def test_daily_trade_limit(self, count, passed):
        result = checker(snapshot(trades_today=count))._check_daily_trades(
            "AAPL", "2024-05-10"
        )
        assert result["passed"] is passed

    @pytest.mark.parametrize(
        ("quota", "passed", "warning"),
        [(500, True, False), (150, True, True), (50, False, False)],
    )
    def test_api_quota(self, quota, passed, warning):
        result = checker(quota=quota)._check_api_quota("AAPL", "2024-05-10")
        assert result["passed"] is passed
        assert bool(result.get("warning")) is warning


class TestTradingHoursCheck:
    def test_within_trading_hours(self):
        broker_snapshot = snapshot(
            captured_at=datetime(2025, 1, 2, 15, 30, tzinfo=timezone.utc)
        )
        result = checker(broker_snapshot)._check_trading_hours("AAPL", "2025-01-02")
        assert result["passed"] is True

    def test_broker_closed_market_is_blocked(self):
        broker_snapshot = snapshot(
            captured_at=datetime(2025, 1, 2, 15, 30, tzinfo=timezone.utc),
            market_open=False,
        )
        result = checker(broker_snapshot)._check_trading_hours("AAPL", "2025-01-02")
        assert result["passed"] is False

    def test_avoid_first_minutes(self):
        broker_snapshot = snapshot(
            captured_at=datetime(2025, 1, 2, 14, 33, tzinfo=timezone.utc)
        )
        result = checker(broker_snapshot)._check_trading_hours("AAPL", "2025-01-02")
        assert result["passed"] is False


class TestPreFlightCheckLogging:
    def test_log_content(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        instance = checker()
        instance.LOG_DIR = tmp_path
        instance.LOG_FILE = tmp_path / "checks.log"

        instance.run("AAPL", datetime.now().date().isoformat())

        with instance.LOG_FILE.open() as file:
            logged = json.load(file)
        assert logged["ticker"] == "AAPL"


class TestPreFlightCheckCLI:
    @patch("sys.argv", ["pre_flight_check", "AAPL", "2024-05-10"])
    @patch("tradingagents.risk_management.pre_flight_check.PreFlightCheck.run")
    def test_cli_pass(self, run):
        run.return_value = {
            "passed": True,
            "checks": [{"name": "test", "passed": True}],
            "blocked_reason": None,
        }
        with pytest.raises(SystemExit, match="0"):
            main()
