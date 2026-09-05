# -*- coding: utf-8 -*-
"""Section writing service mixin."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from common.aicoding.dto.result import Result
from common.aicoding.enums.degree import Degree
from common.aicoding.exception.error_code import ErrorCode
from common.academic_foundation import (
    EvidenceState,
    SectionContract,
    section_contract_set_hash,
    unique_strings,
)
from thesis_docx.cross_reference import normalize_target_id

from artifacts import ArtifactKind, ArtifactStatus, ContextManifest
from evidence import ClaimType
from jobs import get_current_job_id
from writing import (
    AutosaveDraftError,
    AutosaveDraftRevisionConflict,
    SectionDraftRegistryError,
    SectionDraftStatus,
)


class SectionServiceMixin:
    """Section generation, review, revision and assembly."""

    @staticmethod
    def _outline_leaf_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clean = [item for item in nodes if isinstance(item, dict)]
        leaves: list[dict[str, Any]] = []
        for index, node in enumerate(clean):
            level = int(node.get("level", 1) or 1)
            next_level = (
                int(clean[index + 1].get("level", 1) or 1)
                if index + 1 < len(clean)
                else level
            )
            if next_level <= level:
                leaves.append(node)
        return leaves

    def _embed_section_contracts(
        self, task_id: str, nodes: list[dict[str, Any]]
    ) -> tuple[str, str]:
        foundation = self.get_academic_foundation(task_id).data
        canon_hash = str(foundation.get("canon_hash", ""))
        rows_by_section: dict[str, list[dict[str, Any]]] = {}
        for row in foundation.get("evidence_table", []) or []:
            if isinstance(row, dict):
                rows_by_section.setdefault(str(row.get("section_id", "")), []).append(row)
        input_artifact_ids = unique_strings(
            item.get("artifact_id", "")
            for item in foundation.get("artifact_refs", []) or []
            if isinstance(item, dict)
            and str(item.get("kind", "")) != ArtifactKind.RESULT_LEDGER.value
        )
        forbidden_claims = unique_strings(foundation.get("forbidden_claims", []))
        contracts: list[SectionContract] = []
        seen_section_ids: set[str] = set()
        for node in self._outline_leaf_nodes(nodes):
            section_id = str(node.get("number", "")).strip()
            title = str(node.get("title", "")).strip()
            if not section_id or not title:
                raise SectionDraftRegistryError("大纲叶子节点必须包含 number 和 title")
            if section_id in seen_section_ids:
                raise SectionDraftRegistryError(f"大纲叶子节点编号重复: {section_id}")
            seen_section_ids.add(section_id)
            rows = rows_by_section.get(section_id, [])
            requires_results = any(
                str(row.get("claim_type", "")) == ClaimType.NUMERIC.value
                for row in rows
            )
            points = unique_strings(node.get("points", []))
            purpose = "；".join(points) or f"完成“{title}”的结构性论述"
            validation_checks = [
                "SECTION_ID_MATCH",
                "ALLOWED_CLAIMS_ONLY",
                "FORBIDDEN_CLAIMS_EXCLUDED",
                "REQUIRED_EVIDENCE_USED",
                "CONTEXT_IDS_ONLY",
                "CANON_HASH_RECORDED",
            ]
            if requires_results:
                validation_checks.append("VERIFIED_RESULT_REQUIRED")
            contract = SectionContract(
                section_id=section_id,
                title=title,
                purpose=purpose,
                canon_hash=canon_hash,
                input_artifact_ids=input_artifact_ids,
                allowed_claim_keys=unique_strings(
                    row.get("claim_key", "") for row in rows
                ),
                forbidden_claims=forbidden_claims,
                evidence_requirements=unique_strings(
                    requirement
                    for row in rows
                    for requirement in (row.get("evidence_requirements", []) or [])
                ),
                required_evidence_ids=unique_strings(
                    evidence_id
                    for row in rows
                    for evidence_id in (row.get("supporting_evidence_ids", []) or [])
                ),
                # 结果账本是批准大纲的下游，不能反向固化其 ID 形成依赖环。
                required_result_ids=(),
                requires_verified_results=requires_results,
                validation_checks=tuple(validation_checks),
            )
            node["section_contract"] = contract.to_dict()
            contracts.append(contract)
        if not contracts:
            raise SectionDraftRegistryError("大纲至少需要一个可写作的叶子节点")
        return canon_hash, section_contract_set_hash(contracts)

    def _section_contract(self, outline, section_id: str) -> SectionContract:
        nodes = [
            item for item in outline.payload.get("chapters", [])
            if isinstance(item, dict)
        ]
        for node in self._outline_leaf_nodes(nodes):
            if str(node.get("number", "")).strip() != section_id:
                continue
            try:
                contract = SectionContract.from_dict(node.get("section_contract"))
            except ValueError as exc:
                raise SectionDraftRegistryError(
                    f"分节合同无效，请回退环5重新生成大纲: {exc}"
                ) from exc
            if contract.section_id != section_id:
                raise SectionDraftRegistryError("分节合同与大纲节点不一致")
            return contract
        raise SectionDraftRegistryError(
            f"大纲分节 {section_id} 缺少合同，请回退环5重新生成大纲"
        )

    def generate_section_draft(
        self, task_id: str, value: Dict[str, Any]
    ) -> Result[Dict[str, Any]]:
        rec = self._require_current_ring(task_id, 6)
        self._refresh_section_staleness(task_id)
        section_id = str(value.get("section_id", "")).strip()
        catalog = self._outline_section_catalog(task_id)
        if section_id not in catalog:
            raise SectionDraftRegistryError(f"大纲中不存在分节: {section_id}")
        outline = self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
        )
        if outline is None:
            raise SectionDraftRegistryError("缺少有效批准大纲")
        contract = self._section_contract(outline, section_id)
        foundation = self.get_academic_foundation(task_id).data
        runtime_canon_hash = str(foundation.get("canon_hash", ""))
        foundation_by_claim_id = {
            str(row.get("claim_id", "")): row
            for row in (foundation.get("evidence_table", []) or [])
            if isinstance(row, dict) and str(row.get("claim_id", ""))
        }
        argument_map = self._active_argument_map(task_id)
        protocol = self._active_research_protocol(task_id)
        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        upstream = [outline.artifact_id]
        if argument_map is not None:
            self._sync_argument_map_claims(task_id, argument_map)
            upstream.append(argument_map.artifact_id)
        if protocol is not None:
            upstream.append(protocol.artifact_id)
        if result_ledger is not None:
            upstream.append(result_ledger.artifact_id)

        claim_rows: list[dict[str, Any]] = []
        evidence_details: dict[str, dict[str, Any]] = {}
        if argument_map is not None:
            audit_rows = self._evidence.audit(task_id, argument_map.artifact_id)["claims"]
            for row in audit_rows:
                if row["section_id"] != section_id:
                    continue
                projected = foundation_by_claim_id.get(str(row.get("claim_id", "")), {})
                source_key = str(row.get("source_key", ""))
                claim_rows.append(
                    {
                        **row,
                        "claim_key": str(projected.get("claim_key", ""))
                        or source_key.rsplit(":", 1)[-1],
                        "epistemic_intent": str(
                            projected.get("epistemic_intent", "ASSERTION")
                        ),
                        "evidence_state": str(
                            projected.get("evidence_state", row.get("status", "UNSUPPORTED"))
                        ),
                        "verification_strength": str(
                            projected.get("verification_strength", "UNVERIFIED")
                        ),
                        "risk_level": str(projected.get("risk_level", "HIGH")),
                        "supporting_evidence_ids": list(
                            projected.get(
                                "supporting_evidence_ids",
                                row.get("supporting_evidence_ids", []),
                            )
                            or []
                        ),
                    }
                )

        requested_result_ids = tuple(
            dict.fromkeys(str(item) for item in (value.get("result_ids", ()) or ()) if str(item))
        )
        allowed_results = {
            str(item.get("result_id", "")): item
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user"))
        }
        unknown_result_ids = [
            result_id for result_id in requested_result_ids if result_id not in allowed_results
        ]
        if unknown_result_ids:
            raise SectionDraftRegistryError(
                f"分节引用了未核验或不属于当前结果账本的结果: {unknown_result_ids}"
            )

        blockers: list[str] = []
        for artifact_id in contract.input_artifact_ids:
            try:
                input_artifact = self._artifacts.get(artifact_id)
            except Exception:  # noqa: BLE001
                blockers.append(f"合同输入产物不存在: {artifact_id}")
                continue
            if (
                input_artifact.task_id != task_id
                or input_artifact.status != ArtifactStatus.APPROVED
            ):
                blockers.append(f"合同输入产物已失效: {artifact_id}")

        allowed_claim_keys = set(contract.allowed_claim_keys)
        current_claim_keys = {
            str(claim.get("claim_key", "")) for claim in claim_rows
            if str(claim.get("claim_key", ""))
        }
        extra_claim_keys = sorted(current_claim_keys - allowed_claim_keys)
        missing_claim_keys = sorted(allowed_claim_keys - current_claim_keys)
        if extra_claim_keys:
            blockers.append(f"当前论证图包含合同外论断: {extra_claim_keys}")
        if missing_claim_keys:
            blockers.append(f"合同论断在当前论证图中缺失: {missing_claim_keys}")
        if contract.requires_verified_results and not requested_result_ids:
            blockers.append("本节合同要求至少一个经用户核验的结果")
        missing_required_results = sorted(
            set(contract.required_result_ids) - set(requested_result_ids)
        )
        if missing_required_results:
            blockers.append(f"本节缺少合同指定结果: {missing_required_results}")

        for claim in claim_rows:
            supporting = list(claim.get("supporting_evidence_ids", []) or [])
            evidence_state = str(claim.get("evidence_state", "UNSUPPORTED"))
            if evidence_state == EvidenceState.DISPUTED.value:
                blockers.append(f"论断 {claim['claim_id']} 存在未解决反证")
            elif evidence_state == EvidenceState.INVALID_SOURCE.value:
                blockers.append(f"论断 {claim['claim_id']} 使用了失效来源")
            elif evidence_state == EvidenceState.UNSUPPORTED.value and not (
                claim["claim_type"] == ClaimType.NUMERIC.value and requested_result_ids
            ):
                blockers.append(f"论断 {claim['claim_id']} 缺少批准证据")
            for evidence_id in supporting:
                excerpt = self._evidence.get_excerpt(task_id, evidence_id)
                source = self._evidence.get_source(task_id, excerpt.source_id)
                evidence_details[evidence_id] = {
                    "evidence_id": evidence_id,
                    "quote": excerpt.quote,
                    "source_id": source.source_id,
                    "source_title": source.title,
                    "doi": source.doi,
                    "page_start": excerpt.page_start,
                    "page_end": excerpt.page_end,
                    "section": excerpt.section,
                }
        missing_required_evidence = sorted(
            set(contract.required_evidence_ids) - set(evidence_details)
        )
        if missing_required_evidence:
            blockers.append(f"本节缺少合同指定证据: {missing_required_evidence}")
        if blockers:
            raise SectionDraftRegistryError("；".join(blockers))

        context = {
            "task_id": task_id,
            "section_id": section_id,
            "title": str(value.get("title", "")).strip() or catalog[section_id],
            "paper_title": (rec.ring1 or {}).get("chosen", rec.title),
            "outline_node": catalog[section_id],
            "section_contract": contract.to_dict(),
            "canon_hash": runtime_canon_hash,
            "claims": claim_rows,
            "evidence": list(evidence_details.values()),
            "results": [allowed_results[result_id] for result_id in requested_result_ids],
            "instruction": str(value.get("instruction", "")),
            "target_word_count": max(
                300,
                (Degree(rec.degree).min_word_requirement + max(len(catalog), 1) - 1)
                // max(len(catalog), 1),
            ),
        }
        generated = self._section_generator.generate(context)
        expected_claim_ids = {str(claim["claim_id"]) for claim in claim_rows}
        covered_claim_ids = {
            str(claim_id) for claim_id in generated.covered_claim_ids if str(claim_id)
        }
        allowed_evidence_ids = set(evidence_details)
        marked_evidence_ids = set(
            re.findall(r"\bEVD-[A-Z0-9]+\b", generated.content)
        )
        marked_result_ids = set(
            re.findall(r"\bRES-[A-Z0-9]+\b", generated.content)
        )
        used_evidence_ids = {
            str(evidence_id) for evidence_id in generated.used_evidence_ids
            if str(evidence_id)
        } | marked_evidence_ids
        used_result_ids = {
            str(result_id) for result_id in generated.used_result_ids if str(result_id)
        } | marked_result_ids
        gate_issues: list[str] = []
        actual_words = len(re.sub(r"[\s#*`-]+", "", generated.content))
        if generated.generation_source == "mock":
            gate_issues.append("真实模型不可用，降级分节禁止进入作者审批")
        if actual_words < context["target_word_count"]:
            gate_issues.append(
                f"实际字数 {actual_words} 低于本节目标 {context['target_word_count']}"
            )
        if not expected_claim_ids.issubset(covered_claim_ids):
            gate_issues.append(
                f"未覆盖论断: {sorted(expected_claim_ids - covered_claim_ids)}"
            )
        if not covered_claim_ids.issubset(expected_claim_ids):
            gate_issues.append(
                f"声明了合同外论断: {sorted(covered_claim_ids - expected_claim_ids)}"
            )
        if not used_evidence_ids.issubset(allowed_evidence_ids):
            gate_issues.append(
                f"使用了上下文外证据: {sorted(used_evidence_ids - allowed_evidence_ids)}"
            )
        if not set(contract.required_evidence_ids).issubset(used_evidence_ids):
            gate_issues.append(
                "未使用合同指定证据: "
                f"{sorted(set(contract.required_evidence_ids) - used_evidence_ids)}"
            )
        if not used_result_ids.issubset(set(requested_result_ids)):
            gate_issues.append(
                f"使用了上下文外结果: {sorted(used_result_ids - set(requested_result_ids))}"
            )
        if not set(contract.required_result_ids).issubset(used_result_ids):
            gate_issues.append(
                "未使用合同指定结果: "
                f"{sorted(set(contract.required_result_ids) - used_result_ids)}"
            )
        if contract.requires_verified_results and not used_result_ids:
            gate_issues.append("本节未实际使用经用户核验的结果")
        forbidden_hits = [
            claim for claim in contract.forbidden_claims
            if claim and claim in generated.content
        ]
        if forbidden_hits:
            gate_issues.append(f"正文包含禁写主张: {forbidden_hits}")
        for claim in claim_rows:
            supporting = set(claim.get("supporting_evidence_ids", []) or [])
            if supporting and not supporting.intersection(used_evidence_ids):
                gate_issues.append(f"论断 {claim['claim_id']} 未实际引用其支持证据")
        if requested_result_ids and not set(requested_result_ids).issubset(used_result_ids):
            gate_issues.append("未使用全部指定结果记录")
        for result_id in used_result_ids.intersection(allowed_results):
            result = allowed_results[result_id]
            target = normalize_target_id(
                str(result.get("table_or_figure_id", "")) or result_id
            )
            if f"[[BOOKMARK:{target}|" not in generated.content:
                gate_issues.append(
                    f"结果 {result_id} 缺少原生交叉引用目标 BOOKMARK:{target}"
                )

        current_job_id = get_current_job_id()
        current_job = self._jobs.get(task_id, current_job_id) if current_job_id else None
        manifest = ContextManifest(
            prompt_id="section_draft",
            prompt_version="v1",
            input_artifact_ids=tuple(upstream),
            evidence_ids=tuple(sorted(used_evidence_ids)),
            job_id=current_job_id,
            token_budget=current_job.token_budget if current_job else 0,
            input_tokens=current_job.input_tokens if current_job else 0,
            output_tokens=current_job.output_tokens if current_job else 0,
            cost_budget=current_job.cost_budget if current_job else 0.0,
            cost_used=current_job.cost_used if current_job else 0.0,
            canon_hash=runtime_canon_hash,
            contract_hash=contract.contract_hash,
        )
        manifest_data = manifest.to_dict()
        draft = self._sections.create_version(
            task_id=task_id,
            section_id=section_id,
            title=generated.title or context["title"],
            content=generated.content,
            claim_ids=tuple(sorted(expected_claim_ids)),
            evidence_ids=tuple(sorted(used_evidence_ids)),
            result_ids=tuple(sorted(used_result_ids)),
            upstream_artifact_ids=tuple(upstream),
            context_manifest=manifest_data,
        )
        draft = self._sections.submit_auto_gate(
            task_id,
            draft.section_draft_id,
            passed=not gate_issues,
            report={
                "issues": gate_issues,
                "claim_count": len(expected_claim_ids),
                "evidence_count": len(used_evidence_ids),
                "result_count": len(used_result_ids),
                "actual_words": actual_words,
                "target_word_count": context["target_word_count"],
                "generation_source": generated.generation_source,
                "canon_hash": runtime_canon_hash,
                "contract_hash": contract.contract_hash,
                "contract_canon_hash": contract.canon_hash,
                "validation_checks": list(contract.validation_checks),
            },
        )
        if gate_issues:
            return Result.fail(
                code=101200,
                msg="分节草稿未通过自动验收",
                data=draft.to_dict(),
            )
        return Result.ok(data=draft.to_dict(), msg="分节草稿已生成，等待作者审批")

    def generate_all_section_drafts(self, task_id: str) -> Result[Dict[str, Any]]:
        """按大纲批量生成全部缺失分节，结果相关章节自动注入已批准结果。"""
        self._require_current_ring(task_id, 6)
        catalog = self._outline_section_catalog(task_id)
        existing = self._sections.list_task(task_id)
        ready_sections = {
            draft.section_id
            for draft in existing
            if draft.status in {
                SectionDraftStatus.WAITING_APPROVAL,
                SectionDraftStatus.APPROVED,
            }
        }
        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        verified_result_ids = [
            str(item.get("result_id", ""))
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user")) and str(item.get("result_id", ""))
        ]
        generated: list[str] = []
        failures: list[dict[str, str]] = []
        for section_id, title in catalog.items():
            if section_id in ready_sections:
                continue
            use_results = any(
                token in f"{section_id} {title}"
                for token in ("实验", "结果", "分析", "讨论", "4.", "5.")
            )
            result = self.generate_section_draft(
                task_id,
                {
                    "section_id": section_id,
                    "title": title,
                    "result_ids": verified_result_ids if use_results else [],
                    "instruction": "按批准大纲完成本节，达到目标字数并保留证据/结果标记",
                },
            )
            if result.is_ok:
                generated.append(section_id)
            else:
                failures.append({"section_id": section_id, "message": result.msg})
        if failures:
            return Result.fail(
                code=101200,
                msg=f"批量分节生成有 {len(failures)} 节未通过自动验收",
                data={"generated_section_ids": generated, "failures": failures},
            )
        return Result.ok(
            data={
                "generated_section_ids": generated,
                "skipped_section_ids": sorted(ready_sections),
                "total": len(catalog),
            },
            msg=f"已生成 {len(generated)} 个分节，等待作者审批",
        )

    def review_all_section_drafts(
        self, task_id: str, *, approved: bool, actor: str = "author"
    ) -> Result[Dict[str, Any]]:
        """批量审批当前全部 WAITING_APPROVAL 分节，减少机械重复点击。"""
        self._require_current_ring(task_id, 6)
        drafts = [
            draft
            for draft in self._sections.list_task(task_id)
            if draft.status == SectionDraftStatus.WAITING_APPROVAL
        ]
        decided = [
            self._sections.decide(
                task_id,
                draft.section_draft_id,
                approved=approved,
                actor=actor,
                reason="批量批准" if approved else "批量驳回",
            )
            for draft in drafts
        ]
        audit = self.audit_section_drafts(task_id).data
        return Result.ok(
            data={
                "decided_count": len(decided),
                "approved": approved,
                "audit": audit,
            },
            msg=f"已批量{'批准' if approved else '驳回'} {len(decided)} 个分节",
        )

    def review_section_draft(
        self, task_id: str, section_draft_id: str, *, approved: bool,
        actor: str = "author", reason: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require(task_id)
        draft = self._sections.decide(
            task_id, section_draft_id, approved=approved, actor=actor, reason=reason
        )
        data = draft.to_dict()
        data["approvals"] = self._sections.list_approvals(task_id, section_draft_id)
        return Result.ok(data=data, msg="分节审批已记录")

    def revise_section_draft(
        self,
        task_id: str,
        section_draft_id: str,
        value: Dict[str, Any],
        *,
        tenant_id: str = "",
        author_id: str = "",
    ) -> Result[Dict[str, Any]]:
        self._require_current_ring(task_id, 6)
        self._refresh_section_staleness(task_id)
        parent = self._sections.get(task_id, section_draft_id)
        if parent.status == SectionDraftStatus.STALE:
            raise SectionDraftRegistryError("上游已变化，不能基于过期分节继续修订")
        try:
            autosave = self._autosave_submission_draft(
                task_id,
                value,
                object_type="SECTION_REVISION",
                object_id=parent.section_id,
                tenant_id=tenant_id,
                author_id=author_id,
            )
        except AutosaveDraftRevisionConflict as exc:
            return Result.fail(
                code=ErrorCode.STATE_CONFLICT.value,
                msg=str(exc),
                data={
                    "conflict": True,
                    "current_revision": exc.current_revision,
                    "incoming_revision": exc.incoming_revision,
                    "remote": exc.remote.metadata(),
                },
            )
        content = str(value.get("content", "")).strip()
        if not content:
            raise SectionDraftRegistryError("修订正文不能为空")
        if autosave is not None:
            if (
                autosave.base_artifact_id != parent.section_draft_id
                or autosave.base_version != parent.version
            ):
                self._drafts.mark_stale(
                    task_id,
                    autosave.author_id,
                    autosave.draft_key,
                    reason="分节正式基线已变化，请基于最新版本重新修订",
                )
                raise AutosaveDraftError("自动草稿的分节基线已变化，已标记为STALE")
            if str(autosave.content_json.get("content", "")).strip() != content:
                raise AutosaveDraftError("正式提交内容与指定自动草稿revision不一致")
        marked_evidence = set(re.findall(r"\[(EVD-[A-Z0-9]+)\]", content))
        marked_results = set(re.findall(r"\[(RES-[A-Z0-9]+)\]", content))
        expected_evidence = set(parent.evidence_ids)
        expected_results = set(parent.result_ids)
        expected_bookmarks = set(
            re.findall(r"\[\[BOOKMARK:([A-Za-z][A-Za-z0-9_.-]{0,127})\|", parent.content)
        )
        marked_bookmarks = set(
            re.findall(r"\[\[BOOKMARK:([A-Za-z][A-Za-z0-9_.-]{0,127})\|", content)
        )
        issues: list[str] = []
        if marked_evidence != expected_evidence:
            issues.append(
                "证据标记集合必须保持不变: "
                f"missing={sorted(expected_evidence - marked_evidence)}, "
                f"extra={sorted(marked_evidence - expected_evidence)}"
            )
        if marked_results != expected_results:
            issues.append(
                "结果标记集合必须保持不变: "
                f"missing={sorted(expected_results - marked_results)}, "
                f"extra={sorted(marked_results - expected_results)}"
            )
        if not expected_bookmarks.issubset(marked_bookmarks):
            issues.append(
                f"丢失交叉引用目标: {sorted(expected_bookmarks - marked_bookmarks)}"
            )
        draft = self._sections.create_version(
            task_id=task_id,
            section_id=parent.section_id,
            title=str(value.get("title", "")).strip() or parent.title,
            content=content,
            claim_ids=parent.claim_ids,
            evidence_ids=parent.evidence_ids,
            result_ids=parent.result_ids,
            upstream_artifact_ids=parent.upstream_artifact_ids,
            context_manifest={
                **parent.context_manifest,
                "revision_parent_id": parent.section_draft_id,
                "revision_actor": str(value.get("actor", "author")),
            },
        )
        draft = self._sections.submit_auto_gate(
            task_id,
            draft.section_draft_id,
            passed=not issues,
            report={
                "issues": issues,
                "revision_parent_id": parent.section_draft_id,
                "citation_fingerprint": "passed" if not issues else "failed",
            },
        )
        if issues:
            return Result.fail(
                code=101200,
                msg="作者修订未通过事实/引用指纹 Gate",
                data=draft.to_dict(),
            )
        submitted_draft = self._complete_autosave_submission(
            autosave, draft.section_draft_id
        )
        data = draft.to_dict()
        if submitted_draft is not None:
            data["autosave_draft"] = submitted_draft.metadata()
        return Result.ok(data=data, msg="修订已保存为新版本，等待作者审批")

    def list_section_drafts(self, task_id: str) -> Result[List[Dict[str, Any]]]:
        self._require(task_id)
        self._refresh_section_staleness(task_id)
        return Result.ok(
            data=[
                {
                    **draft.to_dict(),
                    "approvals": self._sections.list_approvals(
                        task_id, draft.section_draft_id
                    ),
                }
                for draft in self._sections.list_task(task_id)
            ],
            msg="分节草稿版本列表",
        )

    def audit_section_drafts(self, task_id: str) -> Result[Dict[str, Any]]:
        self._require(task_id)
        self._refresh_section_staleness(task_id)
        catalog = self._outline_section_catalog(task_id)
        active = {
            section_id: self._sections.get_active(task_id, section_id)
            for section_id in catalog
        }
        missing = [section_id for section_id, draft in active.items() if draft is None]
        return Result.ok(
            data={
                "task_id": task_id,
                "expected_section_ids": list(catalog),
                "approved_section_ids": [
                    section_id for section_id, draft in active.items() if draft is not None
                ],
                "missing_section_ids": missing,
                "can_assemble": bool(catalog) and not missing,
            },
            msg="分节完整性审计完成",
        )

    def assemble_section_drafts(self, task_id: str) -> Result[Dict[str, Any]]:
        rec = self._require_current_ring(task_id, 6)
        audit = self.audit_section_drafts(task_id).data
        if not audit["can_assemble"]:
            raise SectionDraftRegistryError(
                f"仍有分节未批准: {audit['missing_section_ids']}"
            )
        catalog = self._outline_section_catalog(task_id)
        drafts = [self._sections.get_active(task_id, section_id) for section_id in catalog]
        chapters = [
            {
                "section_id": draft.section_id,
                "chapter_title": draft.title,
                "content": draft.content,
                "word_count": len(draft.content.replace("\n", "")),
                "section_draft_id": draft.section_draft_id,
                "section_version": draft.version,
            }
            for draft in drafts
            if draft is not None
        ]
        full_content = self._draft_to_text(chapters)
        evidence_ids = sorted(
            {evidence_id for draft in drafts if draft for evidence_id in draft.evidence_ids}
        )
        result_ids = sorted(
            {result_id for draft in drafts if draft for result_id in draft.result_ids}
        )
        outline = self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
        )
        contract_hash = (
            str(outline.payload.get("contract_hash", "")) if outline is not None else ""
        )
        canon_hash = str(
            self.get_academic_foundation(task_id).data.get("canon_hash", "")
        )
        result_ledger = self._artifacts.get_active(
            task_id=task_id, stage_no=6, kind=ArtifactKind.RESULT_LEDGER
        )
        verified_results = [
            item
            for item in (result_ledger.payload.get("results", []) if result_ledger else [])
            if bool(item.get("verified_by_user"))
        ]
        quality_payload = {
            "chapters": chapters,
            "content": full_content,
            "used_refs": evidence_ids,
            "used_result_ids": result_ids,
        }
        actual_words, quality_issues = self._manuscript_quality_issues(
            rec,
            quality_payload,
            source="approved-sections",
            literature=self._ensure_literature(
                rec, (rec.ring1 or {}).get("chosen", rec.title)
            ),
            verified_results=verified_results,
        )
        if quality_issues:
            raise SectionDraftRegistryError("；".join(quality_issues))
        rec.ring6 = {
            "chapters": chapters,
            "content": full_content,
            "total_words": actual_words,
            "used_refs": evidence_ids,
            "used_result_ids": result_ids,
            "section_draft_ids": [draft.section_draft_id for draft in drafts if draft],
            "canon_hash": canon_hash,
            "contract_hash": contract_hash,
            "compliant": True,
        }
        self._store.put(rec)
        self._fsm.submit_execution(
            task_id, json.dumps(rec.ring6, ensure_ascii=False), accepted=True
        )
        return Result.ok(
            data={
                "chapters": chapters,
                "total_words": rec.ring6["total_words"],
                "section_count": len(chapters),
                "used_evidence_ids": evidence_ids,
                "used_result_ids": result_ids,
            },
            msg="全部批准分节已汇编为环6初稿，等待环6确认",
        )

    def _outline_section_catalog(self, task_id: str) -> Dict[str, str]:
        outline = self._artifacts.get_active(
            task_id=task_id, stage_no=5, kind=ArtifactKind.OUTLINE
        )
        if outline is None:
            return {}
        nodes = [item for item in outline.payload.get("chapters", []) if isinstance(item, dict)]
        sections = self._outline_leaf_nodes(nodes)
        return {
            str(item.get("number", "")).strip(): str(item.get("title", "")).strip()
            for item in sections
            if str(item.get("number", "")).strip()
        }

    def _refresh_section_staleness(self, task_id: str) -> None:
        for draft in self._sections.list_task(task_id):
            if draft.status not in {
                SectionDraftStatus.APPROVED,
                SectionDraftStatus.WAITING_APPROVAL,
                SectionDraftStatus.GENERATED,
            }:
                continue
            for artifact_id in draft.upstream_artifact_ids:
                try:
                    artifact = self._artifacts.get(artifact_id)
                except Exception:  # noqa: BLE001
                    self._sections.mark_stale(
                        task_id, draft.section_draft_id,
                        reason=f"上游产物不存在: {artifact_id}",
                    )
                    break
                if artifact.status != ArtifactStatus.APPROVED:
                    self._sections.mark_stale(
                        task_id, draft.section_draft_id,
                        reason=f"上游产物已失效: {artifact_id}",
                    )
                    break


