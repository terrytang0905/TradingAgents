from unittest.mock import ANY, Mock, patch

from tradingagents.api.server import get_config
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


def test_default_config_binds_to_deepseek_v4_flash():
    assert DEFAULT_CONFIG["llm_provider"] == "deepseek"
    assert DEFAULT_CONFIG["deep_think_llm"] == "deepseek-v4-flash"
    assert DEFAULT_CONFIG["quick_think_llm"] == "deepseek-v4-flash"
    assert DEFAULT_CONFIG["backend_url"] == "https://api.deepseek.com"


async def test_api_config_reports_deepseek_provider_and_backend():
    payload = await get_config()

    assert payload["overrides"]["llm_provider"] == "deepseek"
    assert payload["overrides"]["backend_url"] == "https://api.deepseek.com"


def test_deepseek_provider_uses_openai_compatible_client_with_deepseek_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    config = DEFAULT_CONFIG.copy()
    config.update(
        {
            "project_dir": str(tmp_path),
            "data_dir": str(tmp_path / "data"),
            "data_cache_dir": str(tmp_path / "cache"),
            "online_tools": False,
        }
    )

    with (
        patch("tradingagents.graph.trading_graph.set_config"),
        patch("tradingagents.graph.trading_graph.ChatOpenAI") as chat_openai,
        patch("tradingagents.graph.trading_graph.Toolkit"),
        patch("tradingagents.graph.trading_graph.FinancialSituationMemory"),
        patch("tradingagents.graph.trading_graph.ToolNode"),
        patch("tradingagents.graph.trading_graph.GraphSetup") as graph_setup,
        patch("tradingagents.graph.trading_graph.Reflector"),
        patch("tradingagents.graph.trading_graph.SignalProcessor"),
    ):
        graph_setup.return_value.setup_graph.return_value = Mock()

        TradingAgentsGraph(config=config, selected_analysts=[])

    assert chat_openai.call_count == 2
    chat_openai.assert_any_call(
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="test-deepseek-key",
        callbacks=ANY,
    )
