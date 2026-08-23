# 工作台 API 调用示例

本文档描述前端和演示脚本应使用的聚合接口。Base URL：`http://127.0.0.1:8000`。

> 不要从业务客户端直接调用低层 FSM `advance`。正确流程是先调用当前环执行接口，后端自动验收并进入 `WAITING_APPROVAL`，再调用该环 `confirm`。

## 1. 健康检查

```http
GET /healthz
```

成功时 `data.status` 为 `UP`。

## 2. 创建论文任务

```http
POST /api/v1/console/tasks
Content-Type: application/json
```

```json
{
  "title": "基于大语言模型的学位论文辅助写作研究",
  "degree": "MASTER",
  "subject_field": "计算机科学与技术",
  "scope": "all"
}
```

`degree` 可选 `BACHELOR`、`MASTER`、`PHD`；`scope` 可选 `english`、`chinese`、`all`。不传 `session_id` 时，后端会为任务生成唯一的知识库标识。

响应：

```json
{
  "code": 0,
  "msg": "论文任务创建成功",
  "data": {
    "task_id": "TASK-6AEB70D566ED",
    "title": "基于大语言模型的学位论文辅助写作研究",
    "degree": "MASTER",
    "subject_field": "计算机科学与技术",
    "session_id": "TASK-6AEB70D566ED",
    "current_ring": "RING_1",
    "status": "NOT_STARTED"
  }
}
```

## 3. 查询进度

```http
GET /api/v1/console/tasks/{task_id}/progress
```

关键字段：

```json
{
  "current_ring_no": 1,
  "phase_state": "NOT_STARTED",
  "complete_percent": 0.0,
  "can_execute": true,
  "can_confirm": false,
  "session_id": "TASK-6AEB70D566ED",
  "rings": []
}
```

| 状态 | 含义 | 可执行动作 |
|---|---|---|
| `NOT_STARTED` | 当前环尚未执行 | 执行当前环 |
| `IN_PROGRESS` | 兼容旧回退数据的可重试状态 | 执行当前环 |
| `WAITING_APPROVAL` | 产物已通过自动验收 | 确认或拒绝当前产物 |
| `FALLBACK` | 自动验收失败或作者拒绝 | 修订后重试，或回退 |
| `PASSED` | 十环已最终确认 | 下载和归档 |

## 4. 执行当前环

环1示例：

```http
POST /api/v1/console/tasks/{task_id}/rings/1/execute
Content-Type: application/json

{}
```

执行成功后不会进入环2，而是停在：

```json
{
  "current_ring_no": 1,
  "phase_state": "WAITING_APPROVAL",
  "can_execute": false,
  "can_confirm": true
}
```

自动验收失败时 `code != 0`，`data.fallbackTo` 可能给出建议回退环。失败时不得调用确认接口。

## 5. 确认当前环产物

```http
POST /api/v1/console/tasks/{task_id}/rings/1/confirm
Content-Type: application/json
```

接受：

```json
{ "confirmed": true }
```

环1确认成功后，`current_ring_no` 变为 2，`phase_state` 变为 `NOT_STARTED`。

拒绝：

```json
{
  "confirmed": false,
  "reject_reason": "研究范围过宽，需要缩小到医疗问答场景"
}
```

拒绝后仍停在当前环，状态为 `FALLBACK`，允许重新执行。

## 6. 十环执行路径

| 环 | 执行路径 |
|---|---|
| 1 选题 | `/rings/1/execute` |
| 2 开题评审 | `/rings/2/review` |
| 3 文献调研 | `/rings/3/execute` |
| 4 综述评审 | `/rings/4/review` |
| 5 大纲 | `/rings/5/outline` |
| 6 撰写 | `/rings/6/chapter` |
| 7 润色 | `/rings/7/polish` |
| 8 引用校验 | `/rings/8/validate` |
| 9 排版检查 | `/rings/9/layout` |
| 10 定稿汇总 | `/rings/10/final` |

每个路径前都加 `/api/v1/console/tasks/{task_id}`。每次执行成功后调用 `/rings/{ring_no}/confirm`；环10也必须最终确认。

