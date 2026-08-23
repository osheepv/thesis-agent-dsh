"""任务隔离、可追溯的 SQLite 证据账本。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import (
    Claim,
    ClaimStatus,
    ClaimType,
    EvidenceExcerpt,
    EvidenceLink,
    EvidenceRelation,
    EvidenceReviewStatus,
    SourceRecord,
    SourceVerificationStatus,
)


class EvidenceLedgerError(ValueError):
    """违反任务隔离、定位、复核或证据链接约束。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_doi(value: str) -> str:
    doi = value.strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi)
    return doi.rstrip("/.,; ")


class EvidenceLedger:
    """来源、摘录、论断及其关系的持久化账本。"""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._lock = threading.RLock()
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._db_path, check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _init_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS t_evidence_source (
                source_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                canonical_key TEXT NOT NULL,
                title TEXT NOT NULL,
                authors TEXT NOT NULL DEFAULT '[]',
                year INTEGER,
                venue TEXT NOT NULL DEFAULT '',
                doi TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                provider TEXT NOT NULL DEFAULT '',
                verification_status TEXT NOT NULL,
                reliability TEXT NOT NULL DEFAULT 'uncertain',
                file_hash TEXT NOT NULL DEFAULT '',
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(task_id, canonical_key)
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_source_task
            ON t_evidence_source(task_id, created_at);

            CREATE TABLE IF NOT EXISTS t_evidence_excerpt (
                evidence_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                quote TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER,
                section TEXT NOT NULL DEFAULT '',
                char_start INTEGER,
                char_end INTEGER,
                content_hash TEXT NOT NULL,
                review_status TEXT NOT NULL,
                review_actor TEXT NOT NULL DEFAULT '',
                review_reason TEXT NOT NULL DEFAULT '',
                created_by TEXT NOT NULL DEFAULT 'agent',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES t_evidence_source(source_id) ON DELETE CASCADE,
                UNIQUE(task_id, source_id, content_hash, page_start, page_end, section, char_start, char_end)
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_excerpt_task
            ON t_evidence_excerpt(task_id, source_id, created_at);

            CREATE TABLE IF NOT EXISTS t_evidence_claim (
                claim_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                source_key TEXT NOT NULL DEFAULT '',
                artifact_id TEXT NOT NULL DEFAULT '',
                section_id TEXT NOT NULL DEFAULT '',
                text TEXT NOT NULL,
                claim_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_claim_task
            ON t_evidence_claim(task_id, artifact_id, created_at);

            CREATE TABLE IF NOT EXISTS t_evidence_link (
                link_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                claim_id TEXT NOT NULL,
                evidence_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(claim_id) REFERENCES t_evidence_claim(claim_id) ON DELETE CASCADE,
                FOREIGN KEY(evidence_id) REFERENCES t_evidence_excerpt(evidence_id) ON DELETE CASCADE,
                UNIQUE(task_id, claim_id, evidence_id, relation)
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_link_claim
            ON t_evidence_link(task_id, claim_id);
            """
        )
        claim_columns = {
            str(row[1])
            for row in self._db.execute("PRAGMA table_info(t_evidence_claim)").fetchall()
        }
        if "source_key" not in claim_columns:
            self._db.execute(
                "ALTER TABLE t_evidence_claim ADD COLUMN source_key TEXT NOT NULL DEFAULT ''"
            )
        self._db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_evidence_claim_source_key "
            "ON t_evidence_claim(task_id, source_key) WHERE source_key <> ''"
        )
        self._db.commit()

    @staticmethod
    def canonical_key(
        *, title: str = "", year: int | None = None, doi: str = "",
        url: str = "", file_hash: str = "",
    ) -> str:
        normalized_doi = _normalize_doi(doi)
        if normalized_doi:
            return f"doi:{normalized_doi}"
        if file_hash.strip():
            return f"file:{file_hash.strip().lower()}"
        if url.strip():
            return f"url:{url.strip().lower().rstrip('/')}"
        normalized_title = " ".join(title.casefold().split())
        if not normalized_title:
            raise EvidenceLedgerError("来源至少需要 title、doi、url 或 file_hash 之一")
        digest = hashlib.sha256(f"{normalized_title}|{year or ''}".encode("utf-8")).hexdigest()
        return f"title:{digest}"

    def register_source(
        self,
        *,
        task_id: str,
        title: str = "",
        authors: Iterable[str] = (),
        year: int | None = None,
        venue: str = "",
        doi: str = "",
        url: str = "",
        provider: str = "",
        verification_status: SourceVerificationStatus = SourceVerificationStatus.UNVERIFIED,
        reliability: str = "uncertain",
        file_hash: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SourceRecord:
        task_id = task_id.strip()
        if not task_id:
            raise EvidenceLedgerError("task_id 不能为空")
        if not isinstance(verification_status, SourceVerificationStatus):
            raise EvidenceLedgerError("verification_status 非法")
        normalized_doi = _normalize_doi(doi)
        key = self.canonical_key(
            title=title, year=year, doi=normalized_doi, url=url, file_hash=file_hash
        )
        author_values = tuple(str(item).strip() for item in authors if str(item).strip())
        now = _utc_now()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self._db.execute(
                    "SELECT source_id FROM t_evidence_source WHERE task_id=? AND canonical_key=?",
                    (task_id, key),
                ).fetchone()
                if existing is not None:
                    source_id = str(existing["source_id"])
                    current = self.get_source(task_id, source_id)
                    merged_meta = dict(current.metadata)
                    merged_meta.update(metadata or {})
                    status = self._stronger_status(
                        current.verification_status, verification_status
                    )
                    self._db.execute(
                        "UPDATE t_evidence_source SET title=?, authors=?, year=?, venue=?, doi=?, "
                        "url=?, provider=?, verification_status=?, reliability=?, file_hash=?, "
                        "metadata=?, updated_at=? WHERE source_id=?",
                        (
                            title.strip() or current.title,
                            _json_dump(author_values or current.authors),
                            year if year is not None else current.year,
                            venue.strip() or current.venue,
                            normalized_doi or current.doi,
                            url.strip() or current.url,
                            provider.strip() or current.provider,
                            status.value,
                            reliability.strip() or current.reliability,
                            file_hash.strip() or current.file_hash,
                            _json_dump(merged_meta),
                            now,
                            source_id,
                        ),
                    )
                else:
                    source_id = f"SRC-{uuid.uuid4().hex[:20].upper()}"
                    self._db.execute(
                        "INSERT INTO t_evidence_source(source_id, task_id, canonical_key, title, "
                        "authors, year, venue, doi, url, provider, verification_status, reliability, "
                        "file_hash, metadata, created_at, updated_at) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            source_id, task_id, key, title.strip(), _json_dump(author_values), year,
                            venue.strip(), normalized_doi, url.strip(), provider.strip(),
                            verification_status.value, reliability.strip() or "uncertain",
                            file_hash.strip(), _json_dump(metadata or {}), now, now,
                        ),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return self.get_source(task_id, source_id)

    @staticmethod
    def _stronger_status(
        left: SourceVerificationStatus, right: SourceVerificationStatus
    ) -> SourceVerificationStatus:
        terminal = {SourceVerificationStatus.RETRACTED_FLAG, SourceVerificationStatus.EXCLUDED}
        if left in terminal:
            return left
        if right in terminal:
            return right
        ranks = {
            SourceVerificationStatus.UNVERIFIED: 0,
            SourceVerificationStatus.METADATA_VERIFIED: 1,
            SourceVerificationStatus.FULLTEXT_AVAILABLE: 2,
            SourceVerificationStatus.CONTENT_VERIFIED: 3,
        }
        return left if ranks[left] >= ranks[right] else right

    def get_source(self, task_id: str, source_id: str) -> SourceRecord:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_evidence_source WHERE task_id=? AND source_id=?",
                (task_id, source_id),
            ).fetchone()
        if row is None:
            raise EvidenceLedgerError(f"当前任务中不存在来源: {source_id}")
        return self._row_to_source(row)

    def list_sources(self, task_id: str) -> list[SourceRecord]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM t_evidence_source WHERE task_id=? ORDER BY created_at, source_id",
                (task_id,),
            ).fetchall()
        return [self._row_to_source(row) for row in rows]

    def set_source_verification(
        self, task_id: str, source_id: str, status: SourceVerificationStatus
    ) -> SourceRecord:
        current = self.get_source(task_id, source_id)
        if not isinstance(status, SourceVerificationStatus):
            raise EvidenceLedgerError("verification status 非法")
        effective = self._stronger_status(current.verification_status, status)
        with self._lock:
            self._db.execute(
                "UPDATE t_evidence_source SET verification_status=?, updated_at=? "
                "WHERE task_id=? AND source_id=?",
                (effective.value, _utc_now(), task_id, source_id),
            )
            self._db.commit()
        return self.get_source(task_id, source_id)

    def add_excerpt(
        self,
        *,
        task_id: str,
        source_id: str,
        quote: str,
        page_start: int | None = None,
        page_end: int | None = None,
        section: str = "",
        char_start: int | None = None,
        char_end: int | None = None,
        created_by: str = "agent",
    ) -> EvidenceExcerpt:
        self.get_source(task_id, source_id)
        quote = quote.strip()
        if not quote:
            raise EvidenceLedgerError("证据摘录不能为空")
        if page_start is None and not section.strip() and char_start is None:
            raise EvidenceLedgerError("证据必须包含页码、章节或字符偏移定位")
        if page_start is not None and page_start < 1:
            raise EvidenceLedgerError("page_start 必须大于 0")
        if page_end is not None and (page_start is None or page_end < page_start):
            raise EvidenceLedgerError("page_end 不能早于 page_start")
        if char_start is not None and char_start < 0:
            raise EvidenceLedgerError("char_start 不能为负数")
        if char_end is not None and (char_start is None or char_end < char_start):
            raise EvidenceLedgerError("char_end 不能早于 char_start")
        content_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        now = _utc_now()
        with self._lock:
            existing = self._db.execute(
                "SELECT evidence_id FROM t_evidence_excerpt WHERE task_id=? AND source_id=? "
                "AND content_hash=? AND page_start IS ? AND page_end IS ? AND section=? "
                "AND char_start IS ? AND char_end IS ?",
                (
                    task_id, source_id, content_hash, page_start, page_end, section.strip(),
                    char_start, char_end,
                ),
            ).fetchone()
            if existing is not None:
                return self.get_excerpt(task_id, str(existing["evidence_id"]))
            evidence_id = f"EVD-{uuid.uuid4().hex[:20].upper()}"
            self._db.execute(
                "INSERT INTO t_evidence_excerpt(evidence_id, task_id, source_id, quote, "
                "page_start, page_end, section, char_start, char_end, content_hash, "
                "review_status, review_actor, review_reason, created_by, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, ?, ?)",
                (
                    evidence_id, task_id, source_id, quote, page_start, page_end, section.strip(),
                    char_start, char_end, content_hash, EvidenceReviewStatus.NEEDS_REVIEW.value,
                    created_by.strip() or "agent", now, now,
                ),
            )
            self._db.commit()
        return self.get_excerpt(task_id, evidence_id)

    def review_excerpt(
        self, task_id: str, evidence_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> EvidenceExcerpt:
        self.get_excerpt(task_id, evidence_id)
        status = EvidenceReviewStatus.APPROVED if approved else EvidenceReviewStatus.REJECTED
        with self._lock:
            self._db.execute(
                "UPDATE t_evidence_excerpt SET review_status=?, review_actor=?, review_reason=?, "
                "updated_at=? WHERE task_id=? AND evidence_id=?",
                (status.value, actor.strip() or "author", reason.strip(), _utc_now(), task_id, evidence_id),
            )
            self._db.commit()
        reviewed = self.get_excerpt(task_id, evidence_id)
        if approved:
            self.set_source_verification(
                task_id, reviewed.source_id, SourceVerificationStatus.CONTENT_VERIFIED
            )
        return reviewed

    def get_excerpt(self, task_id: str, evidence_id: str) -> EvidenceExcerpt:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_evidence_excerpt WHERE task_id=? AND evidence_id=?",
                (task_id, evidence_id),
            ).fetchone()
        if row is None:
            raise EvidenceLedgerError(f"当前任务中不存在证据: {evidence_id}")
        return self._row_to_excerpt(row)

    def list_excerpts(self, task_id: str, source_id: str = "") -> list[EvidenceExcerpt]:
        query = "SELECT * FROM t_evidence_excerpt WHERE task_id=?"
        args: list[Any] = [task_id]
        if source_id:
            query += " AND source_id=?"
            args.append(source_id)
        query += " ORDER BY created_at, evidence_id"
        with self._lock:
            rows = self._db.execute(query, tuple(args)).fetchall()
        return [self._row_to_excerpt(row) for row in rows]

    def add_claim(
        self, *, task_id: str, text: str, artifact_id: str = "", section_id: str = "",
        claim_type: ClaimType = ClaimType.FACTUAL, source_key: str = "",
    ) -> Claim:
        if not task_id.strip():
            raise EvidenceLedgerError("task_id 不能为空")
        if not text.strip():
            raise EvidenceLedgerError("论断不能为空")
        if not isinstance(claim_type, ClaimType):
            raise EvidenceLedgerError("claim_type 非法")
        source_key = source_key.strip()
        if source_key:
            with self._lock:
                existing = self._db.execute(
                    "SELECT claim_id FROM t_evidence_claim WHERE task_id=? AND source_key=?",
                    (task_id, source_key),
                ).fetchone()
            if existing is not None:
                return self.get_claim(task_id, str(existing["claim_id"]))
        claim_id = f"CLM-{uuid.uuid4().hex[:20].upper()}"
        now = _utc_now()
        with self._lock:
            self._db.execute(
                "INSERT INTO t_evidence_claim(claim_id, task_id, source_key, artifact_id, "
                "section_id, text, claim_type, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim_id, task_id, source_key, artifact_id.strip(), section_id.strip(),
                    text.strip(), claim_type.value, now, now,
                ),
            )
            self._db.commit()
        return self.get_claim(task_id, claim_id)

    def get_claim(self, task_id: str, claim_id: str) -> Claim:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_evidence_claim WHERE task_id=? AND claim_id=?",
                (task_id, claim_id),
            ).fetchone()
        if row is None:
            raise EvidenceLedgerError(f"当前任务中不存在论断: {claim_id}")
        return self._row_to_claim(row)

    def list_claims(self, task_id: str, artifact_id: str = "") -> list[Claim]:
        query = "SELECT * FROM t_evidence_claim WHERE task_id=?"
        args: list[Any] = [task_id]
        if artifact_id:
            query += " AND artifact_id=?"
            args.append(artifact_id)
        query += " ORDER BY created_at, claim_id"
        with self._lock:
            rows = self._db.execute(query, tuple(args)).fetchall()
        return [self._row_to_claim(row) for row in rows]

    def link_evidence(
        self, *, task_id: str, claim_id: str, evidence_id: str,
        relation: EvidenceRelation, rationale: str = "",
    ) -> EvidenceLink:
        self.get_claim(task_id, claim_id)
        evidence = self.get_excerpt(task_id, evidence_id)
        if evidence.review_status != EvidenceReviewStatus.APPROVED:
            raise EvidenceLedgerError("只有经作者批准的证据摘录才能链接到论断")
        if not isinstance(relation, EvidenceRelation):
            raise EvidenceLedgerError("relation 非法")
        with self._lock:
            existing = self._db.execute(
                "SELECT link_id FROM t_evidence_link WHERE task_id=? AND claim_id=? "
                "AND evidence_id=? AND relation=?",
                (task_id, claim_id, evidence_id, relation.value),
            ).fetchone()
            if existing is not None:
                return self.get_link(task_id, str(existing["link_id"]))
            link_id = f"LNK-{uuid.uuid4().hex[:20].upper()}"
            self._db.execute(
                "INSERT INTO t_evidence_link(link_id, task_id, claim_id, evidence_id, relation, "
                "rationale, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    link_id, task_id, claim_id, evidence_id, relation.value,
                    rationale.strip(), _utc_now(),
                ),
            )
            self._db.commit()
        return self.get_link(task_id, link_id)

    def get_link(self, task_id: str, link_id: str) -> EvidenceLink:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM t_evidence_link WHERE task_id=? AND link_id=?",
                (task_id, link_id),
            ).fetchone()
        if row is None:
            raise EvidenceLedgerError(f"当前任务中不存在证据链接: {link_id}")
        return self._row_to_link(row)

    def list_links(self, task_id: str, claim_id: str = "") -> list[EvidenceLink]:
        query = "SELECT * FROM t_evidence_link WHERE task_id=?"
        args: list[Any] = [task_id]
        if claim_id:
            query += " AND claim_id=?"
            args.append(claim_id)
        query += " ORDER BY created_at, link_id"
        with self._lock:
            rows = self._db.execute(query, tuple(args)).fetchall()
        return [self._row_to_link(row) for row in rows]

    def audit(self, task_id: str, artifact_id: str = "") -> dict[str, Any]:
        claims = self.list_claims(task_id, artifact_id)
        rows: list[dict[str, Any]] = []
        blocking: list[str] = []
        for claim in claims:
            links = self.list_links(task_id, claim.claim_id)
            approved_links: list[EvidenceLink] = []
            invalid_evidence_ids: list[str] = []
            for link in links:
                excerpt = self.get_excerpt(task_id, link.evidence_id)
                if excerpt.review_status == EvidenceReviewStatus.APPROVED:
                    approved_links.append(link)
                else:
                    invalid_evidence_ids.append(link.evidence_id)
            support_ids = [
                link.evidence_id
                for link in approved_links
                if link.relation in (EvidenceRelation.SUPPORTS, EvidenceRelation.METHOD)
            ]
            contradiction_ids = [
                link.evidence_id
                for link in approved_links
                if link.relation == EvidenceRelation.CONTRADICTS
            ]
            if contradiction_ids:
                status = ClaimStatus.DISPUTED
            elif support_ids:
                status = ClaimStatus.SUPPORTED
            else:
                status = ClaimStatus.UNSUPPORTED
            if status != ClaimStatus.SUPPORTED:
                blocking.append(claim.claim_id)
            rows.append(
                {
                    **claim.to_dict(),
                    "status": status.value,
                    "supporting_evidence_ids": support_ids,
                    "contradicting_evidence_ids": contradiction_ids,
                    "invalid_evidence_ids": invalid_evidence_ids,
                    "link_count": len(links),
                }
            )
        return {
            "task_id": task_id,
            "artifact_id": artifact_id,
            "claim_count": len(claims),
            "supported_count": sum(1 for row in rows if row["status"] == ClaimStatus.SUPPORTED.value),
            "unsupported_count": sum(1 for row in rows if row["status"] == ClaimStatus.UNSUPPORTED.value),
            "disputed_count": sum(1 for row in rows if row["status"] == ClaimStatus.DISPUTED.value),
            "blocking_claim_ids": blocking,
            "can_publish": bool(claims) and not blocking,
            "claims": rows,
        }

    def delete_task(self, task_id: str) -> dict[str, int]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                link_count = self._db.execute(
                    "DELETE FROM t_evidence_link WHERE task_id=?", (task_id,)
                ).rowcount
                excerpt_count = self._db.execute(
                    "DELETE FROM t_evidence_excerpt WHERE task_id=?", (task_id,)
                ).rowcount
                claim_count = self._db.execute(
                    "DELETE FROM t_evidence_claim WHERE task_id=?", (task_id,)
                ).rowcount
                source_count = self._db.execute(
                    "DELETE FROM t_evidence_source WHERE task_id=?", (task_id,)
                ).rowcount
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return {
            "sources": int(source_count), "excerpts": int(excerpt_count),
            "claims": int(claim_count), "links": int(link_count),
        }

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            source_id=str(row["source_id"]), task_id=str(row["task_id"]),
            canonical_key=str(row["canonical_key"]), title=str(row["title"]),
            authors=tuple(json.loads(str(row["authors"]))), year=row["year"],
            venue=str(row["venue"]), doi=str(row["doi"]), url=str(row["url"]),
            provider=str(row["provider"]),
            verification_status=SourceVerificationStatus(str(row["verification_status"])),
            reliability=str(row["reliability"]), file_hash=str(row["file_hash"]),
            metadata=json.loads(str(row["metadata"])), created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_excerpt(row: sqlite3.Row) -> EvidenceExcerpt:
        return EvidenceExcerpt(
            evidence_id=str(row["evidence_id"]), task_id=str(row["task_id"]),
            source_id=str(row["source_id"]), quote=str(row["quote"]),
            page_start=row["page_start"], page_end=row["page_end"],
            section=str(row["section"]), char_start=row["char_start"], char_end=row["char_end"],
            content_hash=str(row["content_hash"]),
            review_status=EvidenceReviewStatus(str(row["review_status"])),
            review_actor=str(row["review_actor"]), review_reason=str(row["review_reason"]),
            created_by=str(row["created_by"]), created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_claim(row: sqlite3.Row) -> Claim:
        return Claim(
            claim_id=str(row["claim_id"]), task_id=str(row["task_id"]),
            source_key=str(row["source_key"]),
            artifact_id=str(row["artifact_id"]), section_id=str(row["section_id"]),
            text=str(row["text"]), claim_type=ClaimType(str(row["claim_type"])),
            created_at=str(row["created_at"]), updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _row_to_link(row: sqlite3.Row) -> EvidenceLink:
        return EvidenceLink(
            link_id=str(row["link_id"]), task_id=str(row["task_id"]),
            claim_id=str(row["claim_id"]), evidence_id=str(row["evidence_id"]),
            relation=EvidenceRelation(str(row["relation"])), rationale=str(row["rationale"]),
            created_at=str(row["created_at"]),
        )
