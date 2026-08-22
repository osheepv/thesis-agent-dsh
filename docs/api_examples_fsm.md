# FSM 编排器 API 调用示例

本文档描述 **M1 FSM 编排器** 的 HTTP 接口调用方式。FSM 服务以独立模块提供，
其路由严格对齐 `backend/application/adapters/route_config.py` 的 M1 内部路由契约
（无 `/api/v1` 前缀，便于 `application.adapters.m1_fsm_client.FsmClient` 直连）。

若要对**对外主应用**暴露带版本前缀的版本，可调用 `build_fsm_router(prefix="/api/v1")`，
路径即为 `/api/v1/tasks/...`。

> 说明：本文档中的示例基于**内存仓储（InMemoryFsmRepository）** 演示，
> 生产环境替换为 `SqlAlchemyFsmRepository` + PostgreSQL 后，响应体结构不变。

Base URL（FSM 服务示例挂载）：`http://localhost:8001`

---

## 1. 创建论文任务

```
POST /tasks
Content-Type: application/json
```

请求体：

```json
{
  "title": "基于大语言模型的学位论文自动写作研究",
  "degree": "MASTER",
  "subject_field": "计算机科学与技术",
  "template_id": "TPL-001",
  "session_id": "sess-2026-0001"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| title | string | 论文题目（必填） |
| degree | string | 学位层次：`BACHELOR` / `MASTER` / `PHD`（必填） |
| subject_field | string | 学科方向（可选） |
| template_id | string | 论文模板 ID（可选） |
| session_id | string | 会话 ID（M9 知识隔离预留） |

响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "task_id": "TASK-6AEB70D566ED",
    "title": "基于大语言模型的学位论文自动写作研究",
    "degree": "MASTER",
    "degree_label": "硕士",
    "subject_field": "计算机科学与技术",
    "template_id": "TPL-001",
    "current_ring_no": 1,
    "current_ring": "RING_1",
    "current_ring_label": "选题",
    "prev_ring_no": null,
    "phase_state": "NOT_STARTED",
    "hitl_confirmed": false,
    "hitl_required": false,
    "artifacts": {},
    "aux_artifacts": {},
    "rollback_stack_size": 0,
    "is_finished": false,
    "created_at": "2026-08-22T01:00:28.584030",
    "updated_at": "2026-08-22T01:00:28.584032"
  },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 2. 查询任务详情

```
GET /tasks/{task_id}
```

响应（示例，已推进到环2、处于 HITL 等待人工确认）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "task_id": "TASK-6AEB70D566ED",
    "current_ring_no": 2,
    "current_ring": "RING_2",
    "current_ring_label": "开题评审",
    "phase_state": "IN_PROGRESS",
    "hitl_required": true,
    "hitl_confirmed": false,
    "prev_ring_no": 1,
    "rollback_stack_size": 1,
    "is_finished": false,
    "artifacts": { "1": "doc://topic.json" }
  },
  "traceId": null,
  "tenantId": "default"
}
```

任务不存在时返回业务失败信封：

```json
{
  "code": 100001,
  "msg": "任务不存在: not-exist-id",
  "data": { "code": 100001, "msg": "任务不存在: not-exist-id", "detail": null },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 3. 推进当前环节（幂等）

```
POST /tasks/{task_id}/advance
Content-Type: application/json
```

请求体：

```json
{
  "biz_req_no": "REQ-2026-0001",
  "accept": true,
  "artifact_uri": "doc://topic.json",
  "gate_rule": "internal_acceptance",
  "session_id": "sess-2026-0001"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| biz_req_no | string | 幂等请求号（必填，同一请求号重复调用不会重复推进） |
| accept | bool | 验收是否通过，默认 `true` |
| reject_reason | string? | 驳回原因（`accept=false` 时必填） |
| artifact_uri | string? | 主产物 URI（同步产物） |
| gate_rule | string | 验收看门规则名，默认 `internal_acceptance` |

通过时（环1 → 环2）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "current_ring_no": 2,
    "current_ring": "RING_2",
    "phase_state": "IN_PROGRESS",
    "hitl_required": true,
    "hitl_confirmed": false,
    "prev_ring_no": 1,
    "artifacts": { "1": "doc://topic.json" },
    "rollback_stack_size": 1
  }
}
```

拒绝时（阶段态置 FALLBACK，不推进）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "current_ring_no": 1,
    "phase_state": "FALLBACK",
    "rollback_stack_size": 0
  }
}
```

---

## 4. 回退到目标环节

