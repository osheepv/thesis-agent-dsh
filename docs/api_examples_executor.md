# M2 环节执行体 API 调用示例

本文档描述 **M2 环节执行体** 的调用方式。执行体不是独立 HTTP 服务，而是被 **M1 FSM 编排器**
在推进环节时通过 `get_executor(ring_no).execute(ctx)` 同步调用的 Python 对象，返回统一结构
`ExecResult`。因此本文以 **Python 代码 + JSON（output 内容）** 的形式给出调用示例。

关键约定（对齐系统设计 §3.2.M2）：

- 每个环节封装为 `RingExecutor` 子类，调用入口统一为 `get_executor(ring_no).execute(ctx)`。
- `ctx` 为 `ExecContext`，由 **application 层 `MainOrchestration`**（`run_ring1` / `run_ring5` / `run_ring6`）
  组装下发。
- 执行体返回 `ExecResult`，其中 `output` 是 **JSON 字符串**（后续 JSON 解析成结构化产物），
  `accept / fallbackTo / issues / evidence` 供 M1 看门与 guardrail / HITL 参考。
- 真实 DSH（LLM / 检索）为二期接入点；本期各环节使用**确定性 Mock 生成器**保证闭环可运行。
- 已注册实现的执行体为 **环1 / 环5 / 环6**；环 2/4/8/10 为 HITL 网关（本期仅留接口，未注册实现）。

> 说明：本文档中的响应示例基于 `backend/executor/`（环1/5/6）的真实产出结构与
> `tests/test_executor.py` 的断言行为推导，字段名与实现一一对应。

引用来源：

- 接口基类：`backend/executor/base.py`
- 环1 选题：`backend/executor/ring1_topic.py`
- 环5 大纲：`backend/executor/ring5_outline.py`
- 环6 撰写：`backend/executor/ring6_chapter.py`
- 调用方：`backend/application/service/uc_main_orchestration.py`
- 返回结构校验：`tests/test_executor.py`

---

## 1. ExecContext：执行体统一上下文入参

`ExecContext`（`backend/executor/base.py:46`）由 M1 编排器在推进环节时组装下发，
实际一期兜底只需 `subject_field + degree` 即可闭环。

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| subject_field | string | 是 | 学科/专业方向（环1 必填，为空会抛 `ValueError`） |
| degree | string | 是 | 学位层次：`BACHELOR` / `MASTER` / `PHD` |
| theme | string | 否 | 题目（环1/环5 输出，环5/环6 引用；空则回退到 `基于{subject_field}的研究`） |
| outline | string | 否 | 大纲提要（环5 输出，环6 引用），为环5 `output` 的 JSON 字符串 |
| trace_id | string? | 否 | 追踪 ID（数据血缘） |
| session_id | string | 否 | 会话 ID（M9 知识隔离预留），缺省 `""` |
| tenant_id | string | 否 | 租户 ID，缺省 `"default"` |

构造示例：

```python
from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext

ctx = ExecContext(
    subject_field="计算机科学与技术",
    degree=Degree.MASTER,
    theme="基于大语言模型的学位论文自动写作研究",
    outline="",                # 环6 时填入环5 的 output
    trace_id="trace-2026-0001",
    session_id="sess-2026-0001",
    tenant_id="default",
)
```

---

## 2. ExecResult：执行体统一输出

`ExecResult`（`backend/executor/base.py:26`）为执行体统一 **四（+一扩展）字段** 输出。
其中 `output` 为 **JSON 字符串**，其余为元数据。

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| output | string | 本环节主要内容产物。**JSON 字符串**，需 `json.loads` 解析为结构化对象（见第 3 节各环节） |
| accept | bool | 是否通过验收（供 M1 看门；`True` 通过） |
| fallbackTo | int? | 若需回退，目标环节号（如 `5` 表示回到大纲；`None` 表示无需回退） |
| issues | list<string> | 发现的问题列表（供 guardrail / HITL 参考） |
| evidence | dict | **扩展字段**：证据/来源（如引用来源、数据口径、规则命中说明） |

> 注：`ExecResult` 实际含 5 个字段（`output / accept / fallbackTo / issues / evidence`），
> 其中 `evidence` 为设计上的扩展项。`output` 是唯一承载业务产物、需二次解析的字段。

