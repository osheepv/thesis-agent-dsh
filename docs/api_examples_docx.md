# M5/M6 docx 业务包 API 调用示例

本文档描述 **M5/M6 docx 业务包**（模块名 `backend.thesis_docx`）的 HTTP 接口调用方式。
docx 业务以独立模块提供，路由统一挂 `/api/v1` 前缀，由 `backend.thesis_docx.router` 导出
（经 `application.main` 探测挂载）。

> 说明：本包已与 pip 的 python-docx 库（顶层名 `docx`）**解同名**，统一使用
> `backend.thesis_docx` 命名空间导入；`import docx` 固定解析到 python-docx 库。
> 本文档示例基于内存仓储演示，生产环境替换为 SQLAlchemy 仓储后响应体结构不变。

Base URL：`http://localhost:8000`

所有端点返回统一信封 `Result[T]`（`code/msg/data/traceId/tenantId`，`code=0` 表示成功）。

---

## 1. 上传并解析 docx 模板

```
POST /api/v1/templates/upload
Content-Type: multipart/form-data
```

表单参数：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| file | file | 模板 `.docx` 文件（必填，仅允许 `.docx`，大小 ≤ 50MB，魔数须为 ZIP） |
| session_id | string | 会话 ID（可选，会话绑定式隔离） |
| task_id | int | 关联任务 ID（可选） |

响应（`data` 为 TemplateUploadResult）：

