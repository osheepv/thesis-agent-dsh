# thesis-agent-dsh

[![CI](https://github.com/osheepv/thesis-agent-dsh/actions/workflows/main.yml/badge.svg)](https://github.com/osheepv/thesis-agent-dsh/actions/workflows/main.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Discussions](https://img.shields.io/badge/GitHub-Discussions-6f42c1)](https://github.com/osheepv/thesis-agent-dsh/discussions)

学位论文全流程智能写作工作台的工程化原型：FastAPI 后端、十阶段状态机、文献与知识库基础、docx 管线和桌面式 Web UI。

> 准确定位：项目已经具备可信的十阶段控制流，但还不是可稳定交付完整本/硕/博论文的成品。当前重点是把整批生成改造成可编辑、可版本化、逐条绑定证据的分节写作系统。产品边界和建设路线见 [产品架构蓝图](docs/产品架构蓝图.md)，界面规范见 [DESIGN.md](DESIGN.md)。

> 2026-08-26 修复复验：原全流程验证发现的作者选题未落库、文献不可整理、环6/7降级稿放行、失败不可恢复、Token漏记和前端状态不同步等问题已修复。隔离浏览器故障注入流程完成10/10环并达到100%，环7在第3章失败后从检查点续写，DOCX实际生成且版式/交付校验通过；199项pytest全部通过。由于尚未重新完成一次“全环真实供应商 + 真实长论文”压力验收，当前适合内部联调与受控试用，仍不应宣称为无需人工学术审查的生产成品。详见 [全流程模拟验证报告](docs/全流程模拟验证报告_2026-08-24.md)。

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
- 环1候选题由作者显式选择并持久化为后端事实；多候选未选择时禁止确认。
- 环3支持候选文献纳入/排除/排序，确认条目以RIS题录登记到任务知识库。
- 环6/7执行学位级硬质量门禁：本科/硕士/博士最低字数分别为1万/3万/6万，并校验章节、引用、结果、书签、占位文本和生成来源；Mock/降级稿不能伪装为通过。
- 环6/7采用逐章调用；环7保存章节级检查点，作业重试只继续未完成章节，空响应的已计费Token同样进入预算。
- 环7/8失败后可安全回到可修订环节，恢复入口同时识别FSM失败态与当前环FAILED Job。
- 新分节链路的环8会审计正文证据/结果标记，生成稳定引文编号、GB/T 7714参考文献和结果交叉引用清单。
- DOCX 生成器会把明确的 `BOOKMARK/REF` 标记转换为 Word 原生书签与 `REF` 域，并在交付前验证目标完整性；内置模板已修复为严格 OOXML 校验通过。
- 长耗时环执行、分节生成和 DOCX 生成可进入持久化 JobRun；支持幂等入队、Worker 租约/心跳、崩溃恢复、协作取消、失败重试及 Token/费用预算。
- 前端支持十环进度、人工确认闸门、后台作业与预算、证据/论证审计、分节生成/修订/审批，以及刷新后的状态恢复。
- 前端交互已完成一轮真实浏览器加固：默认本地 CORS 可直接连接 API，任务列表刷新会保留当前任务，搜索支持中英文/学位/阶段过滤、无结果提示、Esc 清除和结果数播报。
- 前端支持作者候选题选择、文献筛选排序、失败恢复、实时阶段摘要、批量分节操作和自适应Job轮询；Cytoscape已改为本地静态依赖，离线启动不再访问公共CDN。
- 研究工作台可视化创建并审批研究协议/论证图，上传实验材料、原始数据、代码和日志，推进实验状态、登记/核验结果及批准结果账本。
- 分节工作台可选择任意两个版本进行双栏行级差异比较；学校 DOCX 模板会持久化并支持中英文占位符映射，未映射字段会阻断生成。
- 可选生产认证层提供 HttpOnly 不透明会话、scrypt 密码哈希、登录锁定、owner/editor/reviewer/viewer 授权、任务/知识库租户隔离和不可变操作审计。
- `demo_run.py` 提供最小严格流程冒烟；`demo_full_10.py` 按真实闸门协议运行，任一环失败即停止。

当前关键缺口：

- 结构化表格/图片编辑器、复杂公式管线和学校模板样式差异诊断仍待完成。
- UI 仍是单文件原型；桌面打包、独立 Worker 运维、MFA/SSO 和密钥托管尚未完成。
- 需要补充系统化模型评测、提示词回归和真实长论文压力测试。

## 欢迎参与讨论

这个项目现已公开，希望听到真实用户、研究者和开发者对“智能体如何协助论文写作全流程”的不同看法。

- 发现缺陷、交互问题或学术安全风险，请提交 [Issue](https://github.com/osheepv/thesis-agent-dsh/issues)。
- 产品方向、工作流设计、Agent协作、知识库与引用规范等开放问题，欢迎在 [Discussions](https://github.com/osheepv/thesis-agent-dsh/discussions) 中交流。
- 提交建议时，请尽量说明使用场景、期望行为和当前问题；请勿上传未公开论文、个人信息、API密钥或受版权保护的全文材料。

所有反馈都会作为产品迭代参考，但本项目不会代替作者、导师或学校完成学术真实性、研究伦理和最终质量审查。

参与前请阅读 [贡献指南](CONTRIBUTING.md)、[社区行为准则](CODE_OF_CONDUCT.md)、[安全政策](SECURITY.md) 和 [产品路线图](ROADMAP.md)。

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
| 安全治理 | 认证/授权/审计 | `backend/security/` | ✅ 可选 fail-closed 认证、租户隔离、角色授权、会话撤销和操作审计 |
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

后端默认只允许 `http://127.0.0.1:8787` 与 `http://localhost:8787` 的带凭证跨域请求。部署到其他域名时，通过 `THESIS_CORS_ORIGINS` 逗号分隔显式配置真实前端来源；认证模式禁止使用 `*`。

## 运行测试

当前回归基线：**199 项 pytest 全部通过**（2026-08-26）。

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
`THESIS_LLM_OUTPUT_COST_PER_MILLION` / `THESIS_KB_MAX_FILE_MB` /
`THESIS_AUTH_ENABLED` / `THESIS_AUTH_BOOTSTRAP_TOKEN` / `THESIS_SECURITY_DB`。

## API 示例

见 `docs/api_examples.md`。

## 许可证

项目自有代码采用 [Apache License 2.0](LICENSE)。第三方组件继续适用各自许可证，详见 [第三方软件声明](THIRD_PARTY_NOTICES.md)。
