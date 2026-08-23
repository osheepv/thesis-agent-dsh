# thesis-agent-dsh

学位论文全流程智能写作工作台的工程化原型：FastAPI 后端、十阶段状态机、文献与知识库基础、docx 管线和桌面式 Web UI。

> 准确定位：项目已经具备可信的十阶段控制流，但还不是可稳定交付完整本/硕/博论文的成品。当前重点是把整批生成改造成可编辑、可版本化、逐条绑定证据的分节写作系统。产品边界和建设路线见 [产品架构蓝图](docs/产品架构蓝图.md)，界面规范见 [DESIGN.md](DESIGN.md)。

## 项目定位

依据《学位论文全流程标准化规范（本硕博）》（[docs/学位论文全流程标准化规范_本硕博.md](docs/学位论文全流程标准化规范_本硕博.md)）的 10 环节状态机，把论文写作从经验流程抽象为可执行、可校验、可回退、可人工确认的工作流。本硕博共用同一骨架，通过验收阈值、引用深度、大纲层级与最低字数要求体现差异。

## 当前状态

当前已落地：

- 十环执行体已接入主编排；每一环都严格执行“生成产物 → 自动验收 → `WAITING_APPROVAL` → 用户确认 → 下一环”。
- 跨环执行、无产物推进和重复执行待确认环都会被拒绝；环10最终确认后进度为 100%。
- 正式模式默认关闭静默 Mock。模型未配置或调用失败时明确报错；测试/演示需要显式开启 Mock。
- 环3支持 Crossref、OpenAlex、Semantic Scholar 等来源及中文检索引导；空文献池不再被当成成功。
- 环8无可核验引用时失败，环10材料缺失时失败；外部元数据命中不等同于全文事实已核验。
- 知识库与会话 1:1 绑定，包含文献文件、笔记、双链、图谱和本地 RAG 基础。
- 任务、各环产物和 FSM 状态使用 SQLite 持久化；docx 生成、下载与版式检查已串联。
- 阶段审批通过事务 Outbox 投影为不可变版本产物；上游改版会递归将下游标记为过期。
- 已实现来源、可定位摘录、论断和证据链接账本；未经作者复核的摘录不能支撑正文论断。
- 已实现研究协议、实验运行状态机、原始材料血缘和结果账本；实证类任务未批准结果账本时禁止生成初稿。
- 已实现论证图的有向无环校验与审批；核心论断自动登记到证据账本，大纲对论证版本建立依赖。
- 环6支持按节最小上下文生成、独立版本、自动验收、逐节审批和完整性汇编；上游失效会使相关分节过期。
- 新分节链路的环8会审计正文证据/结果标记，生成稳定引文编号、GB/T 7714参考文献和结果交叉引用清单。
- DOCX 生成器会把明确的 `BOOKMARK/REF` 标记转换为 Word 原生书签与 `REF` 域，并在交付前验证目标完整性；内置模板已修复为严格 OOXML 校验通过。
- 长耗时环执行、分节生成和 DOCX 生成可进入持久化 JobRun；支持幂等入队、Worker 租约/心跳、崩溃恢复、协作取消、失败重试及 Token/费用预算。
- 前端支持十环进度、人工确认闸门、后台作业与预算、证据/论证审计、分节生成/修订/审批，以及刷新后的状态恢复。
- 研究工作台可视化创建并审批研究协议/论证图，上传实验材料、原始数据、代码和日志，推进实验状态、登记/核验结果及批准结果账本。
- 分节工作台可选择任意两个版本进行双栏行级差异比较；学校 DOCX 模板会持久化并支持中英文占位符映射，未映射字段会阻断生成。
- `demo_run.py` 提供最小严格流程冒烟；`demo_full_10.py` 按真实闸门协议运行，任一环失败即停止。

当前关键缺口：

- 结构化表格/图片编辑器、复杂公式管线和学校模板样式差异诊断仍待完成。
- UI 仍是单文件原型；桌面打包、独立 Worker 运维和生产级权限尚未完成。
- 需要补充系统化模型评测、提示词回归和真实长论文压力测试。

## 模块映射（对齐系统设计 M1~M9 落地状态）

