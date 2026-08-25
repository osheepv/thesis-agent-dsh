"""只使用批准论断、证据和结果的分节草稿生成器。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from common import prompt_repo
from common.llm import get_llm_client, get_llm_settings, LLMError
from thesis_docx.cross_reference import normalize_target_id


class SectionGeneration(BaseModel):
    title: str = ""
    content: str = ""
    covered_claim_ids: list[str] = Field(default_factory=list)
    used_evidence_ids: list[str] = Field(default_factory=list)
    used_result_ids: list[str] = Field(default_factory=list)
    generation_source: str = ""


class SectionDraftGenerator:
    def generate(self, context: dict[str, Any]) -> SectionGeneration:
        settings = get_llm_settings()
        if settings.enabled and settings.api_key:
            tpl = prompt_repo.render(
                "section_draft",
                {"section_context": json.dumps(context, ensure_ascii=False)},
            )
            generated = get_llm_client().generate_json(
                system=tpl["system"],
                prompt=tpl["prompt"],
                model_cls=SectionGeneration,
                temperature=0.2,
                max_output_tokens=8192,
            )
            generated.generation_source = "deepseek"
            return generated
        if not settings.fallback_to_mock:
            raise LLMError("分节写作需要可用的 LLM；正式模式禁止静默回退 Mock")
        return self._fallback(context)

    @staticmethod
    def _fallback(context: dict[str, Any]) -> SectionGeneration:
        claims = context.get("claims", []) or []
        results = context.get("results", []) or []
        paragraphs: list[str] = []
        evidence_ids: list[str] = []
        for claim in claims:
            ids = list(claim.get("supporting_evidence_ids", []) or [])
            evidence_ids.extend(ids)
            marker = "" if not ids else " " + " ".join(f"[{item}]" for item in ids)
            paragraphs.append(f"{claim.get('text', '')}{marker}")
        if results:
            for item in results:
                result_id = str(item.get("result_id", ""))
                target = normalize_target_id(
                    str(item.get("table_or_figure_id", "")) or result_id
                )
                display = _display_cross_reference(target)
                paragraphs.append(
                    f"[[BOOKMARK:{target}|{display} {item.get('metric')}结果]]\n"
                    f"经用户核验，{item.get('metric')}="
                    f"{item.get('value')}{item.get('unit', '')} [{result_id}]。"
                )
        if not paragraphs:
            paragraphs.append("本节为结构性说明，不包含未经证据支持的事实或数字结论。")
        return SectionGeneration(
            title=str(context.get("title", "")),
            content="\n\n".join(paragraphs),
            covered_claim_ids=[str(item.get("claim_id", "")) for item in claims],
            used_evidence_ids=list(dict.fromkeys(evidence_ids)),
            used_result_ids=[str(item.get("result_id", "")) for item in results],
            generation_source="mock",
        )


def _display_cross_reference(target: str) -> str:
    upper = target.upper()
    if upper.startswith("TABLE-"):
        return "表" + target[6:]
    if upper.startswith("FIGURE-"):
        return "图" + target[7:]
    return target
