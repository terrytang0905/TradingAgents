"""Signed approvals and a fail-closed boundary for broker order execution."""

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from uuid import uuid4

from tradingagents.default_config import DEFAULT_CONFIG

from .pre_flight_check import PreFlightCheck
from .risk_controller import RiskController
from .risk_limits import RiskLimits as ExecutionRiskLimits

SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
CLIENT_ORDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,48}$")
ALLOWED_ORDER_TYPES = {"market", "limit", "stop", "stop_limit"}
ALLOWED_TIME_IN_FORCE = {"day", "gtc", "opg", "cls", "ioc", "fok"}


class ExecutionDenied(RuntimeError):
    """Raised when an order does not have valid risk approval."""


class ExecutionUnavailable(RuntimeError):
    """Raised when the broker execution dependency fails."""


class ExecutionCircuitOpen(ExecutionUnavailable):
    """Raised while the persistent broker failure circuit is open."""


@dataclass(frozen=True)
class ExecutionApprovalClaims:
    approval_id: str
    symbol: str
    side: str
    trade_date: str
    max_notional: float
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class ExecutionOrder:
    symbol: str
    quantity: int
    side: str
    order_type: str
    trade_date: str
    approval_token: str
    client_order_id: str
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "day"

    def normalized(self) -> "ExecutionOrder":
        return ExecutionOrder(
            symbol=self.symbol.strip().upper(),
            quantity=self.quantity,
            side=self.side.strip().lower(),
            order_type=self.order_type.strip().lower(),
            trade_date=self.trade_date,
            approval_token=self.approval_token,
            client_order_id=self.client_order_id.strip(),
            limit_price=self.limit_price,
            stop_price=self.stop_price,
            time_in_force=self.time_in_force.strip().lower(),
        )

    def fingerprint(self, approval_id: str) -> str:
        payload = {
            "approval_id": approval_id,
            "client_order_id": self.client_order_id,
            "limit_price": self.limit_price,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "side": self.side,
            "stop_price": self.stop_price,
            "symbol": self.symbol,
            "time_in_force": self.time_in_force,
            "trade_date": self.trade_date,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


class ExecutionApprovalService:
    """Issue and verify short-lived HMAC execution capabilities."""

    def __init__(
        self,
        signing_key: str,
        ttl_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ):
        key = signing_key.encode()
        if len(key) < 32:
            raise ExecutionUnavailable("Execution signing key must be at least 32 bytes")
        if ttl_seconds <= 0:
            raise ExecutionUnavailable("Execution approval TTL must be positive")
        self._key = key
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    @classmethod
    def from_environment(
        cls,
        config: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionApprovalService":
        settings = config or {}
        signing_key = os.getenv("TRADINGAGENTS_EXECUTION_SIGNING_KEY", "")
        ttl = int(
            settings.get(
                "execution_approval_ttl_seconds",
                DEFAULT_CONFIG["execution_approval_ttl_seconds"],
            )
        )
        return cls(signing_key, ttl_seconds=ttl)

    def issue(
        self,
        symbol: str,
        side: str,
        trade_date: str,
        max_notional: float,
    ) -> str:
        normalized_symbol = symbol.strip().upper()
        normalized_side = side.strip().lower()
        if not SYMBOL_PATTERN.fullmatch(normalized_symbol):
            raise ExecutionDenied("Invalid approval symbol")
        if normalized_side not in {"buy", "sell"}:
            raise ExecutionDenied("Invalid approval side")
        try:
            date.fromisoformat(trade_date)
        except ValueError as exc:
            raise ExecutionDenied("Invalid approval trade date") from exc
        if not isfinite(max_notional) or max_notional <= 0:
            raise ExecutionDenied("Invalid approval notional")

        issued_at = int(self._clock())
        payload = {
            "approval_id": uuid4().hex,
            "expires_at": issued_at + self._ttl_seconds,
            "issued_at": issued_at,
            "max_notional": float(max_notional),
            "side": normalized_side,
            "symbol": normalized_symbol,
            "trade_date": trade_date,
            "version": 1,
        }
        encoded_payload = _encode_json(payload)
        signature = hmac.new(self._key, encoded_payload.encode(), hashlib.sha256).digest()
        return f"{encoded_payload}.{_encode_bytes(signature)}"

    def verify(self, token: str) -> ExecutionApprovalClaims:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            supplied_signature = _decode_bytes(encoded_signature)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ExecutionDenied("Invalid execution approval token") from exc

        expected_signature = hmac.new(
            self._key,
            encoded_payload.encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ExecutionDenied("Invalid execution approval signature")

        try:
            payload = json.loads(_decode_bytes(encoded_payload))
            if payload.get("version") != 1:
                raise ValueError("unsupported approval version")
            claims = ExecutionApprovalClaims(
                approval_id=str(payload["approval_id"]),
                symbol=str(payload["symbol"]),
                side=str(payload["side"]),
                trade_date=str(payload["trade_date"]),
                max_notional=float(payload["max_notional"]),
                issued_at=int(payload["issued_at"]),
                expires_at=int(payload["expires_at"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ExecutionDenied("Invalid execution approval payload") from exc

        now = int(self._clock())
        if claims.expires_at <= now:
            raise ExecutionDenied("Execution approval has expired")
        if claims.issued_at > now + 5:
            raise ExecutionDenied("Execution approval timestamp is in the future")
        try:
            date.fromisoformat(claims.trade_date)
        except ValueError as exc:
            raise ExecutionDenied("Invalid execution approval payload") from exc
        if (
            not re.fullmatch(r"[0-9a-f]{32}", claims.approval_id)
            or not SYMBOL_PATTERN.fullmatch(claims.symbol)
            or claims.side not in {"buy", "sell"}
            or claims.expires_at <= claims.issued_at
            or not isfinite(claims.max_notional)
            or claims.max_notional <= 0
        ):
            raise ExecutionDenied("Invalid execution approval payload")
        return claims


class ExecutionStateStore:
    """SQLite-backed idempotency and circuit-breaker state."""

    def __init__(
        self,
        path: Path | str,
        failure_threshold: int = 3,
        cooldown_seconds: int = 300,
        clock: Callable[[], float] = time.time,
    ):
        if failure_threshold <= 0 or cooldown_seconds <= 0:
            raise ValueError("Circuit breaker settings must be positive")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    client_order_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    approval_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_breaker (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    failure_count INTEGER NOT NULL,
                    opened_until REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO circuit_breaker(id, failure_count, opened_until)
                VALUES (1, 0, 0)
                """
            )

    def replay(self, client_order_id: str, fingerprint: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT fingerprint, status, response_json FROM executions "
                "WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise ExecutionDenied("Client order id was already used for another order")
        if row["status"] == "pending" or not row["response_json"]:
            raise ExecutionDenied("Order execution is already pending reconciliation")
        result = json.loads(row["response_json"])
        result["idempotent_replay"] = True
        return result

    def assert_circuit_closed(self) -> None:
        now = self.clock()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT failure_count, opened_until FROM circuit_breaker WHERE id = 1"
            ).fetchone()
            if row["opened_until"] > now:
                raise ExecutionCircuitOpen("Broker execution circuit is open")
            if row["opened_until"]:
                connection.execute(
                    "UPDATE circuit_breaker SET failure_count = 0, opened_until = 0 "
                    "WHERE id = 1"
                )

    def reserve(
        self,
        client_order_id: str,
        fingerprint: str,
        approval_id: str,
    ) -> Optional[Dict[str, Any]]:
        now = self.clock()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT fingerprint, status, response_json FROM executions "
                "WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return self.replay(client_order_id, fingerprint)
            connection.execute(
                """
                INSERT INTO executions(
                    client_order_id, fingerprint, approval_id, status,
                    response_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', NULL, ?, ?)
                """,
                (client_order_id, fingerprint, approval_id, now, now),
            )
            connection.commit()
            return None
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ExecutionDenied("Execution approval has already been consumed") from exc
        finally:
            connection.close()

    def complete(self, client_order_id: str, result: Dict[str, Any]) -> None:
        now = self.clock()
        serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                "UPDATE executions SET status = 'succeeded', response_json = ?, "
                "updated_at = ? WHERE client_order_id = ?",
                (serialized, now, client_order_id),
            )
            connection.execute(
                "UPDATE circuit_breaker SET failure_count = 0, opened_until = 0 "
                "WHERE id = 1"
            )

    def fail(self, client_order_id: str) -> None:
        now = self.clock()
        result = {
            "status": "error",
            "message": "Broker order submission failed",
            "idempotent_replay": False,
        }
        serialized = json.dumps(result, sort_keys=True, separators=(",", ":"))
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE executions SET status = 'failed', response_json = ?, "
                "updated_at = ? WHERE client_order_id = ?",
                (serialized, now, client_order_id),
            )
            row = connection.execute(
                "SELECT failure_count FROM circuit_breaker WHERE id = 1"
            ).fetchone()
            failure_count = int(row["failure_count"]) + 1
            opened_until = (
                now + self.cooldown_seconds
                if failure_count >= self.failure_threshold
                else 0
            )
            connection.execute(
                "UPDATE circuit_breaker SET failure_count = ?, opened_until = ? "
                "WHERE id = 1",
                (failure_count, opened_until),
            )
            connection.commit()
        finally:
            connection.close()


class ExecutionGuard:
    """Verify approval, re-run risk checks, and submit at most one broker order."""

    def __init__(
        self,
        approval_service: ExecutionApprovalService,
        state_store: ExecutionStateStore,
        preflight_factory: Callable[[], PreFlightCheck],
        risk_controller: RiskController,
    ):
        self.approval_service = approval_service
        self.state_store = state_store
        self.preflight_factory = preflight_factory
        self.risk_controller = risk_controller

    @classmethod
    def from_environment(
        cls,
        config: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionGuard":
        settings = config or DEFAULT_CONFIG
        store_path = Path(
            os.getenv(
                "TRADINGAGENTS_EXECUTION_DB",
                str(settings.get("execution_db_path", DEFAULT_CONFIG["execution_db_path"])),
            )
        )
        state_store = ExecutionStateStore(
            store_path,
            failure_threshold=int(
                settings.get(
                    "execution_circuit_failure_threshold",
                    DEFAULT_CONFIG["execution_circuit_failure_threshold"],
                )
            ),
            cooldown_seconds=int(
                settings.get(
                    "execution_circuit_cooldown_seconds",
                    DEFAULT_CONFIG["execution_circuit_cooldown_seconds"],
                )
            ),
        )
        return cls(
            approval_service=ExecutionApprovalService.from_environment(settings),
            state_store=state_store,
            preflight_factory=lambda: PreFlightCheck(config=settings),
            risk_controller=RiskController(
                execution_limits=ExecutionRiskLimits.load_from_config(settings)
            ),
        )

    def execute(
        self,
        requested_order: ExecutionOrder,
        price_provider: Callable[[str], float],
        submitter: Callable[[ExecutionOrder], Dict[str, Any]],
    ) -> Dict[str, Any]:
        order = self._validate_order(requested_order.normalized())
        claims = self.approval_service.verify(order.approval_token)
        self._match_approval(order, claims)
        fingerprint = order.fingerprint(claims.approval_id)

        replay = self.state_store.replay(order.client_order_id, fingerprint)
        if replay is not None:
            return replay
        self.state_store.assert_circuit_closed()

        checker = self.preflight_factory()
        preflight_result = checker.run(order.symbol, order.trade_date, action=order.side)
        if not preflight_result["passed"]:
            raise ExecutionDenied(
                f"Pre-flight risk check failed: {preflight_result['blocked_reason']}"
            )
        broker_snapshot = checker.snapshot
        if broker_snapshot is None:
            raise ExecutionDenied("Broker risk snapshot is unavailable")

        try:
            latest_price = float(price_provider(order.symbol))
        except Exception as exc:
            raise ExecutionUnavailable("Broker price lookup failed") from exc
        if not isfinite(latest_price) or latest_price <= 0:
            raise ExecutionUnavailable("Broker price lookup returned invalid data")
        execution_price = self._execution_price(order, latest_price)
        reasons = self.risk_controller.validate_execution_order(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            snapshot=broker_snapshot,
            approved_max_notional=claims.max_notional,
        )
        if reasons:
            raise ExecutionDenied("; ".join(reasons))

        replay = self.state_store.reserve(
            order.client_order_id,
            fingerprint,
            claims.approval_id,
        )
        if replay is not None:
            return replay

        try:
            broker_order = submitter(order)
            if not isinstance(broker_order, dict) or not broker_order.get("id"):
                raise RuntimeError("Broker returned an invalid order response")
        except Exception as exc:
            self.state_store.fail(order.client_order_id)
            raise ExecutionUnavailable("Broker order submission failed") from exc

        result = {
            "status": "success",
            "order": broker_order,
            "idempotent_replay": False,
        }
        self.state_store.complete(order.client_order_id, result)
        return result

    def _validate_order(self, order: ExecutionOrder) -> ExecutionOrder:
        if not SYMBOL_PATTERN.fullmatch(order.symbol):
            raise ExecutionDenied("Invalid order symbol")
        if isinstance(order.quantity, bool) or not isinstance(order.quantity, int):
            raise ExecutionDenied("Order quantity must be an integer")
        if order.quantity <= 0:
            raise ExecutionDenied("Order quantity must be positive")
        if order.side not in {"buy", "sell"}:
            raise ExecutionDenied("Invalid order side")
        if order.order_type not in ALLOWED_ORDER_TYPES:
            raise ExecutionDenied("Invalid order type")
        if order.time_in_force not in ALLOWED_TIME_IN_FORCE:
            raise ExecutionDenied("Invalid time in force")
        if not CLIENT_ORDER_ID_PATTERN.fullmatch(order.client_order_id):
            raise ExecutionDenied("Invalid client order id")
        try:
            date.fromisoformat(order.trade_date)
        except ValueError as exc:
            raise ExecutionDenied("Invalid order trade date") from exc
        if order.order_type in {"limit", "stop_limit"}:
            _positive_price(order.limit_price, "limit price")
        if order.order_type in {"stop", "stop_limit"}:
            _positive_price(order.stop_price, "stop price")
        return order

    @staticmethod
    def _match_approval(
        order: ExecutionOrder,
        claims: ExecutionApprovalClaims,
    ) -> None:
        if (
            order.symbol != claims.symbol
            or order.side != claims.side
            or order.trade_date != claims.trade_date
        ):
            raise ExecutionDenied("Order does not match the analysis approval")

    @staticmethod
    def _execution_price(order: ExecutionOrder, latest_price: float) -> float:
        if order.order_type in {"limit", "stop_limit"}:
            return float(order.limit_price)
        if order.order_type == "stop":
            return max(latest_price, float(order.stop_price))
        return latest_price


class ExecutionApprovalIssuer:
    """Create a signed broker capability from a completed graph decision."""

    def __init__(
        self,
        approval_service: ExecutionApprovalService,
        config: Optional[Dict[str, Any]] = None,
        preflight_factory: Optional[Callable[[], PreFlightCheck]] = None,
    ):
        self.approval_service = approval_service
        self.config = config or DEFAULT_CONFIG
        self.preflight_factory = preflight_factory or (
            lambda: PreFlightCheck(config=self.config)
        )

    @classmethod
    def from_environment(
        cls,
        config: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionApprovalIssuer":
        settings = config or DEFAULT_CONFIG
        return cls(ExecutionApprovalService.from_environment(settings), settings)

    def issue(self, action: str, symbol: str, trade_date: str) -> Optional[str]:
        normalized_action = action.strip().upper()
        if normalized_action == "HOLD":
            return None
        if normalized_action not in {"BUY", "SELL"}:
            raise ExecutionDenied("Analysis did not produce an executable action")

        checker = self.preflight_factory()
        result = checker.run(symbol, trade_date, action=normalized_action.lower())
        if not result["passed"]:
            raise ExecutionDenied(f"Execution approval denied: {result['blocked_reason']}")
        broker_snapshot = checker.snapshot
        if broker_snapshot is None:
            raise ExecutionDenied("Execution approval has no broker snapshot")

        controller = RiskController(execution_limits=checker.limits)
        max_notional = controller.max_approved_notional(
            normalized_action,
            symbol,
            broker_snapshot,
        )
        if max_notional <= 0 or (
            normalized_action == "BUY"
            and max_notional < checker.limits.min_trade_size_usd
        ):
            raise ExecutionDenied("No executable notional remains after risk limits")
        return self.approval_service.issue(
            symbol=symbol,
            side=normalized_action.lower(),
            trade_date=trade_date,
            max_notional=max_notional,
        )


def _positive_price(value: Optional[float], name: str) -> float:
    try:
        price = float(value)
    except (TypeError, ValueError) as exc:
        raise ExecutionDenied(f"Invalid {name}") from exc
    if not isfinite(price) or price <= 0:
        raise ExecutionDenied(f"Invalid {name}")
    return price


def _encode_json(payload: Dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _encode_bytes(serialized)


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
