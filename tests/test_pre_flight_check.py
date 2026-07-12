"""Tests for Pre-flight Risk Check."""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime

from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_limits import RiskLimits


class TestPreFlightCheckInit:
    """Test PreFlightCheck initialization."""

    def test_default_init(self):
        checker = PreFlightCheck()
        assert checker.limits is not None
        assert checker.limits.max_daily_trades == 50

    def test_init_with_limits(self):
        limits = RiskLimits(max_daily_trades=30)
        checker = PreFlightCheck(limits=limits)
        assert checker.limits.max_daily_trades == 30

    def test_init_with_config(self):
        config = {
            "mock_positions": {"AAPL": 100_000},
            "mock_portfolio_value": 500_000
        }
        checker = PreFlightCheck(config=config)
        assert checker.config == config


class TestPreFlightCheckRun:
    """Test run() method."""

    def test_pass_all_checks(self):
        config = {
            "mock_positions": {},
            "mock_portfolio_value": 1_000_000,
            "mock_trades_count": 0,
            "mock_api_quota": 1000
        }
        checker = PreFlightCheck(config=config)
        result = checker.run("AAPL", "2024-05-10")

        assert result["passed"] == True
        assert result["ticker"] == "AAPL"
        assert result["trade_date"] == "2024-05-10"
        assert len(result["checks"]) > 0

    def test_block_on_first_failure(self):
        config = {
            "mock_positions": {"AAPL": 150_000},  # 15% > 10% limit
            "mock_portfolio_value": 1_000_000
        }
        limits = RiskLimits(max_position_per_symbol=0.10)
        checker = PreFlightCheck(limits=limits, config=config)
        result = checker.run("AAPL", "2024-05-10")

        assert result["passed"] == False
        assert "position" in result["blocked_reason"].lower()

    def test_historical_analysis_skips_trading_hours_by_default(self):
        checker = PreFlightCheck(config={"mock_api_quota": 1000})
        with patch.object(
            checker,
            "_check_trading_hours",
            return_value={"name": "trading_hours", "passed": False, "reason": "closed"},
        ) as trading_hours:
            result = checker.run("AAPL", "2024-05-10")

        assert result["passed"] is True
        trading_hours.assert_not_called()


