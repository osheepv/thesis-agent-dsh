"""十阶段宏观工作流的单一契约源。

阶段编号保持现有 API/FSM 兼容；研究设计、实验实施和结果血缘作为环5/环6
必须补齐的内部工作流，不再另造一套与十环冲突的编号。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageContract:
    ring_no: int
    label: str
    objective: str
    required_artifact_kinds: tuple[str, ...]
    implemented_artifact_kinds: tuple[str, ...]
    runtime_artifact_kind: str
    user_decision: str
    reentry_targets: tuple[int, ...] = ()

    @property
    def is_fully_implemented(self) -> bool:
        return set(self.required_artifact_kinds).issubset(self.implemented_artifact_kinds)

    @property
    def missing_artifact_kinds(self) -> tuple[str, ...]:
        implemented = set(self.implemented_artifact_kinds)
        return tuple(kind for kind in self.required_artifact_kinds if kind not in implemented)


STAGE_CONTRACTS: dict[int, StageContract] = {
    1: StageContract(
        1,
        "选题",
        "澄清项目约束并收敛可研究的论文方向",
        ("PROJECT_BRIEF", "TOPIC_PROPOSAL"),
        ("TOPIC_PROPOSAL",),
        "TOPIC_PROPOSAL",
        "确认项目约束、候选题目和研究问题",
    ),
    2: StageContract(
        2,
        "开题评审",
        "核验新颖性、可行性、资源与伦理风险",
        ("FEASIBILITY_REVIEW",),
        ("FEASIBILITY_REVIEW",),
        "FEASIBILITY_REVIEW",
        "通过开题方案，或退回环1修改方向",
        (1,),
    ),
    3: StageContract(
        3,
        "文献调研",
        "执行可复现检索、合法获取、去重、筛选和项目知识库登记",
        ("LITERATURE_CORPUS",),
        ("LITERATURE_CORPUS",),
        "LITERATURE_CORPUS",
        "确认纳入、排除和需要补检索的文献",
        (2,),
    ),
    4: StageContract(
        4,
        "综述评审",
        "形成证据矩阵、主题综合、争议与研究空白",
        ("EVIDENCE_SYNTHESIS",),
        ("EVIDENCE_SYNTHESIS",),
        "EVIDENCE_SYNTHESIS",
        "确认综述结论、研究空白和切入角度",
        (2, 3),
    ),
    5: StageContract(
        5,
        "大纲生成",
        "锁定研究方案、实验/实施手册、论证蓝图和详细大纲",
        ("RESEARCH_PROTOCOL", "ARGUMENT_MAP", "OUTLINE"),
        ("RESEARCH_PROTOCOL", "ARGUMENT_MAP", "OUTLINE"),
        "OUTLINE",
        "确认研究实施方案、证据分配和章节结构",
        (3, 4),
    ),
    6: StageContract(
        6,
        "初稿撰写",
        "登记研究执行产物和结果血缘，并按节生成可审查草稿",
        ("RESULT_LEDGER", "SECTION_DRAFT"),
        ("RESULT_LEDGER", "SECTION_DRAFT"),
        "SECTION_DRAFT",
        "逐节确认研究结果表述、证据绑定和章节草稿",
        (3, 5),
    ),
    7: StageContract(
        7,
        "修改润色",
        "在保持事实、数字和引用不变的前提下完成结构与语言修订",
        ("REVISION",),
        ("REVISION",),
        "REVISION",
        "接受修订，或将结构性问题退回环5/环6",
        (5, 6),
    ),
    8: StageContract(
        8,
        "引用校验",
        "核验主张—证据、数字—结果、正文引文—参考文献的完整链路",
        ("CITATION_AUDIT",),
        ("CITATION_AUDIT",),
        "CITATION_AUDIT",
        "修复阻断项，或明确接受非阻断风险",
        (3, 6, 7),
    ),
    9: StageContract(
        9,
        "定稿排版",
        "按学校模板生成含稳定编号与交叉引用的正式稿",
        ("FORMATTED_MANUSCRIPT",),
        ("FORMATTED_MANUSCRIPT",),
        "FORMATTING_AUDIT",
        "确认格式检查结果和正式稿",
        (7, 8),
    ),
    10: StageContract(
        10,
        "终稿交付",
        "汇总版本、审计、参考文献、交叉引用和最终文件清单",
        ("DELIVERY_MANIFEST",),
        ("DELIVERY_MANIFEST",),
        "DELIVERY_MANIFEST",
        "完成作者最终签字确认",
        (6, 7, 8, 9),
    ),
}


def get_stage_contract(ring_no: int) -> StageContract:
    try:
        return STAGE_CONTRACTS[ring_no]
    except KeyError as exc:
        raise ValueError("ring_no 必须在 1..10") from exc


def workflow_gap_report() -> dict[int, tuple[str, ...]]:
    """返回尚未落地的强制产物，供健康检查和建设路线使用。"""
    return {
        ring_no: contract.missing_artifact_kinds
        for ring_no, contract in STAGE_CONTRACTS.items()
        if contract.missing_artifact_kinds
    }


if tuple(STAGE_CONTRACTS) != tuple(range(1, 11)):
    raise RuntimeError("十阶段契约必须且只能包含 1..10")
