# TradingAgents Graph Layer

> LangGraph工作流扩展指南：节点、边、状态传递

## Core Graph Architecture

```
START → Analysts (parallel-ish sequence) → Researchers (debate loop) → Trader → Risk (triangle debate) → END
```

### Graph Components

| Component | File | Purpose |
|-----------|------|---------|
| StateGraph | `setup.py` | Graph construction |
| AgentState | `agent_states.py` | Global state TypedDict |
| ConditionalLogic | `conditional_logic.py` | Edge routing functions |
| Propagator | `propagation.py` | Initial state creation |
| Reflector | `reflection.py` | Post-trade reflection |

## State Structure

```python
class AgentState(MessagesState):
    # Identity
    company_of_interest: str
    trade_date: str
    sender: str

    # Analyst Reports
    market_report: str
    sentiment_report: str
    news_report: str
    fundamentals_report: str

    # Debate States (Nested TypedDicts)
    investment_debate_state: InvestDebateState
    risk_debate_state: RiskDebateState

    # Decisions
    investment_plan: str
    trader_investment_plan: str
    final_trade_decision: str
```

### Nested State: InvestDebateState

```python
class InvestDebateState(TypedDict):
    bull_history: str       # Bull arguments log
    bear_history: str       # Bear arguments log
    history: str            # Full debate transcript
    current_response: str   # Latest speaker's response
    judge_decision: str     # Research Manager's ruling
    count: int              # Debate round counter
```

### Nested State: RiskDebateState

```python
class RiskDebateState(TypedDict):
    risky_history: str
    safe_history: str
    neutral_history: str
    history: str
    latest_speaker: str     # "Risky" / "Safe" / "Neutral"
    current_risky_response: str
    current_safe_response: str
    current_neutral_response: str
    judge_decision: str
    count: int
```

## Adding New Node

### Step 1: Create Node Function

```python
# Follow factory pattern from agents/CLAUDE.md
def create_<new_node>(llm, memory=None) -> callable:
    def node(state) -> dict:
        # Return state update
        return {"<key>": value}
    return node
```

### Step 2: Add to Graph

```python
# tradingagents/graph/setup.py

workflow.add_node("<New Node>", create_<new_node>(...))
```

### Step 3: Connect Edges

```python
# Simple edge (always go to next)
workflow.add_edge("<Prev Node>", "<New Node>")

# Conditional edge (route based on state)
workflow.add_conditional_edges(
    "<New Node>",
    self.conditional_logic.should_continue_<new>,
    {
        "Option A": "Node A",
        "Option B": "Node B",
    }
)
```

## Conditional Edge Patterns

### Tool Call Check (Analysts)

```python
def should_continue_<analyst>(state: AgentState) -> str:
    """Route based on tool_calls presence."""
    messages = state["messages"]
    last_message = messages[-1]

    if last_message.tool_calls:
        return f"tools_{analyst}"  # Call tools
    return f"Msg Clear {analyst}"  # Clear messages, proceed
```

### Debate Loop Check (Researchers)

```python
def should_continue_debate(state: AgentState) -> str:
    """Route based on debate round count."""
    count = state["investment_debate_state"]["count"]

    # Exit condition: max rounds reached
    if count >= 2 * self.max_debate_rounds:
        return "Research Manager"

    # Continue: alternate between Bull and Bear
    if state["investment_debate_state"]["current_response"].startswith("Bull"):
        return "Bear Researcher"
    return "Bull Researcher"
```

### Triangle Debate Check (Risk)

```python
def should_continue_risk_analysis(state: AgentState) -> str:
    """Route triangle debate between Risky/Safe/Neutral."""
    count = state["risk_debate_state"]["count"]

    # Exit condition
    if count >= 3 * self.max_risk_discuss_rounds:
        return "Risk Judge"

    # Rotate: Risky → Safe → Neutral → Risky
    speaker = state["risk_debate_state"]["latest_speaker"]
    if speaker.startswith("Risky"):
        return "Safe Analyst"
    if speaker.startswith("Safe"):
        return "Neutral Analyst"
    return "Risky Analyst"
```