```json
{
  "code": 0,
  "msg": "模板上传并解析成功",
  "data": {
    "template_id": "3f2c7a1e5b9d4c8f",
    "template_name": "学位论文模板.docx",
    "filename": "学位论文模板.docx",
    "placeholders": ["topic", "outline", "chapter", "degree"],
    "section_count": 3,
    "parse_status": "PARSED",
    "file_hash": "6f1d8d3a5b2c4e7f90ab12cd34ef567890ab12cd34ef567890ab12cd34ef56",
    "meta": {
      "skeleton_sections": [
        { "index": 0, "heading": "摘要", "placeholder": "", "level": 1, "paragraph_count": 3 },
        { "index": 1, "heading": "{ { chapter } }", "placeholder": "chapter", "level": 1, "paragraph_count": 0 }
      ]
    }
  },
  "traceId": null,
  "tenantId": "default"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| template_id | string | 模板 ID（uuid hex） |
| template_name | string | 用户上传的原始文件名 |
| filename | string | 模板文件名（与 template_name 同，兼容别名） |
| placeholders | string[] | Jinja2 占位符列表（去重、按出现顺序） |
| section_count | int | 骨架章节数量 |
| parse_status | string | 解析状态：`PARSED` / `FAILED` |
| file_hash | string | 模板文件 SHA-256 |
| meta | object | 附加元信息（含 skeleton_sections 骨架章节结构） |

安全校验失败（如含宏 / 扩展名非法）时返回业务失败信封：

```json
{
  "code": 500002,
  "msg": "仅支持 .docx 模板，收到扩展名为 .docm",
  "data": { "detail": { "extension": ".docm", "allowed": [".docx"] } },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 2. 模板详情 / 占位符

```
GET /api/v1/templates/{template_id}?session_id=sess-2026-0001
```

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| template_id | string | 模板 ID（路径参数） |
| session_id | string | 会话 ID（可选，按会话归属校验） |

响应（`data` 为 TemplateDetailVO）：

```json
{
  "code": 0,
  "msg": "ok",
  "data": {
    "template_id": "3f2c7a1e5b9d4c8f",
    "template_name": "学位论文模板.docx",
    "session_id": "sess-2026-0001",
    "placeholders": ["topic", "outline", "chapter", "degree"],
    "placeholders_detail": {
      "count": 4,
      "items": ["topic", "outline", "chapter", "degree"]
    },
    "skeleton_sections": [
      { "index": 0, "heading": "摘要", "placeholder": "", "level": 1, "paragraph_count": 3 },
      { "index": 1, "heading": "{ { chapter } }", "placeholder": "chapter", "level": 1, "paragraph_count": 0 }
    ],
    "parse_status": "PARSED",
    "created_at": "2026-08-22T01:00:28.584030"
  },
  "traceId": null,
  "tenantId": "default"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| template_id | string | 模板 ID |
| template_name | string | 模板文件名 |
| session_id | string | 会话 ID（归属校验） |
| placeholders | string[] | 占位符列表 |
| placeholders_detail | object | 占位符 -> 出现位置（`count` + `items`） |
| skeleton_sections | object[] | 骨架章节结构（SectionSkeleton） |
| parse_status | string | 解析状态 |
| created_at | string | 创建时间（ISO，可空） |

模板不存在或不属于当前会话时：

```json
{
  "code": 100004,
  "msg": "论文模板不存在",
  "data": { "detail": { "template_id": "not-exist-id" } },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 3. 按模板 + 内容生成 docx

```
POST /api/v1/docx/generate
Content-Type: application/json
```

请求体（DocxGenerateRequest）：

```json
{
  "template_id": "3f2c7a1e5b9d4c8f",
  "session_id": "sess-2026-0001",
  "content": {
    "topic": "基于大语言模型的学位论文自动写作研究",
    "outline": "1 绪论\n  1.1 研究背景\n1.2 研究意义",
    "chapter": "# 第1章 绪论\n\n本文围绕……",
    "degree": "MASTER",
    "subject_field": "计算机科学与技术"
  },
  "filename": "my_thesis.docx"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| template_id | string | 使用的模板 ID（必填） |
| session_id | string | 会话 ID（可选，归属校验） |
| content | object | 占位符 -> 内容映射，键为占位符名（如 `topic`/`outline`/`chapter`），值为代入文本 |
| filename | string? | 生成文件名（可选，默认 `<template_name>_render.docx`，缺 `.docx` 自动补齐） |

> 说明：`content` 是单一键值映射字典，**没有** 顶层 `outline`/`chapter` 字段。
> 上层主编排（`MainOrchestration.generate_docx`）即以其为内容映射，注入
> `topic`/`title`/`outline`/`chapter`/`content`/`degree`/`subject_field` 等键。

响应（`data` 为 DocxGenerateResult）：

```json
{
  "code": 0,
  "msg": "docx 生成成功",
  "data": {
    "file_id": "4a1b2c3d5e6f7890",
    "download_url": "/api/v1/docx/files/4a1b2c3d5e6f7890",
    "filename": "my_thesis.docx",
    "word_count": 18234,
    "file_hash": "ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef56ab12cd34ef567890",
    "validate": {
      "is_valid": true,
      "schema_valid": true,
      "load_valid": true,
      "roundtrip_valid": true,
      "error_count": 0,
      "warning_count": 0,
      "errors": [],
      "warnings": [],
      "validator": "openxml-audit-0.1.0",
      "file_id": ""
    }
  },
  "traceId": null,
  "tenantId": "default"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| file_id | string | 生成文件 ID（uuid hex） |
| download_url | string | 下载链接（对应 §5 下载接口） |
| filename | string | 生成文件名 |
| word_count | int | 估算字数（剔除空白字符） |
| file_hash | string | 生成文件 SHA-256 |
| validate | object | 生成后即校验的快照（DocxValidateResult，见 §4） |

生成后校验不通过时拒绝交付（遗留产物被清理），返回业务失败信封：

```json
{
  "code": 500003,
  "msg": "生成 docx 未通过校验（errors=3），已拒绝交付",
  "data": { "detail": { "errors": [], "missing_keys": ["abstract"] } },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 4. 校验 docx

```
POST /api/v1/docx/validate?file_id=4a1b2c3d5e6f7890&session_id=sess-2026-0001&strict=true
```

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| file_id | string | 待校验文件 ID（必填，须在 docx 输出域内存在） |
| session_id | string | 会话 ID（可选，归属校验） |
| strict | bool | 是否严格 schema/semantic 校验，默认 `true` |

> 说明：路由以独立 query/form 参数接收 `file_id` / `session_id` / `strict`；
> 未使用 DocxValidateRequest 作为单一请求体。

响应（`data` 为 DocxValidateResult）：

```json
{
  "code": 0,
  "msg": "校验完成",
  "data": {
    "is_valid": true,
    "schema_valid": true,
    "load_valid": true,
    "roundtrip_valid": true,
    "error_count": 0,
    "warning_count": 0,
    "errors": [],
    "warnings": [],
    "validator": "openxml-audit-0.1.0",
    "file_id": "4a1b2c3d5e6f7890"
  },
  "traceId": null,
  "tenantId": "default"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| is_valid | bool | 是否通过校验（schema + load + roundtrip 三项均通过） |
| schema_valid | bool | OOXML schema/semantic 校验是否通过 |
| load_valid | bool | 能否被目标应用加载（python-docx 重开） |
| roundtrip_valid | bool | roundtrip（保存重载）校验是否通过 |
| error_count | int | 错误数 |
| warning_count | int | 警告数 |
| errors | object[] | 错误明细（`severity`/`description`/`part`/`id`/`node`） |
| warnings | object[] | 警告明细 |
| validator | string | 使用的校验器版本（如 `openxml-audit-0.1.0`） |
| file_id | string | 被校验文件 ID |

校验未通过时：

```json
{
  "code": 0,
  "msg": "校验未通过",
  "data": {
    "is_valid": false,
    "schema_valid": false,
    "load_valid": true,
    "roundtrip_valid": true,
    "error_count": 1,
    "warning_count": 0,
    "errors": [
      { "severity": "ERROR", "description": "invalid attribute", "part": "/word/document.xml", "id": "", "node": "" }
    ],
    "warnings": [],
    "validator": "openxml-audit-0.1.0",
    "file_id": "4a1b2c3d5e6f7890"
  },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 5. 下载生成产物

```
GET /api/v1/docx/files/{file_id}?session_id=sess-2026-0001
```

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| file_id | string | 生成文件 ID（路径参数） |
| session_id | string | 会话 ID（可选，归属校验） |

成功：直接返回 `FileResponse`，`Content-Type` 为
`application/vnd.openxmlformats-officedocument.wordprocessingml.document`，
响应体为 `.docx` 二进制流（对应 §3 返回的 `download_url`）。

文件不存在时返回业务失败信封：

```json
{
  "code": 5,
  "msg": "生成文件不存在",
  "data": { "detail": { "file_id": "4a1b2c3d5e6f7890" } },
  "traceId": null,
  "tenantId": "default"
}
```

---

## 附注：聚合闭环入口（写作者工作台）

上文 §1~§5 为 `backend.thesis_docx.router` 直接暴露的 docx 业务端点。实际渲染路径会回退到
python-docx 内置 `default.docx` 模板（见 `backend/application/service/uc_main_orchestration.py`
的 `RealDocxRenderer.generate()`）：未提供用户模板落盘路径时，回退到
`.venv/python-docx/templates/default.docx` 完成「无模板也能生成」的契约。

聚合闭环层另有统一入口，作为写作者工作台的编排面（`backend/application/controller/writer_console.py`，
前缀 `/api/v1/console`）：

```
POST /api/v1/console/tasks/{task_id}/docx/generate
```

该端点走主编排 `MainOrchestration.generate_docx()`，把「环1选题 → 环5大纲 → 环6撰写 → 生成 docx」
串成闭环，返回 `Result[Any]`（`data` 含 `file_id` / `download_url` / `filename` / `word_count`）。

---

## 错误码速查

| code | 含义 |
| --- | --- |
| 000002 | 参数不合法（INVALID_PARAM） |
| 000004 | 无权限 / 资源不属于当前会话（FORBIDDEN） |
| 000005 | 资源不存在（NOT_FOUND） |
| 100004 | 论文模板不存在（TEMPLATE_NOT_FOUND） |
| 500001 | docx 解析失败（DOCX_PARSE_FAILED） |
| 500002 | docx 模板非法（DOCX_TEMPLATE_INVALID） |
| 500003 | docx 生成失败（DOCX_GENERATE_FAILED） |
| 500004 | docx 校验失败（DOCX_VALIDATE_FAILED） |