## 7. docx 生成与下载

环8确认完成、任务进入环9后生成待排版文档：

```http
POST /api/v1/console/tasks/{task_id}/docx/generate
```

生成过早会返回非法状态。生成成功后执行环9排版检查。响应中的 `download_url` 可直接下载文档；docx 内容优先使用环7润色稿。

## 8. curl 最小严格流程

```bash
curl -s http://127.0.0.1:8000/healthz

curl -s -X POST http://127.0.0.1:8000/api/v1/console/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"测试论文","degree":"MASTER","subject_field":"软件工程","scope":"all"}'

curl -s -X POST http://127.0.0.1:8000/api/v1/console/tasks/TASK_ID/rings/1/execute \
  -H "Content-Type: application/json" -d '{}'

curl -s -X POST http://127.0.0.1:8000/api/v1/console/tasks/TASK_ID/rings/1/confirm \
  -H "Content-Type: application/json" -d '{"confirmed":true}'
```

可直接运行根目录 `demo_run.py` 验证最小流程；`demo_full_10.py` 会按同一协议运行十环，任何一步失败即停止。

## 9. 证据账本 API

所有路径都位于 `/api/v1/console/tasks/{task_id}`，并接受 `session_id` 查询参数。

| 动作 | 方法与路径 |
|---|---|
| 登记/列出来源 | `POST/GET /sources` |
| 登记/列出原文摘录 | `POST/GET /evidence` |
| 作者复核摘录 | `POST /evidence/{evidence_id}/review` |
| 登记/列出正文论断 | `POST/GET /claims` |
| 建立论断—证据关系 | `POST /claims/{claim_id}/links` |
| 检查证据覆盖和反证 | `GET /evidence-audit` |

证据摘录必须至少带 `page_start`、`section` 或 `char_start` 之一。只有复核状态为
`APPROVED` 的摘录才能链接到论断。

## 10. 研究与实验 API

| 动作 | 方法与路径 |
|---|---|
| 创建/列出论证图 | `POST/GET /research/argument-maps` |
| 审批论证图 | `POST /research/argument-maps/{artifact_id}/review` |
| 创建/列出研究协议 | `POST/GET /research/protocols` |
| 审批研究协议 | `POST /research/protocols/{artifact_id}/review` |
| 创建/列出实验运行 | `POST/GET /research/runs` |
| 推进实验状态并登记文件 | `POST /research/runs/{run_id}/transition` |
| 登记结果 | `POST /research/runs/{run_id}/results` |
| 核验结果 | `POST /research/results/{result_id}/review` |
| 研究实施审计 | `GET /research/audit` |
| 生成结果账本 | `POST /research/result-ledgers` |
| 审批结果账本 | `POST /research/result-ledgers/{artifact_id}/review` |

实证类标准顺序是：环5创建并批准协议 → 确认环5 → 创建运行 → 材料就绪 → 运行中 →
完成并提交真实性确认 → 登记并核验结果 → 生成并批准结果账本 → 执行环6。

## 11. 分节写作 API

| 动作 | 方法与路径 |
|---|---|
| 为一个大纲分节生成新版本 | `POST /writing/sections/generate` |
| 查看全部分节版本 | `GET /writing/sections` |
| 作者批准/驳回分节 | `POST /writing/sections/{section_draft_id}/review` |
| 检查是否全部分节已批准 | `GET /writing/sections-audit` |
| 汇编为环6正式初稿 | `POST /rings/6/assemble` |

生成请求至少包含 `section_id`；实证结果节可额外传 `result_ids`。系统只把该节论断、
批准证据及指定的已核验结果送入模型，不再把整个文献库塞入一次调用。

结果对象应使用 `[[BOOKMARK:TABLE-4-1|表4-1 实验结果]]` 定义目标；正文使用
`[[REF:TABLE-4-1|表4-1]]` 引用。环8和 DOCX 生成器会分别检查业务血缘与 OOXML 域，
生成响应中的 `cross_references` 返回书签数量、REF 数量、目标映射及未解决项。
