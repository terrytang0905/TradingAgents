"""Security regression tests for the TradingAgents REST API."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from tradingagents.api import server


def test_health_endpoint_remains_public_when_authentication_is_unconfigured(
    monkeypatch,
):
    monkeypatch.delenv("TRADINGAGENTS_API_KEY", raising=False)

    response = TestClient(server.app).get("/health")

    assert response.status_code == 200


def test_api_routes_fail_closed_when_authentication_is_unconfigured(monkeypatch):
    monkeypatch.delenv("TRADINGAGENTS_API_KEY", raising=False)

    response = TestClient(server.app).get("/api/config")

    assert response.status_code == 503
    assert response.json() == {"detail": "API authentication is not configured"}


def test_api_routes_require_a_valid_bearer_token(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")
    client = TestClient(server.app)

    missing = client.get("/api/config")
    invalid = client.get(
        "/api/config", headers={"Authorization": "Bearer wrong-secret"}
    )
    valid = client.get(
        "/api/config", headers={"Authorization": "Bearer server-test-secret"}
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert valid.status_code == 200


def test_api_routes_accept_x_api_key_header(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")

    response = TestClient(server.app).get(
        "/api/config", headers={"X-API-Key": "server-test-secret"}
    )

    assert response.status_code == 200


def test_trade_request_rejects_server_owned_model_configuration():
    with pytest.raises(ValidationError):
        server.TradeRequest(
            ticker="AAPL",
            trade_date="2025-01-02",
            config={"backend_url": "https://attacker.invalid"},
        )


def test_get_trading_agents_rejects_unsafe_mapping_before_initialization():
    with patch.object(server, "TradingAgentsGraph") as graph:
        with pytest.raises(ValueError, match="Unsupported analysis config keys"):
            server.get_trading_agents(
                {"backend_url": "https://attacker.invalid", "online_tools": True}
            )

    graph.assert_not_called()


def test_config_endpoint_rejects_server_owned_model_configuration(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")

    with patch.object(server, "get_trading_agents") as get_trading_agents:
        response = TestClient(server.app).post(
            "/api/config",
            headers={"Authorization": "Bearer server-test-secret"},
            json={"backend_url": "https://attacker.invalid"},
        )

    assert response.status_code == 422
    get_trading_agents.assert_not_called()


def test_safe_analysis_configuration_is_accepted():
    request = server.TradeRequest(
        ticker="AAPL",
        trade_date="2025-01-02",
        config={
            "max_debate_rounds": 2,
            "max_risk_discuss_rounds": 2,
            "online_tools": False,
        },
    )

    assert request.config is not None
    assert request.config.max_debate_rounds == 2
    assert request.config.online_tools is False


def test_cors_rejects_untrusted_origins_by_default(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")
    response = TestClient(server.app).options(
        "/api/config",
        headers={
            "Origin": "https://attacker.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_allows_local_frontend_by_default(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")
    response = TestClient(server.app).options(
        "/api/config",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_configuration_rejects_wildcard(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_CORS_ORIGINS", "*")

    with pytest.raises(RuntimeError, match="must not contain"):
        server._cors_origins()


def test_authenticated_analysis_returns_controlled_execution_approval(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_API_KEY", "server-test-secret")
    passed = {"passed": True, "blocked_reason": None, "checks": []}
    state = {
        "execution_approval": "signed-token",
        "execution_approval_status": {"status": "approved"},
    }

    with (
        patch.object(server, "PreFlightCheck") as preflight_cls,
        patch.object(server, "get_trading_agents") as get_trading_agents,
    ):
        preflight_cls.return_value.run.return_value = passed
        get_trading_agents.return_value.propagate.return_value = (state, "BUY")
        response = TestClient(server.app).post(
            "/api/analyze",
            headers={"Authorization": "Bearer server-test-secret"},
            json={"ticker": "AAPL", "trade_date": "2025-01-02"},
        )

    assert response.status_code == 200
    assert response.json()["execution_approval"] == "signed-token"
    assert response.json()["execution_approval_status"] == {"status": "approved"}
