# -*- coding: utf-8 -*-
"""docx 核心 DTO：模板解析 VO、生成/校验请求/响应。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SectionSkeleton(BaseModel):
    """模板骨架章节块描述。

    Attributes:
        index: 章节在模板中的序号（按出现顺序）。
        heading: 章节标题文本（若为占位符则记录占位符名）。
        placeholder: 该章节绑定的占位符名（如内容块），无则空串。
        level: 标题级别（1 章 / 2 节 / 3 小节），0 表示普通段落。
        paragraph_count: 该章节区域内的段落数。
    """

    index: int = Field(default=0, description="章节序号")
    heading: str = Field(default="", description="章节标题文本")
    placeholder: str = Field(default="", description="绑定占位符名，无则空")
    level: int = Field(default=0, description="标题级别，0 为普通段落")
    paragraph_count: int = Field(default=0, description="区域内段落数")


class TemplateParseVO(BaseModel):
    """模板解析结果 VO（M5 输出）。

    Attributes:
        template_id: 模板 ID（uuid）。
        template_name: 用户上传的原始文件名。
        session_id: 会话 ID（会话绑定式隔离）。
        placeholders: 解析出的 Jinja2 占位符列表（去重、按出现顺序）。
        placeholder_count: 占位符数量。
        skeleton_sections: 骨架章节结构（章节/占位符分布）。
        section_count: 骨架章节数量。
        file_hash: 模板文件 SHA-256。
        file_size: 模板文件字节数。
        parse_status: PARSED / FAILED。
    """

    template_id: str = Field(..., description="模板 ID")
    template_name: str = Field(default="", description="原始文件名")
    session_id: str = Field(default="", description="会话 ID")
    placeholders: List[str] = Field(default_factory=list, description="占位符列表")
    placeholder_count: int = Field(default=0, description="占位符数量")
    skeleton_sections: List[SectionSkeleton] = Field(
        default_factory=list, description="骨架章节结构"
    )
    section_count: int = Field(default=0, description="骨架章节数量")
    file_hash: str = Field(default="", description="模板 SHA-256")
    file_size: int = Field(default=0, description="模板字节数")
    parse_status: str = Field(default="PARSED", description="解析状态 PARSED/FAILED")


class DocxGenerateRequest(BaseModel):
    """docx 生成请求。

    Attributes:
        template_id: 使用的模板 ID。
        session_id: 会话 ID（归属校验）。
        content: 内容映射，键为占位符名，值为要代入的文本。
                 （如 topic / outline / chapter，与模板占位符一一对应）
        filename: 生成文件名（可选，默认 <template_name>_render.docx）。
    """

    template_id: str = Field(..., description="模板 ID")
    session_id: str = Field(default="", description="会话 ID")
    content: Dict[str, Any] = Field(default_factory=dict, description="占位符->内容映射")
    filename: Optional[str] = Field(default=None, description="生成文件名（可选）")


class DocxGenerateResult(BaseModel):
    """docx 生成产出。

    Attributes:
        file_id: 生成文件 ID（uuid）。
        download_url: 下载链接。
        filename: 生成文件名。
        word_count: 估算字数（剔除空白字符）。
        validation: 生成后即校验的快照；序列化字段名保持为 `validate`。
        file_hash: 生成文件 SHA-256（可选，便于去重比对）。
    """

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    file_id: str = Field(..., description="生成文件 ID")
    download_url: str = Field(..., description="下载链接")
    filename: str = Field(default="", description="生成文件名")
    word_count: int = Field(default=0, description="估算字数")
    file_hash: str = Field(default="", description="生成文件 SHA-256")
    validation: Optional["DocxValidateResult"] = Field(
        default=None,
        alias="validate",
        description="生成后校验快照",
    )


class DocxValidateRequest(BaseModel):
    """docx 校验请求。

    Attributes:
        file_id: 待校验文件的 ID（须在 docx 输出域内存在）。
        session_id: 会话 ID（归属校验）。
        strict: 是否严格 schema 校验（默认 true）。
    """

    file_id: str = Field(..., description="待校验文件 ID")
    session_id: str = Field(default="", description="会话 ID")
    strict: bool = Field(default=True, description="是否严格 schema 校验")


class DocxValidateResult(BaseModel):
    """docx 校验结果。

    Attributes:
        is_valid: 是否通过校验（schema/roundtrip/load 三项均通过）。
        schema_valid: OOXML schema 校验是否通过。
        load_valid: 能否被目标应用加载（load 校验）。
        roundtrip_valid: roundtrip（保存重载）校验是否通过。
        error_count: 错误数。
        warning_count: 警告数。
        errors: 错误明细（openxml_audit 抽取的 description/severity/part）。
        warnings: 警告明细。
        validator: 使用的校验器版本。
        file_id: 被校验文件 ID（可选）。
    """

    is_valid: bool = Field(default=False, description="是否通过校验")
    schema_valid: bool = Field(default=False, description="schema 校验是否通过")
    load_valid: bool = Field(default=False, description="load 校验是否通过")
    roundtrip_valid: bool = Field(default=False, description="roundtrip 校验是否通过")
    error_count: int = Field(default=0, description="错误数")
    warning_count: int = Field(default=0, description="警告数")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="错误明细")
    warnings: List[Dict[str, Any]] = Field(default_factory=list, description="警告明细")
    validator: str = Field(default="openxml-audit", description="校验器版本")
    file_id: str = Field(default="", description="被校验文件 ID")
