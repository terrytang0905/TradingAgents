"""Tests for Risk Limits Configuration."""

import pytest
import os
import json
from pathlib import Path
from unittest.mock import patch

from tradingagents.risk_management.risk_limits import RiskLimits


class TestRiskLimitsDefaults:
    """Test default RiskLimits values."""

    def test_default_position_limit(self):
        limits = RiskLimits()
        assert limits.max_position_per_symbol == 0.10
        assert limits.max_position_per_sector == 0.30

    def test_default_trade_limits(self):
        limits = RiskLimits()
        assert limits.max_daily_trades == 50
        assert limits.max_hourly_trades == 10
        assert limits.max_trade_size_usd == 100_000

    def test_default_portfolio_limits(self):
        limits = RiskLimits()
        assert limits.max_portfolio_exposure == 0.80
        assert limits.min_cash_reserve == 0.20

    def test_default_stop_loss(self):
        limits = RiskLimits()
        assert limits.default_stop_loss_pct == 0.05
        assert limits.trailing_stop_enabled == True
        assert limits.hard_stop_pct == 0.10


class TestRiskLimitsLoadFromConfig:
    """Test loading RiskLimits from config."""

    def test_load_from_empty_config(self):
        limits = RiskLimits.load_from_config({})
        assert limits.max_position_per_symbol == 0.10

    def test_load_from_config_dict(self):
        config = {
            "risk_limits": {
                "max_position_per_symbol": 0.15,
                "max_daily_trades": 30
            }
        }
        limits = RiskLimits.load_from_config(config)
        assert limits.max_position_per_symbol == 0.15
        assert limits.max_daily_trades == 30

    @patch.dict(os.environ, {"RISK_MAX_POSITION_PER_SYMBOL": "0.20"})
    def test_load_from_environment(self):
        limits = RiskLimits.load_from_config()
        assert limits.max_position_per_symbol == 0.20

    @patch.dict(os.environ, {
        "RISK_MAX_DAILY_TRADES": "25",
        "RISK_MAX_PORTFOLIO_EXPOSURE": "0.70"
    })
    def test_multiple_env_vars(self):
        limits = RiskLimits.load_from_config()
        assert limits.max_daily_trades == 25
        assert limits.max_portfolio_exposure == 0.70


class TestRiskLimitsValidateTrade:
    """Test trade validation."""

    def test_valid_trade(self):
        limits = RiskLimits()
        result = limits.validate_trade(
            symbol="AAPL",
            quantity=100,
            price=150.0,  # $15,000 trade
            portfolio_value=1_000_000,
            current_positions={"GOOGL": 50_000}
        )
        assert result["valid"] == True
        assert len(result["reasons"]) == 0

    def test_position_limit_exceeded(self):
        limits = RiskLimits(max_position_per_symbol=0.05)  # 5% limit
        result = limits.validate_trade(
            symbol="AAPL",
            quantity=100,
            price=150.0,
            portfolio_value=100_000,  # Trade is 15% of portfolio
            current_positions={}
        )
        assert result["valid"] == False
        assert "position limit" in result["reasons"][0].lower()

    def test_trade_size_exceeded(self):
        limits = RiskLimits(max_trade_size_usd=10_000)
        result = limits.validate_trade(
            symbol="AAPL",
            quantity=100,
            price=150.0,  # $15,000 > $10,000 limit
            portfolio_value=1_000_000,
            current_positions={}
        )
        assert result["valid"] == False
        assert "trade size" in result["reasons"][0].lower()

    def test_trade_size_below_minimum(self):
        limits = RiskLimits(min_trade_size_usd=5_000)
        result = limits.validate_trade(
            symbol="AAPL",
            quantity=10,
            price=100.0,  # $1,000 < $5,000 min
            portfolio_value=1_000_000,
            current_positions={}
        )
        assert result["valid"] == False
        assert "below min" in result["reasons"][0].lower()

    def test_sector_concentration(self):
        limits = RiskLimits(max_position_per_sector=0.25)
        result = limits.validate_trade(
            symbol="AAPL",
            quantity=100,
            price=200.0,  # $20,000
            portfolio_value=100_000,
            current_positions={"GOOGL": 20_000, "MSFT": 10_000},
            sector_mapping={"AAPL": "tech", "GOOGL": "tech", "MSFT": "tech"}
        )
        assert result["valid"] == False  # Tech sector would be 50%


class TestRiskLimitsStopLoss:
    """Test stop loss calculation."""

    def test_fixed_stop_loss(self):
        limits = RiskLimits(default_stop_loss_pct=0.05)
        stops = limits.get_stop_loss(entry_price=100.0)
        assert stops["fixed_stop"] == 95.0
        assert stops["hard_stop"] == 90.0

    def test_trailing_stop(self):
        limits = RiskLimits(trailing_stop_pct=0.03)
        stops = limits.get_stop_loss(
            entry_price=100.0,
            current_price=110.0,  # Price moved up
            use_trailing=True
        )
        assert stops["trailing_stop"] == 106.7  # 110 * 0.97

    def test_trailing_stop_disabled(self):
        limits = RiskLimits(trailing_stop_enabled=False)
        stops = limits.get_stop_loss(
            entry_price=100.0,
            current_price=110.0
        )
        assert stops["trailing_stop"] == stops["fixed_stop"]

    def test_max_stop_selection(self):
        limits = RiskLimits(default_stop_loss_pct=0.05, hard_stop_pct=0.10)
        stops = limits.get_stop_loss(entry_price=100.0, current_price=120.0)
        # Trailing stop at 116.4, hard stop at 90.0
        # Max stop should be trailing (less aggressive)
        assert stops["max_stop"] == stops["trailing_stop"]


class TestRiskLimitsPersistence:
    """Test save/load to file."""

    def test_save_to_file(self, tmp_path):
        limits = RiskLimits(
            max_position_per_symbol=0.15,
            max_daily_trades=30
        )
        filepath = tmp_path / "risk_limits.json"
        limits.save_to_file(filepath)

        with open(filepath) as f:
            data = json.load(f)

        assert data["risk_limits"]["max_position_per_symbol"] == 0.15
        assert data["risk_limits"]["max_daily_trades"] == 30

    def test_load_from_file(self, tmp_path):
        filepath = tmp_path / "risk_limits.json"
        data = {
            "risk_limits": {
                "max_position_per_symbol": 0.20,
                "max_daily_trades": 40
            }
        }
        with open(filepath, "w") as f:
            json.dump(data, f)

        limits = RiskLimits.load_from_file(filepath)
        assert limits.max_position_per_symbol == 0.20
        assert limits.max_daily_trades == 40


class TestRiskLimitsRepr:
    """Test string representation."""

    def test_repr_format(self):
        limits = RiskLimits()
        repr_str = repr(limits)
        assert "position=" in repr_str
        assert "daily_trades=" in repr_str
        assert "exposure=" in repr_str