```
POST /tasks/{task_id}/rollback
Content-Type: application/json
```

请求体：

```json
{ "target_ring_no": 1 }
```

响应（回退到环1）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "current_ring_no": 1,
    "current_ring": "RING_1",
    "phase_state": "NOT_STARTED",
    "prev_ring_no": null,
    "rollback_stack_size": 0
  }
}
```

目标环节非法（`target_ring_no >= 当前环节`）时：

```json
{
  "code": 300001,
  "msg": "目标环节需小于当前环节 2",
  "data": null
}
```

---

## 5. 查询学位路由参数

```
GET /tasks/{task_id}/route
```

响应（硕士，十环节全程差异配置）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "total_rings": 10,
    "routes": [
      { "ring": "RING_1", "ring_no": 1, "label": "选题", "innovation_level": "MEDIUM",
        "citation_depth": 0, "outline_depth": 1, "required_outline_levels": 1,
        "hitl_required": false, "min_word_requirement": 1000, "is_hitl_gate": false },
      { "ring": "RING_4", "ring_no": 4, "label": "综述评审", "innovation_level": "MEDIUM",
        "citation_depth": 40, "outline_depth": 2, "required_outline_levels": 2,
        "hitl_required": true, "min_word_requirement": 12000, "is_hitl_gate": true },
      { "ring": "RING_5", "ring_no": 5, "label": "大纲生成", "innovation_level": "MEDIUM",
        "citation_depth": 0, "outline_depth": 3, "required_outline_levels": 3,
        "hitl_required": false, "min_word_requirement": 30000, "is_hitl_gate": false },
      "..." 
    ]
  }
}
```

> 不同学位的差异点：环1 `innovation_level`（本科 LOW / 硕士 MEDIUM / 博士 HIGH）、
> 环4 `citation_depth`（20 / 40 / 80）、环5 `outline_depth`（2 / 3 / 4）。

---

## 6. 查询十环节进度

```
GET /tasks/{task_id}/progress
```

响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "task_id": "TASK-6AEB70D566ED",
    "total_rings": 10,
    "current_ring_no": 2,
    "current_ring": "RING_2",
    "degree": "MASTER",
    "complete_percent": 10.0,
    "rings": [
      { "ring_no": 1, "ring": "RING_1", "label": "选题", "state": "PASSED", "is_hitl_gate": false, "hitl_required": false },
      { "ring_no": 2, "ring": "RING_2", "label": "开题评审", "state": "IN_PROGRESS", "is_hitl_gate": true, "hitl_required": true },
      { "ring_no": 3, "ring": "RING_3", "label": "文献综述", "state": "NOT_STARTED", "is_hitl_gate": false, "hitl_required": false }
    ]
  }
}
```

---

## 7. HITL 人工确认（M3 网关预留）

```
POST /tasks/{task_id}/hitl/confirm
Content-Type: application/json
```

请求体：

```json
{ "confirmed": true, "session_id": "sess-2026-0001" }
```

人工通过环2后推进到环3：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "current_ring_no": 3,
    "current_ring": "RING_3",
    "phase_state": "NOT_STARTED",
    "hitl_required": false,
    "hitl_confirmed": true
  }
}
```

---

## 8. curl 快速验证（独立 FSM 服务）

```bash
# 1. 创建任务
curl -s -X POST http://localhost:8001/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"测试论文","degree":"MASTER","subject_field":"软件工程"}'

# 2. 推进环1 -> 环2（幂等键）
curl -s -X POST http://localhost:8001/tasks/<task_id>/advance \
  -H "Content-Type: application/json" \
  -d '{"biz_req_no":"REQ-1","accept":true,"artifact_uri":"doc://topic.json"}'

# 3. 查询学位路由
curl -s http://localhost:8001/tasks/<task_id>/route

# 4. 查询进度
curl -s http://localhost:8001/tasks/<task_id>/progress

# 5. 回退到环1
curl -s -X POST http://localhost:8001/tasks/<task_id>/rollback \
  -H "Content-Type: application/json" \
  -d '{"target_ring_no":1}'
```

---

## 错误码速查

| code | 含义 |
| --- | --- |
| 000002 | 参数不合法（INVALID_PARAM） |
| 100001 | 任务不存在（TASK_NOT_FOUND） |
| 100003 | 任务已存在（TASK_ALREADY_EXISTS） |
| 300001 | FSM 非法流转（FSM_INVALID_TRANSITION） |
| 300002 | FSM 当前环节校验失败 |
| 300003 | 验收被拒绝（FSM_ACCEPTANCE_REJECTED） |
