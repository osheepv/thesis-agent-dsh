# thesis-agent-dsh

基于 DSH 的学位论文全流程写作 Agent —— 后端二期（真 LLM + 真实文献链路）。

> 当前：10 环节全流程闭环（选题→开题评审→文献调研→综述评审→大纲→撰写→润色→引用校验→排版→定稿），
> 全部接入真 LLM（DeepSeek 直调）+ 真实文献检索（Crossref/OpenAlex）。二期需求与轮子选型见
> [docs/二期需求与轮子选型分析.md](docs/二期需求与轮子选型分析.md)。

## 项目定位

依据《学位论文全流程标准化规范（本硕博）》（[docs/学位论文全流程标准化规范_本硕博.md](docs/学位论文全流程标准化规范_本硕博.md)）的 10 环节状态机（选题→新颖度→文献调研→文献综述→大纲→撰写→润色→引用校验→排版→定稿），把论文写作流程从"经验"抽象为"可执行、可校验、可回退"的 Agent 工作流；本硕博共用同一骨架，差异仅在各环验收阈值与创新要求。设计文档全集（系统设计/架构/部署/安全）见 `docs/design/`。

## 当前状态

**10 环节全部实现，真 LLM + 真实文献检索全链路闭环**：
- 环1/5/6/7 由 DeepSeek（`deepseek-v4-flash`）真实生成；环3 真实检索（Crossref + OpenAlex）；环2/4 新颖度/综述评审（真实查新拦截泛化题目）；环8 多源引用校验（伪引回退）；环9 docx 版式合规检查；环10 定稿汇总。
- 防编造护栏：环5/6 只能引用环3 检索池（`[L序号]`），环7 指纹守护（引用/数字保留率 <0.85 拒绝），文献未命中不编造。
- 持久化：SQLite 过渡（由 `THESIS_DB_URL` 控制，后期迁 PostgreSQL 改一行）。
- 测试：**98 个 pytest 全绿**（FSM/执行体/闭环/文献/评审/排版/定稿）。
- 一键全流程：`demo_full_10.py`（HTTP 走 API，跑完 10 环 + 下载成品 docx）与 `demo_run.py`（快速 6 步闭环）。

## 模块映射（严格对齐系统设计 M1~M9 应用落地层）

| 模块编号 | 模块名称 | 目录 | 一期状态 |
| --- | --- | --- | --- |
| M1 | FSM 编排器 | `backend/fsm/orchestrator/` | 骨架 |
| M4 | 状态存储 | `backend/fsm/state/`、`backend/fsm/repository/` | 骨架 |
| M2 | 环节执行体 | `backend/executor/` | 骨架（ring1/5/6） |
| M3 | 验收 Gate / HITL | `backend/hitl/` | 预留接口（环2/4/8/10） |
| M5 | docx 模板解析 | `backend/docx/parser/` | 骨架 |
| M6 | docx 生成校验 | `backend/docx/generator/`、`backend/docx/validator/` | 骨架 |
| M7 | 万方查重 | `backend/wanfang/` | 预留（二期，可信边界硬编码位已备） |
| M8 | Guardrail | `backend/guardrail/` | 预留（二期） |
| M9 | 知识库 | `backend/knowledge/` | 预留（二期，session_id 隔离数据结构已备） |
| 公共 | 公共模块 | `backend/common/aicoding/` | ✅ 已实现 |

## 环境准备

```bash
# 1. 创建 venv（若未创建）
python.exe -m venv C:/Users/欧阳威/.workbuddy/binaries/python/envs/default

# 2. 激活
# Windows (Git Bash / PowerShell)
source C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/activate
#  或直接使用 venv 内 python：
C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pip list

# 3. 安装依赖
cd backend
C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pip install -r requirements.txt
```

> 说明：一期 pytest 与 API 启动不依赖真实 PostgreSQL 实例（任务为内存态），
> 模型/DDL 仅用于二期 M4 持久化对接。安装 `psycopg2-binary`/`asyncpg` 需真实 PG 才能连库。

## 运行服务

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
# 或
python main.py
```

打开 http://localhost:8000/docs 查看 Swagger。

## 运行测试

```bash
# 项目根执行
# 若测试找不到包，先确认后台目录注入（tests/conftest.py 已处理）
C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pytest backend/../tests -v
# 或进入 backend 目录：
cd backend && C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pytest ../tests -v
```

## 数据库 DDL

PostgreSQL 16 原生语法（`GENERATED ALWAYS AS IDENTITY` / `BOOLEAN` / `CREATE INDEX` /
`tsvector` 生成列 + GIN），严格禁用 MySQL 语法。见 `backend/db/ddl.sql`。

```bash
psql -U <user> -d <db> -f backend/db/ddl.sql
```

核心表：`t_task`、`t_fsm_state`、`t_outline`、`t_chapter_draft`、`t_docx_template`，
以及 M9 预留的 `t_kb_collection` / `t_kb_document` / `t_kb_chunk`（session 强绑定）。

## 技术栈（锁定版本，见 backend/requirements.txt）

Python 3.12+ · FastAPI 0.115.12 · SQLAlchemy 2.0.41 · PostgreSQL 16 ·
Redis 7.2 · docxtpl 0.17.4 · openxml-audit 0.7.5 · APScheduler 3.11.0 · pytest 8.3.5

## API 示例

见 `docs/api_examples.md`。