## Edge Flow Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                    LangGraph Workflow                             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  START                                                            │
│    │                                                              │
│    ▼                                                              │
│  [Market Analyst] ←─────┐                                        │
│    │ (conditional)      │ tool_calls? → tools_market            │
│    ├─→ tools_market ────┘ (loop back)                            │
│    └─→ Msg Clear Market                                          │
│           │                                                       │
│           ▼                                                       │
│  [Social Analyst] (same pattern)                                 │
│           │                                                       │
│           ▼                                                       │
│  [News Analyst] (same pattern)                                   │
│           │                                                       │
│           ▼                                                       │
│  [Fundamentals Analyst] (same pattern)                           │
│           │                                                       │
│           ▼                                                       │
│  ┌──────────────────────────────────────────────┐               │
│  │          Debate Loop                         │               │
│  │  [Bull Researcher] ←──→ [Bear Researcher]    │               │
│  │         │                    │               │               │
│  │         └────────────────────┘               │               │
│  │                  │                           │               │
│  │                  ▼ (count >= max)            │               │
│  │         [Research Manager]                   │               │
│  └──────────────────────────────────────────────┘               │
│           │                                                       │
│           ▼                                                       │
│  [Trader]                                                        │
│           │                                                       │
│           ▼                                                       │
│  ┌──────────────────────────────────────────────┐               │
│  │        Triangle Debate                       │               │
│  │  [Risky] → [Safe] → [Neutral] → [Risky]      │               │
│  │              │                               │               │
│  │              ▼ (count >= max)                │               │
│  │        [Risk Judge]                          │               │
│  └──────────────────────────────────────────────┘               │
│           │                                                       │
│           ▼                                                       │
│  END                                                              │
└──────────────────────────────────────────────────────────────────┘
```

## Message Clear Pattern

```python
# Used after each analyst to prevent context explosion

def create_msg_delete():
    def delete_messages(state):
        messages = state["messages"]
        removal_operations = [RemoveMessage(id=m.id) for m in messages]
        placeholder = HumanMessage(content="Continue")
        return {"messages": removal_operations + [placeholder]}
    return delete_messages
```

**IMPORTANT**: Always use Msg Clear nodes after analyst nodes. Without this, messages accumulate and exceed context window.

## Graph Compilation

```python
# setup.py
def setup_graph(self, selected_analysts):
    workflow = StateGraph(AgentState)

    # Add nodes, edges...

    return workflow.compile()  # Returns Runnable graph
```

## Running the Graph

```python
# trading_graph.py
def propagate(self, company_name, trade_date):
    init_state = self.propagator.create_initial_state(company_name, trade_date)
    args = self.propagator.get_graph_args()

    if self.debug:
        # Streaming mode with trace
        for chunk in self.graph.stream(init_state, **args):
            chunk["messages"][-1].pretty_print()
        final_state = trace[-1]
    else:
        # Standard invocation
        final_state = self.graph.invoke(init_state, **args)

    return final_state, self.process_signal(final_state["final_trade_decision"])
```

## Adding New Analyst to Graph (完整示例)

```python
# Assume you've created create_quant_analyst following agents/CLAUDE.md

# Step 1: Add to setup_graph
if "quant" in selected_analysts:
    workflow.add_node("Quant Analyst", create_quant_analyst(llm, toolkit))
    workflow.add_node("Msg Clear Quant", create_msg_delete())
    workflow.add_node("tools_quant", self.tool_nodes["quant"])

# Step 2: Add conditional edge
workflow.add_conditional_edges(
    "Quant Analyst",
    self.conditional_logic.should_continue_quant,
    ["tools_quant", "Msg Clear Quant"]
)
workflow.add_edge("tools_quant", "Quant Analyst")

# Step 3: Connect to chain (after previous analyst, before next)
workflow.add_edge("Msg Clear <Prev>", "Quant Analyst")
workflow.add_edge("Msg Clear Quant", "<Next Analyst>")  # or "Bull Researcher"
```

## State Update Rules

| Node Type | Must Return | Optional Return |
|-----------|-------------|-----------------|
| Analyst | `{report_key: str}` | `{"messages": [AIMessage]}` |
| Debater | `{debate_state: dict, count: count+1}` | — |
| Manager | `{judge_decision: str, plan_key: str}` | — |
| Trader | `{trader_plan: str, messages: [...]}` | — |
| Clear | `{"messages": removal + placeholder}` | — |

## Testing Graph Flow

```python
# tests/test_graph_flow.py

def test_analyst_to_researcher_flow():
    ta = TradingAgentsGraph(selected_analysts=["market"])
    state, decision = ta.propagate("AAPL", "2024-01-10")

    assert state["market_report"] is not None
    assert state["investment_debate_state"]["count"] >= 2
    assert state["final_trade_decision"] is not None

def test_debate_round_limit():
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = 2
    ta = TradingAgentsGraph(config=config)

    state, _ = ta.propagate("NVDA", "2024-05-10")
    # Bull + Bear = 2 agents, max_debate_rounds=2
    # Total count should be <= 2 * 2 = 4
    assert state["investment_debate_state"]["count"] <= 4
```

## Common Graph Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `KeyError: 'count'` | Debate state not initialized | Check `propagation.py` init state |
| Graph hangs | Missing END edge | Add `workflow.add_edge("Last Node", END)` |
| Infinite loop | Conditional never returns exit | Check count threshold logic |
| Context overflow | No Msg Clear nodes | Add after each analyst |
| Tool never called | Missing tool edge | Add `add_edge(tools, analyst)` loop |

## Performance Tips

| Optimization | Implementation |
|--------------|----------------|
| Reduce API calls | Use `online_tools=False` for backtesting |
| Faster LLM | Use `quick_think_llm` for analysts |
| Smaller debate | Reduce `max_debate_rounds` |
| Batch processing | Run multiple tickers in parallel subagents |