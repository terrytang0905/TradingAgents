"""Risk Limits Configuration for TradingAgents.

Defines position limits, trade limits, portfolio constraints,
and API protection thresholds.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
import os
import json
from pathlib import Path


@dataclass
class RiskLimits:
    """Risk limit configuration for trading operations.

    All limits are enforced by pre_flight_check Hook before propagate().
    """

    # === Position Limits ===
    max_position_per_symbol: float = 0.10  # 10% of portfolio per symbol
    max_position_per_sector: float = 0.30  # 30% per sector
    max_concentrated_positions: int = 5    # Max symbols >5% allocation

    # === Trade Limits ===
    max_daily_trades: int = 50             # Max trades per day
    max_hourly_trades: int = 10            # Max trades per hour
    max_trade_size_usd: float = 100_000    # Max single trade value
    min_trade_size_usd: float = 1_000      # Min trade to avoid noise

    # === Portfolio Limits ===
    max_portfolio_exposure: float = 0.80   # 80% invested max
    min_cash_reserve: float = 0.20         # 20% cash reserve min
    max_correlated_assets: float = 0.40    # Max correlated exposure

    # === Stop Loss Rules ===
    default_stop_loss_pct: float = 0.05    # 5% stop loss
    trailing_stop_enabled: bool = True
    trailing_stop_pct: float = 0.03        # 3% trailing
    hard_stop_pct: float = 0.10            # 10% hard stop (never override)

    # === API Protection ===
    min_api_quota_reserve: int = 100       # Reserve 100 API calls
    api_timeout_seconds: float = 30.0      # API timeout

    # === Leverage & Derivatives ===
    max_leverage: float = 1.0              # No leverage by default
    allow_options: bool = False            # Disable options trading
    allow_shortselling: bool = False       # Disable short selling

    # === Time Constraints ===
    trading_start_hour: int = 9            # Market open hour (EST)
    trading_end_hour: int = 16             # Market close hour (EST)
    avoid_first_minutes: int = 5           # Avoid first 5 min volatility

    # === Risk Score Thresholds ===
    max_risk_score: int = 70               # Block if risk_score > 70
    min_confidence_threshold: float = 0.6  # Block if confidence < 60%

    # === Custom Overrides ===
    custom_limits: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load_from_config(cls, config: Dict[str, Any] = None) -> "RiskLimits":
        """Load limits from config dict or environment variables.

        Priority: Environment > Config Dict > Defaults

        Args:
            config: Configuration dictionary with 'risk_limits' key

        Returns:
            RiskLimits instance with all limits applied
        """
        if config is None:
            config = {}

        # Build from environment variables
        env_overrides = cls._load_from_env()

        # Merge with config dict
        config_overrides = config.get("risk_limits", {})

        # Combine all overrides
        all_overrides = {**config_overrides, **env_overrides}

        return cls(**all_overrides)

    @classmethod
    def load_from_file(cls, filepath: str) -> "RiskLimits":
        """Load limits from JSON file.

        Args:
            filepath: Path to JSON config file

        Returns:
            RiskLimits instance
        """
        path = Path(filepath)
        if not path.exists():
            return cls()

        with open(path, "r") as f:
            config = json.load(f)

        return cls.load_from_config(config)

    @staticmethod
    def _load_from_env() -> Dict[str, Any]:
        """Load overrides from environment variables.

        Environment variable format:
            RISK_<LIMIT_NAME> = value

        Example:
            RISK_MAX_POSITION_PER_SYMBOL = 0.15
            RISK_MAX_DAILY_TRADES = 30
        """
        overrides = {}

        # Map env vars to dataclass fields
        env_mapping = {
            "RISK_MAX_POSITION_PER_SYMBOL": ("max_position_per_symbol", float),
            "RISK_MAX_POSITION_PER_SECTOR": ("max_position_per_sector", float),
            "RISK_MAX_DAILY_TRADES": ("max_daily_trades", int),
            "RISK_MAX_HOURLY_TRADES": ("max_hourly_trades", int),
            "RISK_MAX_TRADE_SIZE_USD": ("max_trade_size_usd", float),
            "RISK_MAX_PORTFOLIO_EXPOSURE": ("max_portfolio_exposure", float),
            "RISK_MIN_CASH_RESERVE": ("min_cash_reserve", float),
            "RISK_DEFAULT_STOP_LOSS_PCT": ("default_stop_loss_pct", float),
            "RISK_MIN_API_QUOTA_RESERVE": ("min_api_quota_reserve", int),
            "RISK_MAX_LEVERAGE": ("max_leverage", float),
            "RISK_MAX_RISK_SCORE": ("max_risk_score", int),
            "RISK_MIN_CONFIDENCE_THRESHOLD": ("min_confidence_threshold", float),
        }

        for env_var, (field_name, type_func) in env_mapping.items():
            value = os.getenv(env_var)
            if value is not None:
                try:
                    overrides[field_name] = type_func(value)
                except ValueError:
                    pass  # Skip invalid values

        return overrides

    def save_to_file(self, filepath: str):
        """Save current limits to JSON file.

        Args:
            filepath: Path to save JSON config
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump({
                "risk_limits": {
                    "max_position_per_symbol": self.max_position_per_symbol,
                    "max_position_per_sector": self.max_position_per_sector,
                    "max_daily_trades": self.max_daily_trades,
                    "max_hourly_trades": self.max_hourly_trades,
                    "max_trade_size_usd": self.max_trade_size_usd,
                    "max_portfolio_exposure": self.max_portfolio_exposure,
                    "min_cash_reserve": self.min_cash_reserve,
                    "default_stop_loss_pct": self.default_stop_loss_pct,
                    "trailing_stop_enabled": self.trailing_stop_enabled,
                    "trailing_stop_pct": self.trailing_stop_pct,
                    "min_api_quota_reserve": self.min_api_quota_reserve,
                    "max_leverage": self.max_leverage,
                    "max_risk_score": self.max_risk_score,
                    "min_confidence_threshold": self.min_confidence_threshold,
                }
            }, f, indent=2)

    def validate_trade(self, symbol: str, quantity: int, price: float,
                       portfolio_value: float,
                       current_positions: Dict[str, float],
                       sector_mapping: Dict[str, str] = None) -> Dict[str, Any]:
        """Validate a single trade against all limits.

        Args:
            symbol: Ticker symbol
            quantity: Number of shares
            price: Current price per share
            portfolio_value: Total portfolio value
            current_positions: Dict of symbol -> position value
            sector_mapping: Dict of symbol -> sector (optional)

        Returns:
            Dict with 'valid' bool and 'reasons' list
        """
        trade_value = quantity * price
        results = {"valid": True, "reasons": []}

        # Check 1: Position limit per symbol
        current_position = current_positions.get(symbol, 0)
        new_position_pct = (current_position + trade_value) / portfolio_value

        if new_position_pct > self.max_position_per_symbol:
            results["valid"] = False
            results["reasons"].append(
                f"Position limit: {symbol} would be {new_position_pct:.2%} "
                f"(max {self.max_position_per_symbol:.2%})"
            )

        # Check 2: Trade size
        if trade_value > self.max_trade_size_usd:
            results["valid"] = False
            results["reasons"].append(
                f"Trade size: ${trade_value:,.0f} exceeds max ${self.max_trade_size_usd:,.0f}"
            )

        if trade_value < self.min_trade_size_usd:
            results["valid"] = False
            results["reasons"].append(
                f"Trade size: ${trade_value:,.0f} below min ${self.min_trade_size_usd:,.0f}"
            )

        # Check 3: Sector concentration (if mapping provided)
        if sector_mapping:
            sector = sector_mapping.get(symbol, "unknown")
            sector_exposure = sum(
                v for s, v in current_positions.items()
                if sector_mapping.get(s) == sector
            )
            new_sector_pct = (sector_exposure + trade_value) / portfolio_value

            if new_sector_pct > self.max_position_per_sector:
                results["valid"] = False
                results["reasons"].append(
                    f"Sector limit: {sector} would be {new_sector_pct:.2%} "
                    f"(max {self.max_position_per_sector:.2%})"
                )

        # Check 4: Portfolio exposure
        total_exposure = sum(current_positions.values()) / portfolio_value
        new_exposure = total_exposure + trade_value / portfolio_value

        if new_exposure > self.max_portfolio_exposure:
            results["valid"] = False
            results["reasons"].append(
                f"Exposure limit: would be {new_exposure:.2%} "
                f"(max {self.max_portfolio_exposure:.2%})"
            )

        # Check 5: Cash reserve
        cash_after = portfolio_value - (sum(current_positions.values()) + trade_value)
        cash_pct = cash_after / portfolio_value

        if cash_pct < self.min_cash_reserve:
            results["valid"] = False
            results["reasons"].append(
                f"Cash reserve: would be {cash_pct:.2%} "
                f"(min {self.min_cash_reserve:.2%})"
            )

        return results

    def get_stop_loss(self, entry_price: float,
                       current_price: float = None,
                       use_trailing: bool = None) -> Dict[str, float]:
        """Calculate stop loss prices.

        Args:
            entry_price: Initial entry price
            current_price: Current price (for trailing stop)
            use_trailing: Override trailing_stop_enabled

        Returns:
            Dict with 'fixed_stop', 'trailing_stop', 'hard_stop'
        """
        fixed_stop = entry_price * (1 - self.default_stop_loss_pct)
        hard_stop = entry_price * (1 - self.hard_stop_pct)

        trailing = use_trailing if use_trailing is not None else self.trailing_stop_enabled

        if trailing and current_price:
            trailing_stop = current_price * (1 - self.trailing_stop_pct)
        else:
            trailing_stop = fixed_stop

        return {
            "fixed_stop": fixed_stop,
            "trailing_stop": trailing_stop,
            "hard_stop": hard_stop,
            "max_stop": max(trailing_stop, hard_stop),  # The effective stop
        }

    def __repr__(self) -> str:
        return (
            f"RiskLimits("
            f"position={self.max_position_per_symbol:.0%}, "
            f"daily_trades={self.max_daily_trades}, "
            f"exposure={self.max_portfolio_exposure:.0%}, "
            f"stop_loss={self.default_stop_loss_pct:.0%})"
        )


# Default instance for quick access
DEFAULT_LIMITS = RiskLimits()


if __name__ == "__main__":
    # Demo usage
    limits = RiskLimits.load_from_config()
    print(f"Loaded limits: {limits}")

    # Validate a trade
    result = limits.validate_trade(
        symbol="AAPL",
        quantity=100,
        price=180.0,
        portfolio_value=1_000_000,
        current_positions={"AAPL": 50_000, "GOOGL": 100_000},
        sector_mapping={"AAPL": "tech", "GOOGL": "tech"}
    )
    print(f"Trade validation: {result}")

    # Calculate stop loss
    stops = limits.get_stop_loss(entry_price=180.0, current_price=195.0)
    print(f"Stop losses: {stops}")