`get_executor(ring_no)`（`backend/executor/base.py:103`）接收 **int（1~10）** 或 `RingType`，
返回已注册的执行体实例；环节未注册（含 HITL 预留环 2/4/8/10）时抛 `KeyError`。

```python
from backend.executor import get_executor
from backend.executor.base import ExecResult

res: ExecResult = get_executor(1).execute(ctx)
print(type(res.output))      # <class 'str'>，JSON 字符串
print(res.accept)            # True
print(res.fallbackTo)        # None
print(res.issues)            # []
print(res.evidence)          # {...}
```

---

## 3. 环节调用示例

### 3.1 环1 选题（`get_executor(1).execute(ctx)`）

- 输入：`subject_field + degree`（`subject_field` 为空抛 `ValueError`）。
- 职责：生成候选题目列表，为每道题给出创新点定位与可行性评估。
- 调用方：`MainOrchestration.run_ring1`（`uc_main_orchestration.py:243`）。

调用代码（对齐 `run_ring1`）：

```python
from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor

ctx = ExecContext(
    subject_field="计算机科学与技术",
    degree=Degree.MASTER,
    theme="基于大语言模型的学位论文自动写作研究",
    session_id="sess-2026-0001",
    tenant_id="default",
)
res = get_executor(1).execute(ctx)

assert res.accept is True
import json
data = json.loads(res.output)
candidates = data["candidates"]      # 候选题目列表
chosen = candidates[0]["title"]      # 主编排默认选首条
```

`output` 解析结构（`TopicResult`，`ring1_topic.py:42`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| subject_field | string | 学科/专业方向 |
| degree | string | 学位层次（`BACHELOR` / `MASTER` / `PHD`） |
| candidates | array | 候选题目列表 |
| candidates[].title | string | 题目 |
| candidates[].innovation | string | 创新点定位 |
| candidates[].feasibility | string | 可行性评估 |
| candidates[].degree_fit | string | 与该学位层次的匹配度 |
| recommendation | string | 综合推荐理由 |

`output` JSON 示例（硕士，`subject_field="计算机视觉"`，候选数 4）：

```json
{
  "subject_field": "计算机视觉",
  "degree": "MASTER",
  "candidates": [
    {
      "title": "基于多模态数据融合计算机视觉 的自动识别与关键要素分析研究",
      "innovation": "（1）研究型，在现有理论基础上做增量改进，创新点聚焦'模型/方法改进'。 结合领域知识构建 计算机视觉 专用评估指标体系，实现端到端自动化建模。",
      "feasibility": "现有公开数据集与文献充足，工作量与硕士培养要求匹配，研究可行性高。",
      "degree_fit": "匹配硕士层次，正文预计 30000 字量级。"
    },
    {
      "title": "面向真实场景约束计算机视觉 的自动识别与关键要素分析研究",
      "innovation": "（2）研究型，在现有理论基础上做增量改进，创新点聚焦'模型/方法改进'。 结合领域知识构建 计算机视觉 专用评估指标体系，实现端到端自动化建模。",
      "feasibility": "现有公开数据集与文献充足，工作量与硕士培养要求匹配，研究可行性高。",
      "degree_fit": "匹配硕士层次，正文预计 30000 字量级。"
    },
    "..."
  ],
  "recommendation": "综合创新度、可行性与硕士层次匹配度，推荐首选：\n「基于多模态数据融合计算机视觉 的自动识别与关键要素分析研究」\n推荐理由：现有公开数据集与文献充足，工作量与硕士培养要求匹配，研究可行性高。"
}
```

候选数随学位层次递增（`tests/test_executor.py::test_degree_difference_candidate_count`）：
本科 3 个、硕士 4 个、博士 5 个。

### 3.2 环5 大纲生成（`get_executor(5).execute(ctx)`）

- 输入：`theme`（或回退 `subject_field`）+ `degree`。
- 职责：根据选题生成章节结构蓝图（Outline：章/节/要点），体现学位差异。
- 调用方：`MainOrchestration.run_ring5`（`uc_main_orchestration.py:273`）。

调用代码（对齐 `run_ring5`）：

