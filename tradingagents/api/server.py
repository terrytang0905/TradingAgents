"""
TradingAgents REST API Server.

Provides HTTP endpoints for trading analysis.
Run: python -m tradingagents.api.server
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.risk_management.pre_flight_check import PreFlightCheck
from tradingagents.risk_management.risk_limits import RiskLimits


# === Pydantic Models ===

class TradeRequest(BaseModel):
    """Trade analysis request."""
    ticker: str = Field(..., description="Ticker symbol (e.g., NVDA, AAPL)")
    trade_date: str = Field(..., description="Trade date YYYY-MM-DD")
    config: Optional[Dict[str, Any]] = Field(default=None, description="Optional config overrides")

    class Config:
        schema_extra = {
            "example": {
                "ticker": "NVDA",
                "trade_date": "2024-05-10",
                "config": {
                    "max_debate_rounds": 2,
                    "online_tools": True
                }
            }
        }


class TradeResponse(BaseModel):
    """Trade analysis response."""
    status: str
    ticker: str
    trade_date: str
    decision: Optional[str] = None
    confidence: Optional[str] = None
    reports: Optional[Dict[str, str]] = None
    debate_summary: Optional[Dict[str, Any]] = None
    risk_check: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str


class BacktestRequest(BaseModel):
    """Backtest request."""
    tickers: List[str] = Field(..., description="List of ticker symbols")
    start_date: str = Field(..., description="Start date YYYY-MM-DD")
    end_date: str = Field(..., description="End date YYYY-MM-DD")
    initial_capital: float = Field(default=100000, description="Initial capital")
    config: Optional[Dict[str, Any]] = Field(default=None)


class AccountStatusResponse(BaseModel):
    """Account status response."""
    status: str
    risk_limits: Dict[str, Any]
    api_quota: Dict[str, int]
    timestamp: str


# === FastAPI App ===

app = FastAPI(
    title="TradingAgents API",
    description="Multi-Agent LLM Financial Trading Framework API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for local access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
_ta_instance: Optional[TradingAgentsGraph] = None
_task_results: Dict[str, Dict] = {}  # Background task results


def get_trading_agents(config: Dict = None) -> TradingAgentsGraph:
    """Get or create TradingAgents instance."""
    global _ta_instance

    merged_config = DEFAULT_CONFIG.copy()
    if config:
        merged_config.update(config)

    _ta_instance = TradingAgentsGraph(debug=False, config=merged_config)
    return _ta_instance


# === Endpoints ===

@app.get("/")
async def root():
    """Root endpoint - API status."""
    return {
        "status": "running",
        "name": "TradingAgents API",
        "version": "0.1.0",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "analyze": "/api/analyze",
            "analyze_stream": "/api/analyze/stream",
            "backtest": "/api/backtest",
            "status": "/api/status",
            "risk_check": "/api/risk/check",
            "config": "/api/config"
        }
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.post("/api/analyze", response_model=TradeResponse)
async def analyze_trade(request: TradeRequest):
    """
    Analyze a trade decision for given ticker and date.

    This runs the full TradingAgents workflow:
    Analyst Team → Research Debate → Trader → Risk Triangle → Decision
    """
    try:
        # Pre-flight risk check
        checker = PreFlightCheck()
        risk_result = checker.run(request.ticker, request.trade_date)

        if not risk_result["passed"]:
            return TradeResponse(
                status="blocked",
                ticker=request.ticker,
                trade_date=request.trade_date,
                risk_check=risk_result,
                error=risk_result["blocked_reason"],
                timestamp=datetime.now().isoformat()
            )

        # Run analysis
        ta = get_trading_agents(request.config)
        state, decision = ta.propagate(request.ticker, request.trade_date)

        # Extract confidence
        confidence = "MEDIUM"
        if "HIGH" in decision or "high confidence" in decision.lower():
            confidence = "HIGH"
        elif "LOW" in decision or "low confidence" in decision.lower():
            confidence = "LOW"

        # Build response
        return TradeResponse(
            status="success",
            ticker=request.ticker,
            trade_date=request.trade_date,
            decision=decision,
            confidence=confidence,
            reports={
                "market": state.get("market_report", ""),
                "sentiment": state.get("sentiment_report", ""),
                "news": state.get("news_report", ""),
                "fundamentals": state.get("fundamentals_report", ""),
                "trader_plan": state.get("trader_investment_plan", ""),
            },
            debate_summary={
                "bull_history": state.get("investment_debate_state", {}).get("bull_history", ""),
                "bear_history": state.get("investment_debate_state", {}).get("bear_history", ""),
                "judge_decision": state.get("investment_debate_state", {}).get("judge_decision", ""),
            },
            risk_check=risk_result,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        return TradeResponse(
            status="error",
            ticker=request.ticker,
            trade_date=request.trade_date,
            error=str(e),
            timestamp=datetime.now().isoformat()
        )


@app.post("/api/analyze/stream")
async def analyze_trade_stream(request: TradeRequest):
    """
    Stream trade analysis progress.

    Returns incremental updates as agents complete their analysis.
    """
    async def generate():
        try:
            # Pre-flight check
            checker = PreFlightCheck()
            risk_result = checker.run(request.ticker, request.trade_date)

            yield json.dumps({"type": "risk_check", "data": risk_result}) + "\n"

            if not risk_result["passed"]:
                yield json.dumps({
                    "type": "blocked",
                    "data": {"reason": risk_result["blocked_reason"]}
                }) + "\n"
                return

            # Initialize
            yield json.dumps({
                "type": "start",
                "data": {"ticker": request.ticker, "date": request.trade_date}
            }) + "\n"

            # Run with debug streaming
            ta = get_trading_agents(request.config)
            ta.debug = True

            for chunk in ta.graph.stream(ta.propagator.create_initial_state(
                request.ticker, request.trade_date
            ), **ta.propagator.get_graph_args()):
                if chunk:
                    yield json.dumps({
                        "type": "progress",
                        "data": {"step": str(chunk.keys())}
                    }) + "\n"

            # Final result
            state = ta.curr_state
            decision = state.get("final_trade_decision", "")

            yield json.dumps({
                "type": "complete",
                "data": {
                    "decision": decision,
                    "reports": {
                        "market": state.get("market_report", ""),
                        "sentiment": state.get("sentiment_report", ""),
                    }
                }
            }) + "\n"

        except Exception as e:
            yield json.dumps({"type": "error", "data": {"message": str(e)}}) + "\n"

    return StreamingResponse(generate(), media_type="application/json")


@app.post("/api/analyze/background")
async def analyze_trade_background(
    request: TradeRequest,
    background_tasks: BackgroundTasks
):
    """
    Start background analysis task.

    Returns task_id for later result retrieval.
    """
    task_id = f"{request.ticker}_{request.trade_date}_{datetime.now().strftime('%H%M%S')}"

    async def run_analysis():
        try:
            checker = PreFlightCheck()
            risk_result = checker.run(request.ticker, request.trade_date)

            if not risk_result["passed"]:
                _task_results[task_id] = {
                    "status": "blocked",
                    "risk_check": risk_result
                }
                return

            ta = get_trading_agents(request.config)
            state, decision = ta.propagate(request.ticker, request.trade_date)

            _task_results[task_id] = {
                "status": "success",
                "decision": decision,
                "reports": {
                    "market": state.get("market_report", ""),
                    "sentiment": state.get("sentiment_report", ""),
                }
            }
        except Exception as e:
            _task_results[task_id] = {
                "status": "error",
                "error": str(e)
            }

    background_tasks.add_task(run_analysis)

    return {"task_id": task_id, "status": "started"}


@app.get("/api/analyze/result/{task_id}")
async def get_analysis_result(task_id: str):
    """Get result of background analysis task."""
    if task_id not in _task_results:
        return {"status": "pending", "task_id": task_id}

    return {"status": "complete", "task_id": task_id, "result": _task_results[task_id]}


@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest):
    """
    Run backtest for multiple tickers over a time range.

    Note: This is a placeholder - full backtest implementation
    requires additional setup.
    """
    return {
        "status": "started",
        "tickers": request.tickers,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "initial_capital": request.initial_capital,
        "message": "Backtest running in background. Check /api/backtest/status for progress."
    }


@app.get("/api/status", response_model=AccountStatusResponse)
async def get_status():
    """
    Get system status: API quota, risk limits, etc.
    """
    from tradingagents.monitoring.rate_limiter import RateLimiter

    limits = RiskLimits.load_from_config()
    quota = RateLimiter.get_remaining_quota("openai_chat")

    return AccountStatusResponse(
        status="active",
        risk_limits={
            "max_position_per_symbol": limits.max_position_per_symbol,
            "max_daily_trades": limits.max_daily_trades,
            "max_portfolio_exposure": limits.max_portfolio_exposure,
        },
        api_quota={
            "rpm_remaining": quota["rpm_remaining"],
            "rpm_limit": quota["rpm_limit"],
        },
        timestamp=datetime.now().isoformat()
    )


@app.post("/api/risk/check")
async def risk_check(
    ticker: str = Query(..., description="Ticker symbol"),
    trade_date: str = Query(..., description="Trade date YYYY-MM-DD")
):
    """
    Run pre-flight risk check without executing trade.
    """
    checker = PreFlightCheck()
    result = checker.run(ticker, trade_date)

    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "passed": result["passed"],
        "checks": result["checks"],
        "blocked_reason": result.get("blocked_reason"),
        "warnings": result.get("warnings", [])
    }


@app.get("/api/config")
async def get_config():
    """Get current configuration."""
    return {
        "config": DEFAULT_CONFIG,
        "overrides": {
            "llm_provider": os.getenv("LLM_PROVIDER", DEFAULT_CONFIG["llm_provider"]),
            "backend_url": os.getenv("BACKEND_URL", DEFAULT_CONFIG["backend_url"]),
            "deep_think_llm": os.getenv("DEEP_THINK_LLM", DEFAULT_CONFIG["deep_think_llm"]),
            "quick_think_llm": os.getenv("QUICK_THINK_LLM", DEFAULT_CONFIG["quick_think_llm"]),
            "max_debate_rounds": int(
                os.getenv("MAX_DEBATE_ROUNDS", DEFAULT_CONFIG["max_debate_rounds"])
            ),
            "online_tools": (
                os.getenv("ONLINE_TOOLS", str(DEFAULT_CONFIG["online_tools"])).lower() == "true"
            ),
        }
    }


@app.post("/api/config")
async def update_config(config: Dict[str, Any] = Body(...)):
    """
    Update configuration for subsequent requests.

    Note: Changes are applied to the global TradingAgents instance.
    """
    global _ta_instance

    # Validate config keys
    valid_keys = [
        "deep_think_llm", "quick_think_llm", "max_debate_rounds",
        "max_risk_discuss_rounds", "online_tools", "llm_provider", "backend_url"
    ]

    invalid_keys = [k for k in config.keys() if k not in valid_keys]
    if invalid_keys:
        raise HTTPException(400, f"Invalid config keys: {invalid_keys}")

    # Reset instance with new config
    _ta_instance = None
    get_trading_agents(config)

    return {"status": "updated", "config": config}


@app.get("/api/tickers/search")
async def search_tickers(query: str = Query(..., min_length=1)):
    """
    Search for ticker symbols.

    Placeholder - integrate with ticker search service.
    """
    # Common tickers for demo
    common_tickers = [
        {"symbol": "AAPL", "name": "Apple Inc."},
        {"symbol": "NVDA", "name": "NVIDIA Corporation"},
        {"symbol": "GOOGL", "name": "Alphabet Inc."},
        {"symbol": "MSFT", "name": "Microsoft Corporation"},
        {"symbol": "AMZN", "name": "Amazon.com Inc."},
        {"symbol": "META", "name": "Meta Platforms Inc."},
        {"symbol": "TSLA", "name": "Tesla Inc."},
    ]

    # Filter by query
    results = [
        t for t in common_tickers
        if query.upper() in t["symbol"] or query.lower() in t["name"].lower()
    ]

    return {"query": query, "results": results, "count": len(results)}


# === Server Launch ===

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Run the API server."""
    print(f"\n🚀 Starting TradingAgents API Server...")
    print(f"   Local: http://localhost:{port}")
    print(f"   Docs: http://localhost:{port}/docs")
    print(f"   ReDoc: http://localhost:{port}/redoc")
    print(f"\n   Press Ctrl+C to stop\n")

    uvicorn.run(
        "tradingagents.api.server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
