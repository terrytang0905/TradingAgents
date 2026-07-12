"""Polygon Data MCP Server.

Provides real-time and historical market data via Polygon.io API.
"""

import json
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from mcp.server import Server
from mcp.types import Tool, TextContent
import requests


class PolygonDataMCP(Server):
    """MCP server for Polygon.io data API.

    Provides tools for:
    - Real-time quotes
    - Historical aggregates
    - Company details
    - News retrieval
    """

    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str):
        """Initialize Polygon data connection.

        Args:
            api_key: Polygon.io API key
        """
        self.api_key = api_key
        super().__init__("polygon-data")

    def _make_request(self, endpoint: str, params: Dict = None) -> Dict:
        """Make API request to Polygon.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            JSON response
        """
        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params["apiKey"] = self.api_key

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    @Tool
    async def get_quote(self, symbol: str) -> TextContent:
        """Get real-time quote for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Current quote with bid/ask/last price
        """
        try:
            data = self._make_request(f"/v2/last/nbbo/{symbol}")

            if "results" not in data or not data["results"]:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"No quote data for {symbol}"
                    })
                )

            result = data["results"][0]

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "quote": {
                        "symbol": symbol,
                        "bid_price": float(result.get("bid_price", 0)),
                        "bid_size": result.get("bid_size", 0),
                        "ask_price": float(result.get("ask_price", 0)),
                        "ask_size": result.get("ask_size", 0),
                        "last_price": float(result.get("last_price", 0)),
                        "timestamp": result.get("timestamp", ""),
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    @Tool
    async def get_aggregates(
        self,
        symbol: str,
        multiplier: int = 1,
        timespan: str = "day",  # minute, hour, day, week, month
        from_date: str = None,
        to_date: str = None
    ) -> TextContent:
        """Get historical aggregate data (OHLCV).

        Args:
            symbol: Ticker symbol
            multiplier: Size of the timespan multiplier
            timespan: Size of the time window
            from_date: Start date YYYY-MM-DD
            to_date: End date YYYY-MM-DD

        Returns:
            Historical OHLCV data
        """
        try:
            # Default to last 30 days if not specified
            if not from_date:
                from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            if not to_date:
                to_date = datetime.now().strftime("%Y-%m-%d")

            endpoint = f"/v2/aggs/ticker/{symbol}/range/{multiplier}/{timespan}/{from_date}/{to_date}"
            data = self._make_request(endpoint)

            if "results" not in data:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": "No aggregate data returned"
                    })
                )

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "aggregates": {
                        "symbol": symbol,
                        "query": {
                            "from": from_date,
                            "to": to_date,
                            "timespan": timespan,
                            "multiplier": multiplier
                        },
                        "resultsCount": data.get("resultsCount", 0),
                        "data": [
                            {
                                "t": r.get("t"),  # timestamp
                                "o": float(r.get("o", 0)),  # open
                                "h": float(r.get("h", 0)),  # high
                                "l": float(r.get("l", 0)),  # low
                                "c": float(r.get("c", 0)),  # close
                                "v": r.get("v", 0),  # volume
                                "vw": float(r.get("vw", 0)) if r.get("vw") else None,  # volume weighted
                            }
                            for r in data["results"]
                        ]
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    @Tool
    async def get_previous_close(self, symbol: str) -> TextContent:
        """Get previous day's close data.

        Args:
            symbol: Ticker symbol

        Returns:
            Previous close OHLCV data
        """
        try:
            data = self._make_request(f"/v2/aggs/ticker/{symbol}/prev")

            if "results" not in data or not data["results"]:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"No previous close data for {symbol}"
                    })
                )

            result = data["results"][0]

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "previous_close": {
                        "symbol": symbol,
                        "open": float(result.get("o", 0)),
                        "high": float(result.get("h", 0)),
                        "low": float(result.get("l", 0)),
                        "close": float(result.get("c", 0)),
                        "volume": result.get("v", 0),
                        "volume_weighted": float(result.get("vw", 0)) if result.get("vw") else None,
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    @Tool
    async def get_company_details(self, symbol: str) -> TextContent:
        """Get company details.

        Args:
            symbol: Ticker symbol

        Returns:
            Company information: name, description, industry, etc.
        """
        try:
            data = self._make_request(f"/v3/reference/tickers/{symbol}")

            if "results" not in data:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"No company data for {symbol}"
                    })
                )

            result = data["results"]

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "company": {
                        "ticker": result.get("ticker"),
                        "name": result.get("name"),
                        "description": result.get("description"),
                        "market": result.get("market"),
                        "locale": result.get("locale"),
                        "type": result.get("type"),
                        "currency_name": result.get("currency_name"),
                        "cik": result.get("cik"),
                        "composite_figi": result.get("composite_figi"),
                        "share_class_figi": result.get("share_class_figi"),
                        "market_cap": result.get("market_cap"),
                        "weighted_shares_outstanding": result.get("weighted_shares_outstanding"),
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    @Tool
    async def get_news(
        self,
        symbol: str = None,
        published_utc_gte: str = None,
        published_utc_lte: str = None,
        limit: int = 10
    ) -> TextContent:
        """Get news articles.

        Args:
            symbol: Ticker symbol (optional, for general news)
            published_utc_gte: Published after this date
            published_utc_lte: Published before this date
            limit: Maximum number of articles

        Returns:
            List of news articles
        """
        try:
            params = {"limit": limit}

            if symbol:
                params["ticker"] = symbol.upper()

            if published_utc_gte:
                params["published_utc.gte"] = published_utc_gte

            if published_utc_lte:
                params["published_utc.lte"] = published_utc_lte

            data = self._make_request("/v2/reference/news", params)

            if "results" not in data:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": "No news data returned"
                    })
                )

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "news": {
                        "query": {
                            "symbol": symbol,
                            "from": published_utc_gte,
                            "to": published_utc_lte,
                        },
                        "count": len(data["results"]),
                        "articles": [
                            {
                                "id": a.get("id"),
                                "title": a.get("title"),
                                "author": a.get("author"),
                                "published_utc": a.get("published_utc"),
                                "article_url": a.get("article_url"),
                                "image_url": a.get("image_url"),
                                "description": a.get("description"),
                                "tickers": a.get("tickers", []),
                                "keywords": a.get("keywords", []),
                            }
                            for a in data["results"]
                        ]
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )

    @Tool
    async def get_snapshot(self, symbol: str) -> TextContent:
        """Get market snapshot for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Current snapshot: quote, minute bar, prev day bar
        """
        try:
            data = self._make_request(f"/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}")

            if "ticker" not in data:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": f"No snapshot data for {symbol}"
                    })
                )

            ticker = data["ticker"]

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "snapshot": {
                        "symbol": ticker.get("ticker"),
                        "name": ticker.get("name"),
                        "market_cap": ticker.get("market_cap"),
                        "price": float(ticker.get("last_trade", {}).get("p", 0)) if ticker.get("last_trade") else None,
                        "change": ticker.get("todaysChange"),
                        "change_pct": ticker.get("todaysChangePerc"),
                        "volume": ticker.get("day", {}).get("v") if ticker.get("day") else None,
                    }
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e),
                    "symbol": symbol
                })
            )

    @Tool
    async def search_tickers(
        self,
        query: str,
        market: str = "stocks",
        active: bool = True,
        limit: int = 10
    ) -> TextContent:
        """Search for tickers.

        Args:
            query: Search query
            market: Market type (stocks, crypto, fx)
            active: Only active tickers
            limit: Maximum results

        Returns:
            List of matching tickers
        """
        try:
            params = {
                "search": query,
                "market": market,
                "active": str(active).lower(),
                "limit": limit
            }

            data = self._make_request("/v3/reference/tickers", params)

            if "results" not in data:
                return TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "error",
                        "message": "No tickers found"
                    })
                )

            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "tickers": [
                        {
                            "ticker": t.get("ticker"),
                            "name": t.get("name"),
                            "market": t.get("market"),
                            "locale": t.get("locale"),
                            "type": t.get("type"),
                            "active": t.get("active"),
                        }
                        for t in data["results"]
                    ],
                    "count": len(data["results"])
                }, indent=2)
            )
        except Exception as e:
            return TextContent(
                type="text",
                text=json.dumps({
                    "status": "error",
                    "message": str(e)
                })
            )


def run_server():
    """Run the MCP server."""
    import os

    api_key = os.getenv("POLYGON_API_KEY")

    if not api_key:
        raise ValueError("POLYGON_API_KEY required")

    server = PolygonDataMCP(api_key)
    server.run()


if __name__ == "__main__":
    run_server()
