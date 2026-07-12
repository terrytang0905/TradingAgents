# Analyst Agent Template

> 数据采集型Agent创建模板

## Factory Function Pattern

```python
# tradingagents/agents/analysts/<name>_analyst.py

from langchain_core.messages import HumanMessage, AIMessage
from typing import Dict, Any


def create_<name>_analyst(llm, toolkit):
    """
    Create <Name> Analyst agent.

    Args:
        llm: ChatOpenAI or ChatAnthropic instance
        toolkit: Toolkit instance providing data tools

    Returns:
        Node function for LangGraph
    """

    def node(state) -> Dict[str, Any]:
        """
        Analyst node function.

        Input: AgentState
        Output: Dict with report_key and optional messages
        """
        # 1. Extract state fields
        company = state["company_of_interest"]
        trade_date = state["trade_date"]

        # 2. Build prompt
        prompt = f"""You are a <Name> Analyst analyzing {company} on {trade_date}.

        ## Your Task
        Analyze <data_type> data and generate a comprehensive report.

        ## Data to Analyze
        {<data_source>}

        ## Output Format
        ## <Name> Analysis Report for {company}

        ### Data Summary
        <key metrics and statistics>

        ### Key Findings
        - <finding_1>
        - <finding_2>
        - <finding_3>

        ### Signals/Indicators
        - <signal_1>: <value> (<interpretation>)
        - <signal_2>: <value> (<interpretation>)

        ### Recommendations
        <brief actionable recommendations>
        """

        # 3. Invoke LLM (bind tools if needed)
        # If using tools: llm.bind_tools([...]).invoke(prompt)
        # If no tools: llm.invoke(prompt)
        response = llm.invoke(prompt)

        # 4. Return state update
        return {
            "<name>_report": response.content,
            "messages": [AIMessage(content=response.content)],
            "sender": "<Name> Analyst"
        }

    return node
```

---

## With Tools (Tool-calling Analyst)

```python
def create_<name>_analyst_with_tools(llm, toolkit):
    """Analyst that calls tools for data."""

    # Bind tools to LLM
    tools = [
        toolkit.get_<data_tool_1>,
        toolkit.get_<data_tool_2>,
    ]
    llm_with_tools = llm.bind_tools(tools)

    def node(state) -> Dict[str, Any]:
        company = state["company_of_interest"]
        trade_date = state["trade_date"]

        prompt = f"""You are a <Name> Analyst.

        Use your tools to gather <data_type> data for {company} around {trade_date}.

        Call the appropriate tools to retrieve:
        1. <data_1>
        2. <data_2>

        Then analyze and generate a report.
        """

        response = llm_with_tools.invoke(prompt)

        return {
            "<name>_report": response.content,
            "messages": [response],
            "sender": "<Name> Analyst"
        }

    return node
```

---

## Prompt Design Checklist

### Role Definition
```
"You are a [Type] Analyst specializing in [domain]."
```

### Task Description
```
"Your task is to analyze [data_type] and identify [signals/patterns/opportunities]."
```

### Input Specification
```
"Available data: [list data sources from state or tools]"
```

### Output Requirements
```
"Generate a report following this format:
1. Data Summary
2. Key Findings (bullet points)
3. Signals with interpretations
4. Brief recommendations"
```

### Constraints
```
- Focus on actionable insights
- Avoid generic observations
- Quantify when possible
- Cite specific data points"
```

---

## Integration Steps

1. **Create file**: `analysts/<name>_analyst.py`
2. **Add to __init__.py**: `from .analysts.<name>_analyst import create_<name>_analyst`
3. **Create Tool Node**: If using tools, register in `_create_tool_nodes()`
4. **Add Conditional Edge**: In `conditional_logic.py`, add `should_continue_<name>()`
5. **Update Graph**: In `setup.py`, add node and edges
6. **Test**: Create `tests/test_<name>_analyst.py`

---

## Example: Sentiment Analyst

```python
def create_sentiment_analyst(llm, toolkit):
    """Social media sentiment analyst."""

    def node(state) -> Dict[str, Any]:
        company = state["company_of_interest"]
        trade_date = state["trade_date"]

        prompt = f"""You are a Sentiment Analyst analyzing social media discussions about {company} on {trade_date}.

        ## Task
        Analyze sentiment from Reddit, Twitter, and financial forums.
        Identify:
        - Overall sentiment score (Positive/Neutral/Negative)
        - Key discussion themes
        - Notable opinions from influential voices
        - Sentiment trend (improving/declining/stable)

        ## Output Format
        ## Sentiment Analysis Report for {company}

        ### Overall Sentiment
        Score: X/10 (Positive/Neutral/Negative)
        Trend: <direction>

        ### Key Themes
        1. <theme_1>: <summary>
        2. <theme_2>: <summary>

        ### Notable Discussions
        - <discussion_1>
        - <discussion_2>

        ### Trading Implications
        <how sentiment affects trading decisions>
        """

        response = llm.invoke(prompt)

        return {
            "sentiment_report": response.content,
            "messages": [AIMessage(content=response.content)],
            "sender": "Sentiment Analyst"
        }

    return node
```