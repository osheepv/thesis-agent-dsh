# -*- coding: utf-8 -*-
"""M5 模板解析器：模板安全校验 + Jinja2 占位符提取 + 骨架结构识别。

设计要点：
    - 模板安全校验清单（用户约束“docx 模板安全”）：
        1) 扩展名白名单：仅 `.docx`，拒绝 `.docm`/`.dotm`/`.doc`/`.dot`（含宏）。
        2) 魔数校验：DOCX 是 ZIP 容器，头 4 字节须为 `PK\\x03\\x04`。
        3) 大小校验：≤ `DocxConfig.MAX_TEMPLATE_SIZE_MB`。
        4) 宏部件拒绝：包内不得含 `vbaProject.bin`（宏项目二进制）。
        5) 随机重命名存储：落盘文件名用 uuid，屏蔽原始文件名（由调用方/存储层落地）。
    - 占位符提取：正则匹配 Jinja2 `{{ identifier }}`，去重并保留出现顺序。
    - 骨架结构：遍历段落，按标题样式（Heading/标题 N）与内容块占位符划分章节。
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional

from docx import Document
from docx.text.paragraph import Paragraph

from common.aicoding.exception import BizException, ErrorCode

from ..config import DocxConfig
from ..dto.base import SectionSkeleton, TemplateParseVO

#: Jinja2 占位符正则：{{ identifier }} / {{ identifier.filter }}
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][\w\.]*)\s*\}\}")

#: 标题样式名映射到级别（兼容英文 Heading 与中文标题）
_HEADING_STYLE_MAP: dict[str, int] = {
    "title": 0,
    "heading 1": 1,
    "heading 2": 2,
    "heading 3": 3,
    "heading 4": 4,
    "标题 1": 1,
    "标题 2": 2,
    "标题 3": 3,
    "标题 4": 4,
}

#: 内容块占位符名（出现在正文中通常代表整章内容替换点）
_CONTENT_BLOCK_NAMES = {"content", "chapter", "body", "正文", "章节"}


@dataclass
class ParseOutcome:
    """一次解析的内部结果载体。

    Attributes:
        placeholders: 去重后的占位符名（按出现顺序）。
        skeleton: 骨架章节结构。
        paragraphs: 全文段落文本（供存储/诊断，可选）。
    """

    placeholders: List[str] = field(default_factory=list)
    skeleton: List[SectionSkeleton] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)


class TemplateParser:
    """M5 模板解析器。

    Args:
        config: docx 模块配置（可注入自定义，便于测试探测阈值）。
    """

    def __init__(self, config: Optional[DocxConfig] = None) -> None:
        self._config = config or DocxConfig()

    # ------------------------------------------------------------------ #
    # 对外入口
    # ------------------------------------------------------------------ #
    def validate_and_parse(self, file_bytes: bytes, original_name: str) -> ParseOutcome:
        """模板安全校验并解析，返回占位符与骨架。

        Args:
            file_bytes: 模板文件二进制。
            original_name: 用户上传的原始文件名（用于扩展名白名单校验）。

        Raises:
            BizException: 任一安全校验不通过或解析失败时抛出。
        """
        self._check_extension(original_name)
        self._check_size(file_bytes)
        self._check_magic(file_bytes)
        self._check_zip_parts(file_bytes)
        return self._parse_to_outcome(file_bytes)

    def extract_placeholders(self, file_bytes: bytes) -> List[str]:
        """仅提取占位符（供校验/详情接口复用）。"""
        return self._parse_to_outcome(file_bytes).placeholders

    # ------------------------------------------------------------------ #
    # 安全校验清单
    # ------------------------------------------------------------------ #
    def _check_extension(self, original_name: str) -> None:
        """扩展名白名单校验：仅 .docx，拒绝带宏的 .docm/.dotm 等。"""
        name = (original_name or "").strip().lower()
        ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
        if ext in self._config.ALLOWED_EXTENSIONS:
            return
        # 给出更明确的拒绝原因（区分“带宏”与“一般非法”）
        if ext == ".docm":
            raise BizException(
                ErrorCode.DOCX_TEMPLATE_INVALID,
                "禁止上传包含宏的 docm 模板",
                detail={"extension": ext},
            )
        raise BizException(
            ErrorCode.DOCX_TEMPLATE_INVALID,
            f"仅支持 .docx 模板，收到扩展名为 {ext or '(无)'}",
            detail={"extension": ext, "allowed": sorted(self._config.ALLOWED_EXTENSIONS)},
        )

    def _check_size(self, file_bytes: bytes) -> None:
        """大小校验：≤ 配置上限（默认 50MB）。"""
        size = len(file_bytes)
        limit = self._config.MAX_TEMPLATE_SIZE_MB * 1024 * 1024
        if size > limit:
            raise BizException(
                ErrorCode.DOCX_TEMPLATE_INVALID,
                f"模板文件过大：{size / 1024 / 1024:.2f}MB > {self._config.MAX_TEMPLATE_SIZE_MB}MB",
                detail={"size": size, "limit": limit},
            )

    @staticmethod
    def _check_magic(file_bytes: bytes) -> None:
        """魔数校验：DOCX 为 ZIP 容器，头部须为 PK\\x03\\x04。"""
        magic = file_bytes[:4]
        if magic != b"PK\x03\x04":
            raise BizException(
                ErrorCode.DOCX_TEMPLATE_INVALID,
                "文件魔数非法，不是合法的 docx（ZIP）文件",
                detail={"magic": magic.hex()},
            )

    def _check_zip_parts(self, file_bytes: bytes) -> None:
        """校验 ZIP 包内不得含宏部件（vbaProject.bin）等被拒部件。"""
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = zf.namelist()
                lower_names = {n.lower() for n in names}
                for reject in self._config.REJECT_PART_NAMES:
                    if reject.lower() in lower_names or any(
                        reject.lower() in n for n in lower_names
                    ):
                        raise BizException(
                            ErrorCode.DOCX_TEMPLATE_INVALID,
                            f"模板包含被拒绝的部件：{reject}（含宏，禁止）",
                            detail={"part": reject},
                        )
                # 完整性：应包含 document.xml
                if not any(n.endswith("word/document.xml") for n in names):
                    raise BizException(
                        ErrorCode.DOCX_PARSE_FAILED,
                        "模板缺少 word/document.xml，不是有效的 Word 文档",
                    )
        except zipfile.BadZipFile as exc:
            raise BizException(
                ErrorCode.DOCX_TEMPLATE_INVALID, "模板不是有效的 ZIP（OOXML）容器", detail={"err": str(exc)}
            ) from exc

    # ------------------------------------------------------------------ #
    # 解析
    # ------------------------------------------------------------------ #
    def _parse_to_outcome(self, file_bytes: bytes) -> ParseOutcome:
        """解析占位符与骨架。"""
        try:
            doc = Document(io.BytesIO(file_bytes))
        except Exception as exc:  # noqa: BLE001
            raise BizException(
                ErrorCode.DOCX_PARSE_FAILED, "模板解析失败", detail={"err": str(exc)}
            ) from exc

        paragraphs: List[str] = []
        ordered_names: List[str] = []
        seen: set[str] = set()
        skeleton: List[SectionSkeleton] = []

        for idx, para in enumerate(doc.paragraphs):
            text = para.text or ""
            paragraphs.append(text)
            # 占位符提取
            for match in _PLACEHOLDER_RE.finditer(text):
                name = match.group(1)
                if name not in seen:
                    seen.add(name)
                    ordered_names.append(name)
            # 骨架章节识别
            skeleton.append(self._section_from_paragraph(idx, para, text))

        skeleton = self._compact_sections(skeleton)
        return ParseOutcome(placeholders=ordered_names, skeleton=skeleton, paragraphs=paragraphs)

    def _section_from_paragraph(self, index: int, para: Paragraph, text: str) -> SectionSkeleton:
        """将单个段落映射为骨架章节（标题/内容块占位符）。"""
        style_name = (para.style.name or "").strip().lower() if para.style else ""
        level = _HEADING_STYLE_MAP.get(style_name, 0)

        # 内容块占位符：出现在正文段落的该占位符视为章节锚点
        block_placeholder = ""
        for match in _PLACEHOLDER_RE.finditer(text):
            name = match.group(1)
            if name.lower() in _CONTENT_BLOCK_NAMES:
                block_placeholder = name
                break

        heading = text.strip()
        if not heading and level == 0:
            heading = ""
        return SectionSkeleton(
            index=index,
            heading=heading[:80],  # 截断避免过长
            placeholder=block_placeholder,
            level=level,
            paragraph_count=1,
        )

    def _compact_sections(self, raw: List[SectionSkeleton]) -> List[SectionSkeleton]:
        """压缩骨架：合并标题与其后连续普通段落到一个章节块。"""
        compact: List[SectionSkeleton] = []
        current: Optional[SectionSkeleton] = None
        for item in raw:
            is_heading = item.level > 0 or bool(item.placeholder)
            if is_heading:
                if current is not None:
                    compact.append(current)
                current = item
            else:
                if current is None:
                    # 无标题前缀的正文（模板开头说明），视为匿名节
                    current = SectionSkeleton(
                        index=len(compact), heading="(前置内容)", placeholder="", level=0,
                        paragraph_count=0,
                    )
                current.paragraph_count += 1
        if current is not None:
            compact.append(current)

        # 重排 index 为连续序号
        for i, sec in enumerate(compact):
            sec.index = i
        return compact


def extract_placeholders_from_text(text: str) -> List[str]:
    """静态工具：从文本中提取占位符名（供测试/诊断）。"""
    return _PLACEHOLDER_RE.findall(text)
