# -*- coding: utf-8 -*-
"""证据/来源/论断服务（从 uc_main_orchestration.py 拆出的 mixin）。

EvidenceServiceMixin 依赖宿主类提供：
    self._evidence  — EvidenceLedger 实例
    self._artifacts — ArtifactRegistry 实例
    self._require(task_id) — 身份校验方法
"""
from __future__ import annotations

from typing import Any, Dict, List

from common.aicoding.dto.result import Result

from evidence import (
    ClaimType,
    EvidenceLedgerError,
    EvidenceRelation,
    SourceVerificationStatus,
)
from artifacts import ArtifactStatus


class EvidenceServiceMixin:
    """来源、可定位摘录、论断和证据链接的 CRUD 与审计。"""

    def register_source(self, task_id: str, source: Dict[str, Any]) -> Result[Dict[str, Any]]:
        self._require(task_id)
        status_value = str(source.get("verification_status", "UNVERIFIED"))
        try:
            status = SourceVerificationStatus(status_value)
        except ValueError as exc:
            raise EvidenceLedgerError(f"非法来源核验状态: {status_value}") from exc
        record = self._evidence.register_source(
            task_id=task_id,
            title=str(source.get("title", "")),
            authors=source.get("authors", ()) or (),
            year=source.get("year"),
            venue=str(source.get("venue", "")),
            doi=str(source.get("doi", "")),
            url=str(source.get("url", "")),
            provider=str(source.get("provider", "user")),
            verification_status=status,
            reliability=str(source.get("reliability", "uncertain")),
            file_hash=str(source.get("file_hash", "")),
            metadata=dict(source.get("metadata", {}) or {}),
        )
        return Result.ok(data=record.to_dict(), msg="来源已登记")

    def list_sources(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        self._sync_approved_literature_artifacts(task_id)
        return Result.ok(
            data=[item.to_dict() for item in self._evidence.list_sources(task_id)],
            msg="来源列表",
        )

    def add_evidence(self, task_id: str, value: Dict[str, Any]) -> Result[Dict[str, Any]]:
        self._require(task_id)
        excerpt = self._evidence.add_excerpt(
            task_id=task_id,
            source_id=str(value.get("source_id", "")),
            quote=str(value.get("quote", "")),
            page_start=value.get("page_start"),
            page_end=value.get("page_end"),
            section=str(value.get("section", "")),
            char_start=value.get("char_start"),
            char_end=value.get("char_end"),
            created_by=str(value.get("created_by", "agent")),
        )
        return Result.ok(data=excerpt.to_dict(), msg="证据摘录已登记，等待作者复核")

    def list_evidence(self, task_id: str, source_id: str = "") -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[
                item.to_dict()
                for item in self._evidence.list_excerpts(task_id, source_id=source_id)
            ],
            msg="证据摘录列表",
        )

    def review_evidence(
        self, task_id: str, evidence_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        excerpt = self._evidence.review_excerpt(
            task_id, evidence_id, approved=approved, actor=actor, reason=reason
        )
        return Result.ok(data=excerpt.to_dict(), msg="证据复核结果已记录")

    def add_claim(self, task_id: str, value: Dict[str, Any]) -> Result[Dict[str, Any]]:
        self._require(task_id)
        artifact_id = str(value.get("artifact_id", ""))
        if artifact_id:
            artifact = self._artifacts.get(artifact_id)
            if artifact.task_id != task_id:
                raise EvidenceLedgerError("禁止把论断挂到其他论文任务的产物")
        type_value = str(value.get("claim_type", "FACTUAL"))
        try:
            claim_type = ClaimType(type_value)
        except ValueError as exc:
            raise EvidenceLedgerError(f"非法论断类型: {type_value}") from exc
        claim = self._evidence.add_claim(
            task_id=task_id,
            text=str(value.get("text", "")),
            artifact_id=artifact_id,
            section_id=str(value.get("section_id", "")),
            claim_type=claim_type,
        )
        return Result.ok(data=claim.to_dict(), msg="论断已登记")

    def list_claims(self, task_id: str, artifact_id: str = "") -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        return Result.ok(
            data=[
                item.to_dict()
                for item in self._evidence.list_claims(task_id, artifact_id=artifact_id)
            ],
            msg="论断列表",
        )

    def link_claim_evidence(
        self, task_id: str, claim_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        relation_value = str(value.get("relation", "SUPPORTS"))
        try:
            relation = EvidenceRelation(relation_value)
        except ValueError as exc:
            raise EvidenceLedgerError(f"非法证据关系: {relation_value}") from exc
        link = self._evidence.link_evidence(
            task_id=task_id,
            claim_id=claim_id,
            evidence_id=str(value.get("evidence_id", "")),
            relation=relation,
            rationale=str(value.get("rationale", "")),
        )
        return Result.ok(data=link.to_dict(), msg="论断—证据链接已登记")

    def audit_evidence(self, task_id: str, artifact_id: str = "") -> Result[Dict[str, Any]]:
        self._require(task_id)
        return Result.ok(
            data=self._evidence.audit(task_id, artifact_id=artifact_id),
            msg="证据覆盖审计完成",
        )

    def _sync_approved_literature_artifacts(self, task_id: str) -> None:
        """为升级前已投影的环3产物补登记来源；重复调用保持幂等。"""
        for artifact in self._artifacts.list_task(task_id):
            if artifact.stage_no == 3 and artifact.status == ArtifactStatus.APPROVED:
                self._register_literature_sources(
                    task_id=task_id,
                    payload=artifact.payload,
                    artifact_id=artifact.artifact_id,
                    source_event_id=artifact.source_event_id,
                )

    def _register_literature_sources(
        self, *, task_id: str, payload: Dict[str, Any], artifact_id: str,
        source_event_id: str,
    ) -> None:
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise EvidenceLedgerError("环3文献产物 items 必须是列表")
        for item in items:
            if not isinstance(item, dict):
                raise EvidenceLedgerError("环3文献条目必须是对象")
            reliability = str(item.get("reliability", "uncertain"))
            status = (
                SourceVerificationStatus.METADATA_VERIFIED
                if reliability in ("verified", "matched")
                else SourceVerificationStatus.UNVERIFIED
            )
            urls = item.get("urls", []) or []
            url = str(urls[0]) if isinstance(urls, list) and urls else ""
            self._evidence.register_source(
                task_id=task_id,
                title=str(item.get("title", "")),
                authors=item.get("authors", ()) or (),
                year=item.get("year"),
                venue=str(item.get("venue", "")),
                doi=str(item.get("doi", "")),
                url=url,
                provider="ring3",
                verification_status=status,
                reliability=reliability,
                metadata={
                    "artifact_id": artifact_id,
                    "source_event_id": source_event_id,
                    "abstract": str(item.get("abstract", "")),
                    "category": str(item.get("category", "")),
                    "citation_count": item.get("citation_count"),
                    "gbt7714": str(item.get("gbt7714", "")),
                    "urls": urls if isinstance(urls, list) else [],
                },
            )