```python
from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor

ctx = ExecContext(
    subject_field="计算机视觉",
    degree=Degree.MASTER,
    theme="基于深度学习的X识别",     # 来自环1 首选
    session_id="sess-2026-0001",
    tenant_id="default",
)
res = get_executor(5).execute(ctx)

data = json.loads(res.output)
chapters = data["chapters"]   # 章节/节节点（平铺，含层级编号）
summary = data["summary"]
```

`output` 解析结构（`OutlineResult`，`ring5_outline.py:37`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| theme | string | 题目 |
| degree | string | 学位层次 |
| chapters | array | 章节/节节点（平铺，含 `level` 层级编号） |
| chapters[].level | int | 层级：1 章、2 节、3 要点 |
| chapters[].number | string | 编号，如 `第1章` / `1.1` / `1.1.1` |
| chapters[].title | string | 标题 |
| chapters[].points | array<string> | 本节点要点描述 |
| summary | string | 大纲整体说明 |

`output` JSON 示例（硕士，`theme="基于深度学习的X识别"`，缩略展示前两节点）：

```json
{
  "theme": "基于深度学习的X识别",
  "degree": "MASTER",
  "chapters": [
    {
      "level": 1,
      "number": "第1章",
      "title": "绪论",
      "points": ["绪论下共 4 节，层次深度匹配硕士要求。"]
    },
    {
      "level": 2,
      "number": "1.1",
      "title": "研究背景与意义",
      "points": ["深入展开：研究背景与意义 相关论述与数据/案例支撑。"]
    },
    {
      "level": 2,
      "number": "1.2",
      "title": "国内外研究现状述评",
      "points": ["深入展开：国内外研究现状述评 相关论述与数据/案例支撑。"]
    },
    "..."
  ],
  "summary": "共 6 章；已按硕士层次生成15 个章节/节节点（本科章节少、博士章节深）。"
}
```

章节深度随学位层次递增：本科 5 章、硕士 6 章、博士 7 章（`tests/test_executor.py::test_degree_difference_chapter_depth`）。

### 3.3 环6 分章撰写（`get_executor(6).execute(ctx)`）

- 输入：`theme + outline`（`outline` 为空则回退到默认骨架 `_CHAPTER_TITLES` 五章）。
- 职责：根据大纲逐章节生成初稿，产出 `t_chapter_draft` 风格章节草稿（章节号/标题/正文 markdown）。
- 调用方：`MainOrchestration.run_ring6`（`uc_main_orchestration.py:304`）。

调用代码（对齐 `run_ring6`，outline 来自环5）：

```python
from backend.common.aicoding.enums import Degree
from backend.executor import ExecContext, get_executor

# 先用环1、环5 组装上下文
ctx1 = ExecContext(subject_field="计算机视觉", degree=Degree.MASTER, theme="基于深度学习的X识别")
outline_json = get_executor(5).execute(ctx1).output   # 环5 的大纲 JSON

ctx6 = ExecContext(
    subject_field="计算机视觉",
    degree=Degree.MASTER,
    theme="基于深度学习的X识别",
    outline=outline_json,                             # 环5 的 output JSON 字符串
    session_id="sess-2026-0001",
    tenant_id="default",
)
res = get_executor(6).execute(ctx6)

draft = json.loads(res.output)
chapters = draft["chapters"]      # 章节草稿列表
total_words = draft["total_words"]
```

`output` 解析结构（`ChapterWriteResult`，`ring6_chapter.py:44`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| theme | string | 题目 |
| degree | string | 学位层次 |
| chapters | array | 章节草稿列表 |
| chapters[].chapter_no | int | 章节号，如 1 |
| chapters[].chapter_title | string | 章节标题，如 `绪论` |
| chapters[].content | string | 正文（Markdown） |
| chapters[].word_count | int | 正文字数估算 |
| total_words | int | 总字数估算 |

`output` JSON 示例（硕士，第一章，正文字数基于实际模板估算）：

```json
{
  "theme": "基于深度学习的X识别",
  "degree": "MASTER",
  "chapters": [
    {
      "chapter_no": 1,
      "chapter_title": "绪论",
      "content": "## 1 引言\n\n本章围绕「绪论」展开论述，结合领域背景与既有工作，明确本章要解决的核心问题与总体思路。\n\n## 2 绪论中的关键环节\n\n本节梳理第 2 个关键环节的主要内容，说明其方法依据、实现路径与对整体目标的支撑作用。\n\n## 3 绪论中的关键环节\n\n本节梳理第 3 个关键环节的主要内容，说明其方法依据、实现路径与对整体目标的支撑作用。\n\n## 小结\n\n本章对「绪论」相关要点做了系统梳理，为后续章节奠定基础。",
      "word_count": 208
    },
    "..."
  ],
  "total_words": 1080
}
```

