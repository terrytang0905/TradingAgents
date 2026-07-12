---
name: trading-strategy
description: 创建新交易策略Agent，基于现有模板快速定制。支持Analyst/Debater/Decision三种类型Agent生成。
origin: custom
---

# Trading Strategy Skill

> 基于模板快速创建新交易策略Agent

## When to Activate

- 用户提及"新策略"、"添加Agent"、"创建分析师"
- 用户描述交易逻辑意图（如"我要一个动量策略Agent"）
- 需要复用现有辩论/决策模式

手动调用：`/trading-strategy` 或 `/新策略`

---

## Strategy Templates Overview

| 类型 | 模板文件 | 适用场景 |
|------|---------|---------|
| **Analyst** | `@references/analyst_template.md` | 数据采集、报告生成 |
| **Debater** | `@references/bull_bear_template.md` | 观点辩论、多视角论证 |
| **Risk Debater** | `@references/risk_triangle.md` | 风险三角辩论 |
| **Decision** | `@references/decision_template.md` | 最终决策、交易执行 |

---

## Quick Start Workflow

```
Step 1: 确定Agent类型
  → 选择 Analyst/Debater/Decision

Step 2: 加载模板
  → /trading-strategy <type>

Step 3: 填写定制部分
  → 修改prompt、添加数据源、调整输出格式

Step 4: 注册到Graph
  → 按 @tradingagents/graph/AGENTS.md 流程

Step 5: 测试验证
  → pytest tests/test_<name>_analyst.py
```

---

## Agent Creation Checklist

### Analyst Agent
- [ ] 创建 `analysts/<name>_analyst.py`
- [ ] 定义数据源（Toolkit工具）
- [ ] 编写prompt模板
- [ ] 添加到 `agents/__init__.py`
- [ ] 注册Tool Node
- [ ] 添加Conditional Edge
- [ ] 测试数据采集

### Debater Agent
- [ ] 创建 `researchers/<name>_researcher.py`
- [ ] 配置Memory检索
- [ ] 编写辩论prompt
- [ ] 添加count计数逻辑
- [ ] 测试辩论循环

### Decision Agent
- [ ] 创建 `managers/<name>_manager.py`
- [ ] 配置deep_thinking LLM
- [ ] 编写裁决prompt
- [ ] 定义输出格式
- [ ] 测试决策输出

---

## Output Format Standard

所有决策Agent必须输出：

```
FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL**
CONFIDENCE: HIGH/MEDIUM/LOW
KEY_FACTORS:
- <factor_1>
- <factor_2>
- <factor_3>
RATIONALE: <concise explanation>
```

---

## Prompt Design Tips

### Analyst Prompt 结构
```
1. Role定义（你是XX分析师）
2. 任务描述（分析什么数据）
3. 输入说明（从state获取什么）
4. 输出要求（报告格式）
5. 注意事项（避免什么错误）
```

### Debater Prompt 结构
```
1. Role定义（你是看涨/看跌分析师）
2. 论点要求（强调什么、反驳什么）
3. Memory集成（类似情境教训）
4. 输出格式（ conversational style）
5. 辩论参与（直接回应对方观点）
```

---

## See Detailed Templates

- Analyst: `@references/analyst_template.md`
- Bull/Bear: `@references/bull_bear_template.md`
- Risk Triangle: `@references/risk_triangle.md`
- Decision: `@references/decision_template.md`
- Output Format: `@references/output_format.md`

---

## Testing Your Agent

```bash
# Quick test
python -c "
from tradingagents.agents.<name>_analyst import create_<name>_analyst
from langchain_openai import ChatOpenAI
node = create_<name>_analyst(ChatOpenAI(model='gpt-4o-mini'), toolkit)
print('✅ Agent created successfully')
"

# Full test
pytest tests/test_<name>_analyst.py -v
```