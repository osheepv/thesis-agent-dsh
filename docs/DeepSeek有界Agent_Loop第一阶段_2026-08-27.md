# DeepSeek有界Agent Loop第一阶段

本阶段只支持DeepSeek API，不提供OpenAI、Anthropic、Ollama或其他供应商的配置入口。多供应商适配层保留在后续路线中，当前先把一条真实写作链路做稳。

## 已落地的范围

- 前端“推理配置”可在运行时设置DeepSeek Base URL、模型、API Key、思考模式、推理强度与Tools/Vision能力。
- API Key只保存在当前后端进程内：后端不回显，前端不写`localStorage`，数据库不落盘；留空密钥会保留当前值，重启服务后恢复`.env`配置。
- 认证开启时，只有`owner`角色可修改DeepSeek运行时配置。
- 环6逐章撰写前可运行一次有界写作计划Agent，计划作为检查点保存，失败重试时不重复消耗已完成的计划调用。

## Agent工具与边界

当前Agent只能调用四个注册的只读工具：

1. `search_sources`：搜索当前任务文献池和项目知识库。
2. `read_approved_context`：读取已批准的大纲、结果、论证图或研究协议。
3. `check_citation`：检查`[L序号]`是否属于当前文献池。
4. `check_plan_structure`：检查计划是否覆盖全部章节且不含越界引用。

循环强制最大轮数、最大工具调用数和单次观测长度；未注册工具、参数越界、重复动作、空结果和不收敛都会显式失败。工具参数由本地JSON Schema子集校验，不使用需要`/beta`端点的供应商strict模式。

## 开启方式

该能力默认关闭，避免升级后产生未预期模型费用。在`backend/.env`中设置：

```dotenv
THESIS_AGENT_LOOP_ENABLED=true
THESIS_AGENT_LOOP_MAX_TURNS=4
THESIS_AGENT_LOOP_MAX_TOOL_CALLS=10
THESIS_AGENT_LOOP_MAX_OBSERVATION_CHARS=4000
THESIS_AGENT_LOOP_MAX_OUTPUT_TOKENS=2048
```

开启后，当前DeepSeek配置必须声明Tools能力，否则环6在发起付费调用前立即拒绝执行。

## 官方协议依据

- [DeepSeek当前模型与能力](https://api-docs.deepseek.com/quick_start/pricing/)
- [DeepSeek Tool Calls协议](https://api-docs.deepseek.com/guides/tool_calls/)

## 下一步

先在环6完成真实DeepSeek小规模验收，观测工具选择、收敛、Token与计划质量；通过后再扩展到选题、文献、大纲和修订环节。多模型供应商不在本阶段范围内。
