# TradingAgents Dataflows Layer

> 数据API调用、缓存策略、错误处理约定

## API Overview

| API | Purpose | Rate Limit | Online Tool | Offline Tool |
|-----|---------|------------|-------------|--------------|
| YFinance | OHLCV价格数据 | 2000 RPM | `get_YFin_data_online` | `get_YFin_data` |
| Stockstats | 技术指标计算 | — | `get_stockstats_indicators_report_online` | `get_stockstats_indicators_report` |
| FinnHub | 公司新闻 | 60 RPM | `get_finnhub_news` | Cached |
| Reddit | 社交情绪 | — | `get_reddit_stock_info` | Cached |
| Google News | 全球新闻 | — | `get_google_news` | — |
| OpenAI Web Search | 实时检索 | 100 RPM | `get_*_openai` | — |
| SimFin | 财务报表 | — | — | `get_simfin_*` |

## Online vs Offline Mode

```python
# config["online_tools"] = True  → 实时API调用
# config["online_tools"] = False → 使用本地TradingDB缓存

# Offline数据范围
DATA_DIR = "/path/to/TradingDB"
# 价格数据: 2015-01-01 to 2025-03-25
# FinnHub新闻: Cached JSON files
# Reddit数据: Cached JSON files
# SimFin财务: CSV files
```

## Adding New Data Source

### Step 1: Create Utility File

```python
# tradingagents/dataflows/<new>_utils.py

import requests
from typing import Annotated

def get_<new>_data(
    ticker: Annotated[str, "ticker symbol"],
    curr_date: Annotated[str, "current date YYYY-mm-dd"],
    look_back_days: Annotated[int, "days to look back"] = 7,
) -> str:
    """
    Retrieve <new> data for a company.

    Returns formatted string for LLM consumption.
    """
    # API call implementation
    ...

    # Return formatted string
    return f"## <New> Data for {ticker}:\n{formatted_data}"
```

### Step 2: Register in `interface.py`

```python
# tradingagents/dataflows/interface.py

from .<new>_utils import get_<new>_data

# Add export
__all__ = [..., "get_<new>_data"]
```

### Step 3: Add to Toolkit

```python
# tradingagents/agents/utils/agent_utils.py

@staticmethod
@tool
def get_<new>_data(
    ticker: Annotated[str, "ticker"],
    curr_date: Annotated[str, "date YYYY-mm-dd"],
) -> str:
    """Retrieve <new> data via toolkit."""
    return interface.get_<new>_data(ticker, curr_date)
```

### Step 4: Add to Tool Node

```python
# tradingagents/graph/trading_graph.py

tool_nodes["<analyst>"] = ToolNode([
    ...,
    self.toolkit.get_<new>_data,
])
```

## Error Handling Pattern

```python
# Standard error handling for API calls
try:
    data = api_call(params)
    if not data or len(data) == 0:
        return ""  # Return empty string, not error message
    return format_data(data)
except requests.exceptions.Timeout:
    print(f"Warning: {api_name} timeout, returning cached data")
    return get_cached_data(params)
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 429:  # Rate limit
        print(f"Warning: {api_name} rate limited, waiting...")
        time.sleep(60)
        return retry_call(params)
    return ""
```

## Data Formatting Standard

所有数据API输出遵循统一格式：

```markdown
## <Data Source> for <ticker>, from <start> to <end>:

### <Section 1 Title>
<data content>

### <Section 2 Title>
<data content>

<Interpretation notes if applicable>
```

**示例**：

```markdown
## NVDA News from FinnHub, from 2024-05-03 to 2024-05-10:

### NVIDIA Announces New AI Chip (2024-05-08)
NVIDIA unveiled its next-generation AI accelerator...

### Analyst Upgrade (2024-05-06)
Morgan Stanley raised price target to $1,200...
```

## Caching Strategy

| Data Type | Cache Duration | Storage | Refresh Trigger |
|-----------|---------------|---------|-----------------|
| Price Data | Daily | CSV | `online_tools=True` |
| News Data | Session | JSON | `look_back_days` change |
| Financials | Quarterly | CSV | `curr_date` > last update |
| Sentiment | Hourly | JSON | `online_tools=True` |

## Rate Limit Protection

```python
# Implemented in tradingagents/monitoring/rate_limiter.py

LIMITS = {
    "openai": {"rpm": 500, "tpm": 200000},
    "finnhub": {"rpm": 60},
    "yfinance": {"rpm": 2000},
    "google_news": {"rpm": 100},
}

# Automatic logging via Hooks
# Warning at 90% threshold
# Block at 100% threshold (Hook enforced)
```

## Look-back Days Defaults

| Analyst | Default Look-back | Reason |
|---------|------------------|--------|
| Market | 30 days | Technical indicator window |
| Social | 7 days | Sentiment decay |
| News | 7 days | News relevance window |
| Fundamentals | 30 days | Insider data window |

## Data Quality Checks

```python
# Before returning data to LLM, validate:

def validate_data(data: str) -> str:
    if not data or data.strip() == "":
        return "No data available for this period."

    # Check for API error messages
    if "error" in data.lower() or "failed" in data.lower():
        return ""

    # Check minimum content length
    if len(data) < 100:
        return ""

    return data
```

## Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| Date format mismatch | API returns empty | Use `YYYY-mm-dd` strictly |
| Rate limit exceeded | 429 errors | Hook自动保护，等待60s |
| Offline data outdated | Missing recent data | Use `online_tools=True` for live |
| Empty ticker | KeyError | Validate ticker before API call |
| Weekend/holiday dates | Empty price data | Check trading calendar |

## Testing Data APIs

```python
# tests/test_dataflows.py

def test_yfin_data_online():
    from tradingagents.dataflows.interface import get_YFin_data_online
    result = get_YFin_data_online("AAPL", "2024-01-01", "2024-01-10")
    assert "AAPL" in result
    assert len(result) > 100

def test_finnhub_news_format():
    from tradingagents.dataflows.interface import get_finnhub_news
    result = get_finnhub_news("NVDA", "2024-05-10", 7)
    assert "##" in result  # Markdown header format
```