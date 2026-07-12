#!/bin/bash
# TradingAgents Local Deployment Start Script
# Usage: ./start.sh [mode]

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print header
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     TradingAgents Local Deployment        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════╝${NC}"
echo ""

# Check Python
if ! command -v python &> /dev/null; then
    echo -e "${RED}Error: Python not found${NC}"
    exit 1
fi

PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2)
echo -e "${GREEN}✓ Python ${PYTHON_VERSION}${NC}"

# Check environment
if [ ! -d ".venv" ] && [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python -m venv .venv
fi

# Activate environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

echo -e "${GREEN}✓ Virtual environment activated${NC}"

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"
pip install -e . --quiet

echo -e "${GREEN}✓ Dependencies installed${NC}"

# Check API keys
check_api_keys() {
    MISSING_KEYS=""

    if [ -z "$OPENAI_API_KEY" ]; then
        MISSING_KEYS+="OPENAI_API_KEY "
    fi

    if [ -z "$FINNHUB_API_KEY" ]; then
        MISSING_KEYS+="FINNHUB_API_KEY "
    fi

    if [ -n "$MISSING_KEYS" ]; then
        echo -e "${YELLOW}⚠ Missing API keys: ${MISSING_KEYS}${NC}"
        echo -e "${YELLOW}  Set them in .env file or environment variables${NC}"
    else
        echo -e "${GREEN}✓ API keys configured${NC}"
    fi
}

# Load .env if exists
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
    echo -e "${GREEN}✓ .env loaded${NC}"
fi

check_api_keys

# Parse mode argument
MODE="${1:-cli}"

echo ""
echo -e "${BLUE}Starting TradingAgents in ${MODE} mode...${NC}"
echo ""

case "$MODE" in
    cli)
        echo -e "${GREEN}Starting CLI interface...${NC}"
        echo -e "  Run: ${YELLOW}tradingagents --help${NC}"
        echo ""
        python -m cli.main
        ;;

    api)
        PORT="${2:-8000}"
        echo -e "${GREEN}Starting REST API server...${NC}"
        echo -e "  Local: ${YELLOW}http://localhost:${PORT}${NC}"
        echo -e "  Docs:  ${YELLOW}http://localhost:${PORT}/docs${NC}"
        echo -e "  ReDoc: ${YELLOW}http://localhost:${PORT}/redoc${NC}"
        echo ""
        python -m tradingagents.api.server --port $PORT
        ;;

    web)
        echo -e "${GREEN}Starting Chainlit Web UI...${NC}"
        echo -e "  URL: ${YELLOW}http://localhost:8000${NC}"
        echo ""
        chainlit run tradingagents/app.py -w --port 8000
        ;;

    all)
        echo -e "${GREEN}Starting all services...${NC}"
        echo ""
        echo -e "${BLUE}Services:${NC}"
        echo -e "  - REST API: ${YELLOW}http://localhost:8001${NC}"
        echo -e "  - Web UI:  ${YELLOW}http://localhost:8002${NC}"
        echo ""

        # Start API in background
        python -m tradingagents.api.server --port 8001 &
        API_PID=$!

        # Start Web UI in background
        chainlit run tradingagents/app.py -w --port 8002 &
        WEB_PID=$!

        echo -e "${GREEN}✓ Services started${NC}"
        echo -e "  API PID: ${API_PID}"
        echo -e "  Web PID: ${WEB_PID}"
        echo ""
        echo -e "${YELLOW}Press Ctrl+C to stop all services${NC}"

        # Wait for interrupt
        trap "kill $API_PID $WEB_PID; exit 0" INT TERM
        wait
        ;;

    test)
        echo -e "${GREEN}Running tests...${NC}"
        python -m pytest tests/ -v --tb=short
        ;;

    install)
        echo -e "${GREEN}Installing TradingAgents...${NC}"
        pip install -e .
        echo -e "${GREEN}✓ Installation complete${NC}"
        ;;

    *)
        echo -e "${RED}Unknown mode: ${MODE}${NC}"
        echo ""
        echo "Usage: ./start.sh [mode]"
        echo ""
        echo "Modes:"
        echo "  cli     - Interactive CLI (default)"
        echo "  api     - REST API server (port 8000)"
        echo "  web     - Chainlit Web UI (port 8000)"
        echo "  all     - Both API and Web UI"
        echo "  test    - Run test suite"
        echo "  install - Install package"
        echo ""
        exit 1
        ;;
esac