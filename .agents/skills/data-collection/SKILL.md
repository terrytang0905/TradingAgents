---
name: data-collection
description: 配置和管理数据源API，支持YFinance/FinnHub/Reddit/OpenAI Web Search等多源采集。
origin: custom
---

# Data Collection Skill

> 数据源配置与API调用管理

## When to Activate

- 用户提及"数据源"、"API配置"、"采集数据"
- 需要添加新的数据源
- 配置Online/Offline数据模式

手动调用：`/data-collection` 或 `/数据采集`

---

## Supported Data Sources

| 数据源 | 类型 | 内容 | Rate Limit |
|--------|------|------|------------|
| **YFinance** | API | OHLCV价格数据 | 2000 RPM |
| **FinnHub** | API | 公司新闻、Insider数据 | 60 RPM |
| **Reddit** | Cache | r/wallstreetbets帖子 | 60 RPM |
| **Google News** | API | 全球新闻搜索 | 100 RPM |
| **OpenAI Web Search** | API | 实时情绪/基本面检索 | 100 RPM |
| **SimFin** | Cache | 财务报表 (CSV) | — |
| **Polygon** | API | 实时行情 (MCP) | 5 RPM |

---

## Online vs Offline Mode

```python
# config["online_tools"] = True  → 实时API调用
# config["online_tools"] = False → 使用TradingDB缓存

# Offline数据范围 (默认)
DATA_DIR = "/path/to/TradingDB"
- 价格数据: 2015-01-01 ~ 2025-03-25
- FinnHub新闻: Cached JSON
- Reddit数据: Cached JSON
- SimFin财务: CSV files

# 使用场景
online_tools=True:
  - 实时交易决策
  - 最新新闻采集
  - 实盘部署

online_tools=False:
  - 历史回测
  - 开发测试 (省钱)
  - 研究分析
```

---

## API Key Configuration

```bash
# Required API Keys
export FINNHUB_API_KEY=your_key        # FinnHub (free tier available)
export OPENAI_API_KEY=your_key         # OpenAI (required for LLM + Web Search)
export POLYGON_API_KEY=your_key        # Polygon (optional, MCP)
export ALPACA_API_KEY=your_key         # Alpaca (optional, broker)
export ALPACA_SECRET_KEY=your_key      # Alpaca

# Optional
export REDDIT_CLIENT_ID=your_id        # Reddit API (optional)
export REDDIT_CLIENT_SECRET=your_secret
```

---

## Adding New Data Source

### Step 1: Create Utils File

```python
# tradingagents/dataflows/<new>_utils.py

def get_<new>_data(ticker: str, curr_date: str, look_back_days: int = 7) -> str:
    """Retrieve <new> data for ticker."""

    # API call implementation
    response = requests.get(url, params=params)
    data = response.json()

    # Format for LLM consumption
    return format_as_markdown(data)
```

### Step 2: Register in interface.py

```python
# tradingagents/dataflows/interface.py
from .<new>_utils import get_<new>_data
```

### Step 3: Add to Toolkit

```python
# tradingagents/agents/utils/agent_utils.py

@staticmethod
@tool
def get_<new>_data(ticker: str, curr_date: str) -> str:
    """Retrieve <new> data."""
    return interface.get_<new>_data(ticker, curr_date)
```

### Step 4: Register Rate Limit

```python
# tradingagents/monitoring/rate_limiter.py

LIMITS["<new>"] = RateLimitConfig(rpm=100)
```

---

## Data Formatting Standard

所有数据输出必须格式化：

```markdown
## <Source> Data for <ticker>, from <start> to <end>:

### <Section>
<data content>

### <Section>
<data content>

<Interpretation notes>
```

---

## Rate Limit Protection

```python
# Before API call
from tradingagents.monitoring.rate_limiter import RateLimiter

if not RateLimiter.check_can_call("finnhub"):
    RateLimiter.wait_if_needed("finnhub")

# After API call
RateLimiter.log_call("finnhub")
```

---

## Cache Strategy

| 数据类型 | 缓存时长 | 刷新条件 |
|----------|---------|---------|
| 价格数据 | Daily | `online_tools=True` |
| 新闻数据 | Session | `look_back_days`变化 |
| 财务数据 | Quarterly | `curr_date`超过上次更新 |
| 情绪数据 | Hourly | `online_tools=True` |

---

## See Detailed References

- API Endpoints: `@references/api_endpoints.md`
- Cache Strategy: `@references/cache_strategy.md`
- Error Handling: `@references/error_handling.md`