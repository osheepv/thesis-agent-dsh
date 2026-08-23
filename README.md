# thesis-agent-dsh

基于 DSH 的学位论文全流程写作 Agent —— 后端（真 LLM + 真实文献链路）+ Claude 风格桌面 UI。

> 当前：10 环节全流程闭环（选题→开题评审→文献调研→综述评审→大纲→撰写→润色→引用校验→排版→定稿），
> 全部接入真 LLM（DeepSeek 直调）+ 真实文献检索（Crossref/OpenAlex/Semantic Scholar + 中文引导层 NCPSSD/ChinaXiv），
> 附本地零成本 RAG 语义检索与双链知识库。二期需求与轮子选型见
> [docs/二期需求与轮子选型分析.md](docs/二期需求与轮子选型分析.md)。

## 项目定位

依据《学位论文全流程标准化规范（本硕博）》（[docs/学位论文全流程标准化规范_本硕博.md](docs/学位论文全流程标准化规范_本硕博.md)）的 10 环节状态机（选题→新颖度→文献调研→文献综述→大纲→撰写→润色→引用校验→排版→定稿），把论文写作流程从"经验"抽象为"可执行、可校验、可回退"的 Agent 工作流；本硕博共用同一骨架，差异仅在各环验收阈值与创新要求。设计文档全集（系统设计/架构/部署/安全）见 `docs/design/`。

## 当前状态

**10 环节全部实现，真 LLM + 真实文献检索全链路闭环**：
- 环1/5/6/7 由 DeepSeek（`deepseek-v4-flash`）真实生成；环3 真实检索（Crossref + OpenAlex + Semantic Scholar，中文期刊走 NCPSSD/ChinaXiv 引导层）；环2/4 新颖度/综述评审（真实查新拦截泛化题目）；环8 多源引用校验（伪引回退）；环9 docx 版式合规检查；环10 定稿汇总。
- 防编造护栏：环5/6 只能引用环3 检索池（`[L序号]`）+ 知识库 RAG 语义块（`[KB]`），环7 指纹守护（引用/数字保留率 <0.85 拒绝），文献未命中不编造。
- 标准检索通道：源注册表（Source Registry）按 scope（english/chinese/all）路由——新建对话可选检索范围并持久化；英文 scope 自动过滤中文期刊条目。
- **RAG 语义检索**：知识库文献（PDF/txt/md）自动全文切块 + 本地嵌入（BAAI/bge-small-zh-v1.5，约 100MB 装一次永久免费）+ numpy 余弦检索，写作时注入 Top-K 相关段落到 prompt——零 API 成本，用户本地出算力。
- **M9 知识库**：会话 1:1 强绑定（对话=知识库）；文献池（上传/复制 GB/T 7714/下载/删除）、笔记（contenteditable 编辑器 + `[[双链]]`）、知识图谱（Cytoscape.js，Obsidian Graph View 风格：hover 邻接高亮 / BFS 跳数视图 / 节点详情抽屉）。
- 提示词模板化：`backend/prompts/*.md`（SYSTEM+USER 文本，改文案不碰代码）。
- 持久化：任务列表+各环产物落 SQLite（`task_store.db`，重启不丢）；FSM 状态 SQLite 过渡（`THESIS_DB_URL` 控制，后期迁 PostgreSQL 改一行）。
- 前端 UI：`ui/index.html`（单文件，Claude Code 桌面版风格——Claude 官方配色 / 对话级 10 环进度条 / 每环确认闸门双重验证 / 会话=知识库关联）。
- CI：GitHub Actions（`.github/workflows/main.yml`），push 自动跑 125 用例。
- 测试：**125 个 pytest 全绿**（FSM/执行体/闭环/文献/评审/排版/定稿/RAG/持久化/提示词模板）。
- 一键全流程：`demo_full_10.py`（HTTP 走 API，跑完 10 环 + 下载成品 docx）与 `demo_run.py`（快速 6 步闭环）。

## 模块映射（对齐系统设计 M1~M9 落地状态）

| 模块编号 | 模块名称 | 目录 | 状态 |
| --- | --- | --- | --- |
| M1 | FSM 编排器 | `backend/fsm/orchestrator/` | ✅ 已实现（10 环状态机 + HITL 闸门 + 回退） |
| M2 | 环节执行体 | `backend/executor/` | ✅ 已实现（环1~10 全部，LLM 优先 + Mock 回退） |
| M3 | 验收 Gate / HITL | `backend/fsm/` | ✅ 已实现（每环人工确认闸门，双重验证） |
| M4 | 状态存储 | `backend/db/`、`backend/fsm/repository/` | ✅ SQLite（任务/环产物/FSM 状态） |
| M5/M6 | docx 解析/生成 | `backend/thesis_docx/` | ✅ 已实现（docxtpl + 版式检查器） |
| M7 | 查重 | — | 预留（OOS：只提醒人工自建查重） |
| M8 | Guardrail | `backend/common/` | 部分（防编造护栏：池引用白名单 + 指纹守护） |
| M9 | 知识库 | `backend/knowledge/` | ✅ 已实现（文件池/笔记双链/图谱 API + RAG 检索） |
| 公共 | 公共模块 | `backend/common/` | ✅ 已实现（LLM 客户端 / 文献服务 / 引用格式化 / 提示词仓库） |

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
# 必须先配置 .env（复制 .env.example 并填 DeepSeek key）
C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m uvicorn application.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs 查看 Swagger。

**前端 UI**（Claude 桌面风格界面，独立端口）：

```bash
# 用任意静态服务器托管 ui/index.html（如 VSCode Live Server / python -m http.server）
cd ui && C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m http.server 8787
```

浏览器打开 http://localhost:8787（后端 8000 需同时运行）。

## 运行测试

```bash
# 项目根执行（conftest 自动注入路径）
C:/Users/欧阳威/.workbuddy/binaries/python/envs/default/Scripts/python.exe -m pytest tests -v
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

Python 3.13 · FastAPI 0.115.12 · SQLAlchemy 2.0.41 · SQLite（过渡；后期迁 PostgreSQL）·
DeepSeek（`deepseek-v4-flash`，openai SDK 直调）· docxtpl 0.20.2 · openxml-audit 0.7.5 ·
sentence-transformers 3.4.1（BAAI/bge-small-zh-v1.5 本地嵌入，RAG 零成本）· pypdf ·
Cytoscape.js 3.30.2（知识图谱）· pytest 8.3.5

## 环境变量

后端读取 `backend/.env`（模板见 `backend/.env.example`，**.env 严禁提交 git**）：
`THESIS_DEEPSEEK_API_KEY`（必填）/ `THESIS_DB_URL` / `THESIS_LIT_ENABLED` / `THESIS_LIT_SCOPE` /
`THESIS_METASO_ENABLED`（默认 false，省钱）/ `THESIS_RAG_ENABLED` / `THESIS_CORS_ORIGINS` / `THESIS_TASK_STORE_MEMORY`（测试用）。

## API 示例

见 `docs/api_examples.md`。
