"""Regression tests for the controlled broker execution boundary."""

from datetime import datetime, timezone

import pytest

from tradingagents.risk_management.execution_control import (
    ExecutionApprovalIssuer,
    ExecutionApprovalService,
    ExecutionCircuitOpen,
    ExecutionDenied,
    ExecutionGuard,
    ExecutionOrder,
    ExecutionStateStore,
    ExecutionUnavailable,
)
from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_controller import RiskController
from tradingagents.risk_management.risk_data import RiskSnapshot
from tradingagents.risk_management.risk_limits import RiskLimits


def snapshot(**overrides) -> RiskSnapshot:
    values = {
        "source": "test-broker",
        "captured_at": datetime.now(timezone.utc),
        "portfolio_value": 100_000,
        "cash": 70_000,
        "positions": {"AAPL": 5_000},
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


class StaticProvider:
    def __init__(self, broker_snapshot: RiskSnapshot):
        self.snapshot = broker_snapshot

    def capture(self, ticker: str, trade_date: str) -> RiskSnapshot:
        return self.snapshot


class StaticQuota:
    def remaining(self) -> int:
        return 500


def preflight(broker_snapshot: RiskSnapshot) -> PreFlightCheck:
    return PreFlightCheck(
        config={"enforce_trading_hours": False},
        data_provider=StaticProvider(broker_snapshot),
        quota_provider=StaticQuota(),
    )


def order(token: str, client_order_id: str = "analysis-1-order-1", **overrides):
    values = {
        "symbol": "AAPL",
        "quantity": 10,
        "side": "buy",
        "order_type": "market",
        "trade_date": datetime.now().date().isoformat(),
        "approval_token": token,
        "client_order_id": client_order_id,
        "time_in_force": "day",
    }
    values.update(overrides)
    return ExecutionOrder(**values)


def approval(service: ExecutionApprovalService, **overrides) -> str:
    values = {
        "symbol": "AAPL",
        "side": "buy",
        "trade_date": datetime.now().date().isoformat(),
        "max_notional": 1_000,
    }
    values.update(overrides)
    return service.issue(**values)


def guard(tmp_path, broker_snapshot=None, failure_threshold=3):
    service = ExecutionApprovalService("x" * 32, ttl_seconds=60)
    store = ExecutionStateStore(
        tmp_path / "execution.sqlite3",
        failure_threshold=failure_threshold,
        cooldown_seconds=60,
    )
    current = broker_snapshot or snapshot()
    execution_guard = ExecutionGuard(
        approval_service=service,
        state_store=store,
        preflight_factory=lambda: preflight(current),
        risk_controller=RiskController(execution_limits=RiskLimits()),
    )
    return service, execution_guard


def tampered(token: str) -> str:
    payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    return f"{payload[:-1]}{replacement}.{signature}"


def test_execution_approval_rejects_tampering_and_expiry():
    now = [1_000.0]
    service = ExecutionApprovalService(
        "x" * 32,
        ttl_seconds=30,
        clock=lambda: now[0],
    )
    token = service.issue("AAPL", "buy", "2025-01-02", 1_000)

    with pytest.raises(ExecutionDenied, match="signature"):
        service.verify(tampered(token))

    now[0] = 1_031.0
    with pytest.raises(ExecutionDenied, match="expired"):
        service.verify(token)


def test_guard_submits_once_and_replays_cached_result(tmp_path):
    service, execution_guard = guard(tmp_path)
    token = approval(service)
    submissions = []

    def submit(execution_order):
        submissions.append(execution_order)
        return {"id": "broker-order-1", "status": "accepted"}

    first = execution_guard.execute(order(token), lambda symbol: 100.0, submit)
    second = execution_guard.execute(order(token), lambda symbol: 100.0, submit)

    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert second["order"]["id"] == "broker-order-1"
    assert len(submissions) == 1


def test_guard_rejects_order_that_does_not_match_analysis_approval(tmp_path):
    service, execution_guard = guard(tmp_path)
    token = approval(service)

    with pytest.raises(ExecutionDenied, match="does not match"):
        execution_guard.execute(
            order(token, side="sell"),
            lambda symbol: 100.0,
            lambda request: pytest.fail("broker must not be called"),
        )


def test_guard_rechecks_real_position_and_cash_limits_before_submission(tmp_path):
    broker_snapshot = snapshot(positions={"AAPL": 6_000}, cash=70_000)
    service, execution_guard = guard(tmp_path, broker_snapshot=broker_snapshot)
    token = approval(service, max_notional=6_000)

    with pytest.raises(ExecutionDenied, match="position limit"):
        execution_guard.execute(
            order(token, quantity=50),
            lambda symbol: 100.0,
            lambda request: pytest.fail("broker must not be called"),
        )


def test_guard_allows_risk_reducing_sell_at_position_limit(tmp_path):
    broker_snapshot = snapshot(
        positions={"AAPL": 10_000},
        position_quantities={"AAPL": 100},
        cash=10_000,
    )
    service, execution_guard = guard(tmp_path, broker_snapshot=broker_snapshot)
    token = approval(service, side="sell", max_notional=10_000)

    result = execution_guard.execute(
        order(token, side="sell", quantity=100),
        lambda symbol: 100.0,
        lambda request: {"id": "exit-order", "status": "accepted"},
    )

    assert result["order"]["id"] == "exit-order"


def test_guard_opens_circuit_after_repeated_broker_failures(tmp_path):
    service, execution_guard = guard(tmp_path, failure_threshold=2)

    def fail(_request):
        raise RuntimeError("broker unavailable with secret details")

    for index in range(2):
        token = approval(service)
        with pytest.raises(ExecutionUnavailable, match="Broker order submission failed"):
            execution_guard.execute(
                order(token, client_order_id=f"failed-{index}"),
                lambda symbol: 100.0,
                fail,
            )

    token = approval(service)
    with pytest.raises(ExecutionCircuitOpen):
        execution_guard.execute(
            order(token, client_order_id="blocked-by-circuit"),
            lambda symbol: 100.0,
            fail,
        )


def test_risk_controller_calculates_safe_analysis_approval_from_snapshot():
    controller = RiskController(execution_limits=RiskLimits())

    buy_limit = controller.max_approved_notional("BUY", "AAPL", snapshot())
    sell_limit = controller.max_approved_notional("SELL", "AAPL", snapshot())

    assert buy_limit == 5_000
    assert sell_limit == 5_000


def test_approval_issuer_allows_a_small_risk_reducing_exit():
    broker_snapshot = snapshot(
        positions={"AAPL": 500},
        position_quantities={"AAPL": 5},
    )
    service = ExecutionApprovalService("x" * 32, ttl_seconds=60)
    issuer = ExecutionApprovalIssuer(
        service,
        config={"enforce_trading_hours": False},
        preflight_factory=lambda: preflight(broker_snapshot),
    )

    token = issuer.issue("SELL", "AAPL", datetime.now().date().isoformat())

    assert token is not None
    assert service.verify(token).max_notional == 500
