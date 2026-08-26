-- LEGACY TARGET SCHEMA：仅保留为早期PostgreSQL设计参考，不是当前运行时迁移源。
-- 当前唯一FSM映射为 fsm/state/orm.py；在建立Alembic基线前请勿直接用于生产库。
-- ============================================================
-- thesis-agent-dsh  一期 PostgreSQL 原生 DDL
-- 数据库: PostgreSQL 16；字符集 utf8mb4 由 PG 以 UTF8 承载。
-- 约束: 使用 GENERATED ALWAYS AS IDENTITY / BOOLEAN / CREATE INDEX /
--       tsvector 生成列 + GIN 索引；严格禁用 MySQL 语法
--       (禁 AUTO_INCREMENT / TINYINT(1) / ON UPDATE CURRENT_TIMESTAMP /
--        行内 COMMENT / FULLTEXT)。
-- 执行: psql -U <user> -d <db> -f db/ddl.sql
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 0) 扩展：gin/tsvector 全文检索需要 (PG13+ 内置，无需额外扩展)，
--    此处显式声明以便审计。
-- ------------------------------------------------------------

-- ------------------------------------------------------------
-- 1) t_task  论文任务（一次生成任务对应一条）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_task (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_no         VARCHAR(64)  NOT NULL,
    title           VARCHAR(512) NOT NULL,
    degree          VARCHAR(16)  NOT NULL,                    -- BACHELOR/MASTER/PHD
    discipline      VARCHAR(128) NULL,
    session_id      VARCHAR(64)  NOT NULL,                    -- M9 会话知识隔离强绑定
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
    status          VARCHAR(24)  NOT NULL DEFAULT 'NOT_STARTED',
    current_ring    VARCHAR(16)  NOT NULL DEFAULT 'RING_1',   -- 当前环境编号
    retry_count     INT          NOT NULL DEFAULT 0,
    word_count      INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ  NULL
);
CREATE INDEX IF NOT EXISTS idx_task_task_no      ON t_task (task_no);
CREATE INDEX IF NOT EXISTS idx_task_session_id   ON t_task (session_id);
CREATE INDEX IF NOT EXISTS idx_task_status       ON t_task (status);

-- 标题+学科全文检索（tsvector 生成列 + GIN）
ALTER TABLE t_task ADD COLUMN IF NOT EXISTS search_vec tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(discipline, ''))
    ) STORED;
CREATE INDEX IF NOT EXISTS idx_task_search_vec ON t_task USING GIN (search_vec);

-- ------------------------------------------------------------
-- 2) t_fsm_state  FSM 状态（M1/M4，任务-环节 1:N）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_fsm_state (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id          BIGINT       NOT NULL,
    ring_type        VARCHAR(16)  NOT NULL,                   -- RING_1 ~ RING_10
    phase_state      VARCHAR(24)  NOT NULL DEFAULT 'NOT_STARTED', -- NOT_STARTED/IN_PROGRESS/PASSED/FALLBACK
    attempt          INT          NOT NULL DEFAULT 0,
    payload          JSONB        NULL,                       -- 环节产物/上下文
    is_hitl_gate     BOOLEAN      NOT NULL DEFAULT FALSE,     -- 是否 HITL 网关环节
    hitl_approved    BOOLEAN      NULL,                       -- 人工验收结果
    hitl_approver    VARCHAR(64)  NULL,
    entry_at         TIMESTAMPTZ  NULL,
    exit_at          TIMESTAMPTZ  NULL,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_fsm_state_task FOREIGN KEY (task_id) REFERENCES t_task (id) ON DELETE CASCADE,
    CONSTRAINT uq_fsm_state_task_ring UNIQUE (task_id, ring_type)
);
CREATE INDEX IF NOT EXISTS idx_fsm_state_task        ON t_fsm_state (task_id);
CREATE INDEX IF NOT EXISTS idx_fsm_state_ring_type   ON t_fsm_state (ring_type);
CREATE INDEX IF NOT EXISTS idx_fsm_state_phase_state ON t_fsm_state (phase_state);

