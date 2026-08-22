# API 调用示例

一期提供最小可运行闭环入口：健康检查 + 任务创建/查询（内存态骨架，不依赖数据库）。

Base URL：`http://localhost:8000`

## 1. 健康检查

```
GET /healthz
```

响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": { "service": "thesis-agent-dsh", "status": "UP", "ts": "2026-08-22T00:00:00.000000Z" },
  "traceId": null,
  "tenantId": "default"
}
```

## 2. 创建论文任务

```
POST /api/v1/tasks
Content-Type: application/json
```

请求体：

```json
{
  "title": "基于大语言模型的学位论文自动写作研究",
  "degree": "MASTER",
  "discipline": "计算机科学与技术",
  "session_id": "sess-2026-0001",
  "start_ring": "RING_1"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| title | string | 论文题目（必填） |
| degree | string | 学位层次：`BACHELOR` / `MASTER` / `PHD`（必填） |
| discipline | string? | 学科（可选） |
| session_id | string | 会话 ID（M9 知识隔离预留） |
| start_ring | string | 起始环节，默认 `RING_1` |

响应：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "task_id": "a1b2c3d4e5f6a7b8",
    "task_no": "THA1B2C3D4",
    "title": "基于大语言模型的学位论文自动写作研究",
    "degree": "MASTER",
    "discipline": "计算机科学与技术",
    "status": "NOT_STARTED",
    "current_ring": "RING_1",
    "session_id": "sess-2026-0001",
    "tenant_id": "default",
    "trace_id": null,
    "metadata": null
  },
  "traceId": null,
  "tenantId": "default"
}
```

## 3. 分页查询任务

```
GET /api/v1/tasks?page=1&size=20
```

响应（`data.items` 为 TaskSummary 数组）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": { "total": 1, "page": 1, "size": 20, "items": [ ... ] },
  "traceId": null,
  "tenantId": "default"
}
```

## 4. 查询单个任务

```
GET /api/v1/tasks/{task_id}
```

成功响应同上；任务不存在返回业务失败信封：

```json
{
  "code": 100001,
  "msg": "任务不存在: not-exist-id",
  "data": null,
  "traceId": null,
  "tenantId": "default"
}
```

## 5. curl 快速验证

```bash
# 健康检查
curl -s http://localhost:8000/healthz

# 创建任务
curl -s -X POST http://localhost:8000/api/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{"title":"测试论文","degree":"MASTER","discipline":"软件工程"}'
```