正文字数随学位层次递增（`tests/test_executor.py::test_degree_difference_paragraph_depth`）：
本科 2 段/章、硕士 3 段/章、博士 5 段/章。

---

## 4. 在主编排用例中的调用（application 层）

M2 执行体被 **`backend/application/service/uc_main_orchestration.py`** 中的 `MainOrchestration`
按步骤调用，实现「创建任务 → 环1选题 → 环5大纲 → 环6撰写 → 生成 docx」闭环。

| 步骤 | 方法 | 调用的执行体 | 产物 |
| --- | --- | --- | --- |
| 环1 选题 | `run_ring1(task_id)` | `get_executor(1).execute(ctx)` | `candidates` / `chosen` / `recommendation` |
| 环5 大纲 | `run_ring5(task_id)` | `get_executor(5).execute(ctx)` | `outline`(文本) / `chapters` / `summary` |
| 环6 撰写 | `run_ring6(task_id)` | `get_executor(6).execute(ctx)` | `chapters` / `total_words` / `content_preview` |

以 `run_ring1` 为例（`uc_main_orchestration.py:243`），其核心逻辑为：

```python
def run_ring1(self, task_id: str) -> Result[dict]:
    rec = self._require(task_id)
    ctx = ExecContext(
        subject_field=rec.subject_field,
        degree=Degree(rec.degree),
        theme=rec.title,
        session_id=rec.session_id,
        tenant_id=rec.tenant_id,
    )
    res = get_executor(1).execute(ctx)          # 调用 M2 执行体
    if not res.accept:                          # 验收未过 -> 业务异常（含 fallbackTo/issues）
        raise BizException(ErrorCode.FSM_ACCEPTANCE_REJECTED,
                           msg="环1选题未通过验收",
                           detail={"fallbackTo": res.fallbackTo, "issues": res.issues})
    data = json.loads(res.output)               # output 为 JSON 字符串
    candidates = data.get("candidates", [])
    chosen_title = candidates[0]["title"] if candidates else data.get("theme", rec.title)
    self._fsm.advance(task_id, biz_req_no=f"{task_id}-R1", accept=True, artifact_uri=res.output)
    ...
    return Result.ok(data={"candidates": candidates, "chosen": chosen_title,
                           "recommendation": data.get("recommendation", "")}, msg="环1选题完成")
```

`run_ring5` / `run_ring6` 沿用同一模式，差异仅在环节号与产物流转：
- `run_ring5` 取 `rec.ring1["chosen"]` 作为 `theme`，执行 `get_executor(5)`，产物 `outline`（文本）/ `chapters` / `summary`。
- `run_ring6` 取 `rec.ring5["outline"]` 作为 `ctx.outline`，执行 `get_executor(6)`，产物 `chapters` / `total_words` / `content_preview`。

---

## 5. 校验与边缘情况

- 环1 `subject_field` 为空时抛 `ValueError`（`ring1_topic.py:117`），调用方需先校验。
- 环5 `theme` 与环6 `theme` 为空时回退为 `f"基于{ctx.subject_field}的研究"`。
- 环6 `outline` 为空或无法解析为环5 格式时，回退到默认五章骨架（`ring6_chapter.py:72`），容错不报错。
- 未注册环节（环 2/4/8/10 HITL 网关）调用 `get_executor(ring)` 抛 `KeyError`。
- 三个执行体的 `accept` 恒为 `True`、`fallbackTo` 恒为 `None`、`issues` 恒为 `[]`（本期确定性 Mock）。

错误处理速查：

| 场景 | 行为 |
| --- | --- |
| `subject_field` 为空（环1） | `ValueError` |
| 环节未注册实现（环 2/4/8/10） | `KeyError` |
| `accept=false` | application 层抛 `BizException(FSM_ACCEPTANCE_REJECTED)`，`detail` 含 `fallbackTo` + `issues` |