-- ------------------------------------------------------------
-- 3) t_outline  大纲（M1 环5 产物，任务 1:N）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_outline (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id         BIGINT       NOT NULL,
    title           VARCHAR(512) NOT NULL,
    degree          VARCHAR(16)  NOT NULL,
    content         JSONB        NOT NULL,                    -- 树形章节结构
    status          VARCHAR(24)  NOT NULL DEFAULT 'DRAFT',
    word_estimate   INT          NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_outline_task FOREIGN KEY (task_id) REFERENCES t_task (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_outline_task ON t_outline (task_id);

-- ------------------------------------------------------------
-- 4) t_chapter_draft  章节草稿（M1 环6 产物，任务 1:N）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_chapter_draft (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id         BIGINT       NOT NULL,
    chapter_id      VARCHAR(64)  NOT NULL,                    -- 对应大纲章节节点 id
    chapter_seq     INT          NOT NULL,                    -- 章节顺序
    chapter_title   VARCHAR(512) NOT NULL,
    content         TEXT         NOT NULL,
    content_balloon TEXT         NULL,                        -- 字数/查重摘要（M6 校验）
    word_count      INT          NOT NULL DEFAULT 0,
    status          VARCHAR(24)  NOT NULL DEFAULT 'DRAFT',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_chapter_draft_task FOREIGN KEY (task_id) REFERENCES t_task (id) ON DELETE CASCADE,
    CONSTRAINT uq_chapter_draft_task_chapter UNIQUE (task_id, chapter_seq)
);
CREATE INDEX IF NOT EXISTS idx_chapter_draft_task    ON t_chapter_draft (task_id);
CREATE INDEX IF NOT EXISTS idx_chapter_draft_chapter ON t_chapter_draft (chapter_id);

-- 章节草稿正文全文检索
ALTER TABLE t_chapter_draft ADD COLUMN IF NOT EXISTS search_vec tsvector
    GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(chapter_title, '') || ' ' || coalesce(content, ''))
    ) STORED;
CREATE INDEX IF NOT EXISTS idx_chapter_draft_search_vec ON t_chapter_draft USING GIN (search_vec);

-- ------------------------------------------------------------
-- 5) t_docx_template  用户上传模板（M5，任务/用户 1:N）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_docx_template (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id         BIGINT       NULL,
    tenant_id       VARCHAR(64)  NOT NULL DEFAULT 'default',
    file_name       VARCHAR(256) NOT NULL,
    file_path       VARCHAR(512) NOT NULL,                    -- 对象存储/本地路径
    file_hash       VARCHAR(64)  NULL,                        -- sha256 去重
    file_size       BIGINT       NOT NULL DEFAULT 0,
    kind            VARCHAR(24)  NOT NULL DEFAULT 'THESIS',   -- THESIS/REPORT/OTHER
    parse_status    VARCHAR(24)  NOT NULL DEFAULT 'PENDING',  -- PENDING/PARSED/FAILED
    placeholders    JSONB        NULL,                        -- M5 解析出的 {{}} 占位符
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_docx_template_task FOREIGN KEY (task_id) REFERENCES t_task (id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_docx_template_task   ON t_docx_template (task_id);
CREATE INDEX IF NOT EXISTS idx_docx_template_hash   ON t_docx_template (file_hash);

-- ------------------------------------------------------------
-- 6) M9 会话知识库隔离 预留表（二期实现，本期仅建结构）
--    规则：session_id 强绑定，禁止跨会话共享。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS t_kb_collection (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id       VARCHAR(64)  NOT NULL,                   -- 会话强绑定
    tenant_id        VARCHAR(64)  NOT NULL DEFAULT 'default',
    name             VARCHAR(128) NOT NULL,
    namespace        VARCHAR(160) NOT NULL,                   -- kb_session:{session_id}
    description      VARCHAR(512) NULL,
    doc_count        INT          NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_kb_collection_session_name UNIQUE (session_id, name)
);
CREATE INDEX IF NOT EXISTS idx_kb_collection_session ON t_kb_collection (session_id);

CREATE TABLE IF NOT EXISTS t_kb_document (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collection_id    BIGINT       NOT NULL,
    session_id       VARCHAR(64)  NOT NULL,                   -- 冗余强绑定，隔离校验
    doc_name         VARCHAR(256) NOT NULL,
    doc_path         VARCHAR(512) NOT NULL,
    doc_hash         VARCHAR(64)  NULL,
    status           VARCHAR(24)  NOT NULL DEFAULT 'UPLOADED', -- PARSED/INDEXED/FAILED
    chunk_count      INT          NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_kb_document_collection FOREIGN KEY (collection_id) REFERENCES t_kb_collection (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kb_document_collection ON t_kb_document (collection_id);
CREATE INDEX IF NOT EXISTS idx_kb_document_session   ON t_kb_document (session_id);

CREATE TABLE IF NOT EXISTS t_kb_chunk (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id      BIGINT       NOT NULL,
    collection_id    BIGINT       NOT NULL,
    session_id       VARCHAR(64)  NOT NULL,                   -- 冗余强绑定，隔离校验
    chunk_seq        INT          NOT NULL,
    chunk_text       TEXT         NOT NULL,
    token_count      INT          NOT NULL DEFAULT 0,
    embedding        VECTOR       NULL,                        -- 需 pgvector 扩展（二期限装）
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT fk_kb_chunk_document FOREIGN KEY (document_id) REFERENCES t_kb_document (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_document  ON t_kb_chunk (document_id);
CREATE INDEX IF NOT EXISTS idx_kb_chunk_collection ON t_kb_chunk (collection_id);

COMMIT;