class TestPositionLimitCheck:
    """Test position limit check."""

    def test_position_within_limit(self):
        config = {
            "mock_positions": {"AAPL": 50_000},
            "mock_portfolio_value": 1_000_000  # 5% < 10% limit
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_position_limit("AAPL", "2024-05-10")

        assert result["passed"] == True

    def test_position_at_limit(self):
        config = {
            "mock_positions": {"AAPL": 100_000},
            "mock_portfolio_value": 1_000_000  # 10% = limit
        }
        limits = RiskLimits(max_position_per_symbol=0.10)
        checker = PreFlightCheck(limits=limits, config=config)
        result = checker._check_position_limit("AAPL", "2024-05-10")

        assert result["passed"] == False

    def test_position_warning_threshold(self):
        config = {
            "mock_positions": {"AAPL": 85_000},
            "mock_portfolio_value": 1_000_000  # 8.5% > 80% of 10%
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_position_limit("AAPL", "2024-05-10")

        assert result["passed"] == True
        assert result.get("warning") is not None


class TestDailyTradesCheck:
    """Test daily trade count check."""

    def test_trades_within_limit(self):
        config = {"mock_trades_count": 30}
        checker = PreFlightCheck(config=config)
        result = checker._check_daily_trades("AAPL", "2024-05-10")

        assert result["passed"] == True
        assert result["current"] == 30

    def test_trades_at_limit(self):
        config = {"mock_trades_count": 50}
        checker = PreFlightCheck(config=config)
        result = checker._check_daily_trades("AAPL", "2024-05-10")

        assert result["passed"] == False
        assert "50" in result["reason"]


class TestPortfolioExposureCheck:
    """Test portfolio exposure check."""

    def test_exposure_within_limit(self):
        config = {
            "mock_positions": {"AAPL": 200_000, "GOOGL": 200_000},
            "mock_portfolio_value": 1_000_000  # 40% < 80%
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_portfolio_exposure("AAPL", "2024-05-10")

        assert result["passed"] == True

    def test_exposure_at_limit(self):
        config = {
            "mock_positions": {"AAPL": 400_000, "GOOGL": 400_000},
            "mock_portfolio_value": 1_000_000  # 80% = limit
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_portfolio_exposure("AAPL", "2024-05-10")

        assert result["passed"] == False


class TestCashReserveCheck:
    """Test cash reserve check."""

    def test_sufficient_cash(self):
        config = {
            "mock_positions": {"AAPL": 300_000},
            "mock_portfolio_value": 1_000_000  # 70% cash > 20% min
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_cash_reserve("AAPL", "2024-05-10")

        assert result["passed"] == True

    def test_insufficient_cash(self):
        config = {
            "mock_positions": {"AAPL": 850_000},
            "mock_portfolio_value": 1_000_000  # 15% cash < 20% min
        }
        checker = PreFlightCheck(config=config)
        result = checker._check_cash_reserve("AAPL", "2024-05-10")

        assert result["passed"] == False


class TestAPIQuotaCheck:
    """Test API quota check."""

    def test_sufficient_quota(self):
        config = {"mock_api_quota": 500}
        checker = PreFlightCheck(config=config)
        result = checker._check_api_quota("AAPL", "2024-05-10")

        assert result["passed"] == True

    def test_low_quota_warning(self):
        config = {"mock_api_quota": 150}  # 150 < 2*100 reserve
        checker = PreFlightCheck(config=config)
        result = checker._check_api_quota("AAPL", "2024-05-10")

        assert result["passed"] == True
        assert result.get("warning") is not None

    def test_insufficient_quota(self):
        config = {"mock_api_quota": 50}  # 50 < 100 reserve
        checker = PreFlightCheck(config=config)
        result = checker._check_api_quota("AAPL", "2024-05-10")

        assert result["passed"] == False


class TestTradingHoursCheck:
    """Test trading hours check."""

    @patch('tradingagents.risk_management.pre_flight_check.datetime')
    def test_within_trading_hours(self, mock_datetime):
        mock_now = MagicMock()
        mock_now.hour = 10  # 10 AM
        mock_now.minute = 30
        mock_datetime.now.return_value = mock_now

        checker = PreFlightCheck()
        result = checker._check_trading_hours("AAPL", "2024-05-10")

        assert result["passed"] == True

    @patch('tradingagents.risk_management.pre_flight_check.datetime')
    def test_before_trading_hours(self, mock_datetime):
        mock_now = MagicMock()
        mock_now.hour = 8  # 8 AM
        mock_now.minute = 30
        mock_datetime.now.return_value = mock_now

        checker = PreFlightCheck()
        result = checker._check_trading_hours("AAPL", "2024-05-10")

        assert result["passed"] == False

    @patch('tradingagents.risk_management.pre_flight_check.datetime')
    def test_avoid_first_minutes(self, mock_datetime):
        mock_now = MagicMock()
        mock_now.hour = 9
        mock_now.minute = 3  # Within first 5 minutes
        mock_datetime.now.return_value = mock_now

        checker = PreFlightCheck()
        result = checker._check_trading_hours("AAPL", "2024-05-10")

        assert result["passed"] == False


class TestPreFlightCheckLogging:
    """Test logging functionality."""

    def test_log_file_created(self, tmp_path):
        checker = PreFlightCheck()
        checker.LOG_DIR = tmp_path
        checker.LOG_FILE = tmp_path / "checks.log"

        result = checker.run("AAPL", "2024-05-10")
        checker._log_result(result)

        assert checker.LOG_FILE.exists()

    def test_log_content(self, tmp_path):
        checker = PreFlightCheck()
        checker.LOG_DIR = tmp_path
        checker.LOG_FILE = tmp_path / "checks.log"

        result = checker.run("AAPL", "2024-05-10")
        checker._log_result(result)

        with open(checker.LOG_FILE) as f:
            logged = json.load(f)

        assert logged["ticker"] == "AAPL"
        assert logged["trade_date"] == "2024-05-10"


class TestPreFlightCheckCLI:
    """Test CLI functionality."""

    @patch('sys.argv', ['pre_flight_check', 'AAPL', '2024-05-10'])
    @patch('tradingagents.risk_management.pre_flight_check.PreFlightCheck.run')
    def test_cli_pass(self, mock_run):
        mock_run.return_value = {
            "passed": True,
            "checks": [{"name": "test", "passed": True}],
            "blocked_reason": None
        }

        # Should exit 0
        with pytest.raises(SystemExit) as exc:
            from tradingagents.risk_management.pre_flight_check import main
            main()

        assert exc.value.code == 0

    @patch('sys.argv', ['pre_flight_check', 'AAPL', '2024-05-10'])
    @patch('tradingagents.risk_management.pre_flight_check.PreFlightCheck.run')
    def test_cli_block(self, mock_run):
        mock_run.return_value = {
            "passed": False,
            "checks": [{"name": "test", "passed": False, "reason": "Blocked"}],
            "blocked_reason": "Blocked"
        }

        # Should exit 1
        with pytest.raises(SystemExit) as exc:
            from tradingagents.risk_management.pre_flight_check import main
            main()

        assert exc.value.code == 1
