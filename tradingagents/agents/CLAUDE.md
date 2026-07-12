# TradingAgents Agents Layer

> Agent创建规范与接口契约

## Agent Creation Pattern (Factory Function)

所有Agent遵循工厂函数模式：

```python
def create_<agent_name>(llm, memory=None, toolkit=None) -> callable:
    """
    Factory function creating an agent node.

    Args:
        llm: ChatOpenAI or ChatAnthropic instance
        memory: FinancialSituationMemory instance (optional)
        toolkit: Toolkit instance for tools (optional)

    Returns:
        node: Function accepting state, returning state update dict
    """
    def node(state) -> dict:
        # 1. Extract needed state fields
        # 2. Get past memories if memory exists
        # 3. Build prompt with context + memories
        # 4. Invoke LLM
        # 5. Return state update dict
        return {...}
    return node
```

## State Interface Contract

**Input**: `AgentState` TypedDict (defined in `utils/agent_states.py`)

**Output**: Dict with keys matching `AgentState` fields

**IMPORTANT Rules**:
- Debate agents: Always include `investment_debate_state["count"] + 1`
- Risk agents: Always include `risk_debate_state["count"] + 1`
- Analyst agents: Return report string (e.g., `market_report`)
- Decision agents: Return decision string (e.g., `final_trade_decision`)

## Memory Integration Pattern

```python
# Standard memory retrieval pattern
curr_situation = f"{market_report}\n\n{sentiment_report}\n\n{news_report}\n\n{fundamentals_report}"
past_memories = memory.get_memories(curr_situation, n_matches=2)

# Build memory string for prompt
past_memory_str = ""
for rec in past_memories:
    past_memory_str += rec["recommendation"] + "\n\n"
```

## Agent Categories

| Category | File Pattern | Memory | Tools |
|----------|-------------|--------|-------|
| **Analyst** | `analysts/<name>_analyst.py` | No | Yes (Toolkit) |
| **Researcher** | `researchers/<name>_researcher.py` | Yes | No |
| **Trader** | `trader/trader.py` | Yes | No |
| **Risk Debator** | `risk_mgmt/<type>_debator.py` | No | No |
| **Manager** | `managers/<name>_manager.py` | Yes | No |

## Adding New Analyst (完整流程)

### Step 1: Create Analyst File

```python
# tradingagents/agents/analysts/<new>_analyst.py

from langchain_core.messages import HumanMessage

def create_<new>_analyst(llm, toolkit):
    """Create <New> Analyst agent."""

    def node(state) -> dict:
        company = state["company_of_interest"]
        trade_date = state["trade_date"]

        # Build prompt
        prompt = f"""You are a <New> Analyst analyzing {company} on {trade_date}.
        ...detailed instructions...
        """

        # Invoke LLM (with tools if needed)
        response = llm.invoke(prompt)

        return {"<new>_report": response.content}

    return node
```

### Step 2: Register in `__init__.py`

```python
# tradingagents/agents/__init__.py
from .analysts.<new>_analyst import create_<new>_analyst

__all__ = [
    ...,
    "create_<new>_analyst",
]
```

### Step 3: Add Tool Node (if using tools)

```python
# tradingagents/graph/trading_graph.py

def _create_tool_nodes(self):
    return {
        ...,
        "<new>": ToolNode([
            self.toolkit.get_<new>_data,
            self.toolkit.get_<new>_analysis,
        ]),
    }
```

### Step 4: Add Conditional Logic

```python
# tradingagents/graph/conditional_logic.py

def should_continue_<new>(self, state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools_<new>"
    return "Msg Clear <New>"
```

### Step 5: Update Graph Setup

```python
# tradingagents/graph/setup.py

def setup_graph(self, selected_analysts=["market", "social", "news", "fundamentals", "<new>"]):
    # Add node
    workflow.add_node("<New> Analyst", create_<new>_analyst(...))
    workflow.add_node("Msg Clear <New>", create_msg_delete())
    workflow.add_node("tools_<new>", self.tool_nodes["<new>"])

    # Add edges
    workflow.add_conditional_edges("<New> Analyst", self.conditional_logic.should_continue_<new>, ...)
```

## Prompt Design Guidelines

### Analyst Prompts
- Focus on data extraction and report generation
- Include specific output format requirements
- Use structured sections (## Data, ## Analysis, ## Signals)

### Researcher Prompts (Bull/Bear)
- Include debate history for context
- Require addressing opponent's arguments
- Use conversational style, not bullet lists
- Include memory retrieval for past lessons

### Manager Prompts
- Require decisive stance (Buy/Sell/Hold)
- Avoid defaulting to Hold without justification
- Include actionable investment plan
- Reference past mistakes from memory

### Risk Prompts
- Use three-perspective debate (Risky/Safe/Neutral)
- Require counterpoint rebuttals
- Output must include risk metrics

## Testing New Agent

```python
# tests/test_<new>_analyst.py

import pytest
from tradingagents.agents.<new>_analyst import create_<new>_analyst
from tradingagents.default_config import DEFAULT_CONFIG

def test_<new>_analyst_creates_node():
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(model="gpt-4o-mini")
    toolkit = Toolkit()
    node = create_<new>_analyst(llm, toolkit)
    assert callable(node)

def test_<new>_analyst_returns_state_update():
    # Mock state and verify output format
    ...
```

## Common Mistakes to Avoid

| Mistake | Symptom | Fix |
|---------|---------|-----|
| Missing count increment | Debate never ends | Add `count + 1` in return dict |
| Wrong state key | KeyError in graph | Check `AgentState` TypedDict |
| No tool_calls check | Tools never called | Add conditional edge logic |
| Prompt too vague | Generic outputs | Add specific output format |
| Memory not used | No learning | Add memory retrieval pattern |

## Agent Output Format Standards

All decision outputs must include:

```
FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**
CONFIDENCE: HIGH/MEDIUM/LOW
KEY_FACTORS:
- <factor_1>
- <factor_2>
- <factor_3>
RATIONALE: <concise explanation>
```

All analysis reports must include:

```
## <Report Title>
### Data Summary
<key metrics>

### Key Findings
- <finding_1>
- <finding_2>

### Signals/Indicators
- <signal_1>: <value> (<interpretation>)
```