| 模块编号 | 模块名称 | 目录 | 状态 |
| --- | --- | --- | --- |
| M1 | FSM 编排器 | `backend/fsm/orchestrator/` | ✅ 已实现（10 环状态机 + HITL 闸门 + 回退） |
| M2 | 环节执行体 | `backend/executor/`、`backend/writing/` | 🟡 十环、证据约束分节写作、修订审批和汇编已接入；版本差异待建设 |
| M3 | 验收 Gate / HITL | `backend/fsm/` | ✅ 执行/验收/确认分离，所有环人工确认 |
| M4 | 状态存储 | `backend/db/`、`backend/fsm/repository/` | ✅ SQLite（任务/环产物/FSM 状态） |
| M5/M6 | docx 解析/生成 | `backend/thesis_docx/` | ✅ 用户模板持久化/映射、docxtpl、版式检查、原生书签/REF 域及严格 OOXML 验证 |
| M7 | 查重 | — | 预留（OOS：只提醒人工自建查重） |
| M8 | Guardrail | `backend/common/`、`backend/evidence/`、`backend/research/` | ✅ 来源/摘录/论断、结果血缘、环8强制审计和 DOCX 域验证 |
| M9 | 知识库 | `backend/knowledge/` | ✅ 已实现（文件池/笔记双链/图谱 API + RAG 检索） |
| 执行治理 | JobRun/预算 | `backend/jobs/` | ✅ 持久化队列、租约恢复、取消重试、Token/费用登记 |
| 公共 | 公共模块 | `backend/common/` | ✅ 已实现（LLM 客户端 / 文献服务 / 引用格式化 / 提示词仓库） |

## 环境准备

```bash
python -m venv .venv
# PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
```

默认使用 SQLite，不需要 PostgreSQL。真实模型与文献服务由环境变量启用。

## 运行服务

```bash
cd backend
# 必须先配置 .env（复制 .env.example 并填 DeepSeek key）
python -m uvicorn application.main:app --host 127.0.0.1 --port 8000
```

打开 http://127.0.0.1:8000/docs 查看 Swagger。

**前端 UI**（Claude 桌面风格界面，独立端口）：

```bash
# 用任意静态服务器托管 ui/index.html（如 VSCode Live Server / python -m http.server）
cd ui
python -m http.server 8787
```

浏览器打开 http://localhost:8787（后端 8000 需同时运行）。

## 运行测试

当前回归基线：**184 项 pytest 全部通过**。

```bash
# 项目根执行（conftest 自动注入路径）
python -m pytest tests -v
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

Python 3.13 · FastAPI 0.115.12 · SQLAlchemy 2.0.41 · SQLite（过渡；后期可迁 PostgreSQL）·
OpenAI 兼容模型客户端（模型名由环境配置）· docxtpl 0.20.2 · openxml-audit 0.7.5 ·
sentence-transformers 3.4.1（BAAI/bge-small-zh-v1.5 本地嵌入，RAG 零成本）· pypdf ·
Cytoscape.js 3.30.2（知识图谱）· pytest 8.3.5

## 环境变量

后端读取 `backend/.env`（模板见 `backend/.env.example`，**.env 严禁提交 git**）：
`THESIS_DEEPSEEK_API_KEY` / `THESIS_DEEPSEEK_FALLBACK_TO_MOCK` / `THESIS_DB_URL` / `THESIS_LIT_ENABLED` / `THESIS_LIT_SCOPE` /
`THESIS_METASO_ENABLED`（默认 false，省钱）/ `THESIS_RAG_ENABLED` / `THESIS_CORS_ORIGINS` /
`THESIS_TASK_STORE_MEMORY`（测试用）/ `THESIS_ARTIFACT_DB` / `THESIS_EVIDENCE_DB` /
`THESIS_RESEARCH_DB` / `THESIS_SECTION_DB` / `THESIS_JOB_DB` /
`THESIS_JOB_WORKER_ENABLED` / `THESIS_LLM_INPUT_COST_PER_MILLION` /
`THESIS_LLM_OUTPUT_COST_PER_MILLION` / `THESIS_KB_MAX_FILE_MB`。

## API 示例

见 `docs/api_examples.md`。
