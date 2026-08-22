# -*- coding: utf-8 -*-
"""M5/M6 docx 模块配置。

集中管理模板解析与生成的安全阈值、存储路径、校验容忍度等常量。
配置来源优先级（与 common 约定一致）：环境变量 > 默认值。
"""
from __future__ import annotations

import os
from pathlib import Path


class DocxConfig:
    """docx 模块静态配置。

    Attributes:
        MAX_TEMPLATE_SIZE_MB: 模板文件大小上限（MB），超限拒绝。
        MAX_GENERATED_SIZE_MB: 生成 docx 大小上限（MB），超限视为异常。
        ALLOWED_EXTENSIONS: 允许的模板扩展名白名单（覆盖 .docx；.docm/.dotm 拒绝）。
        MACRO_PART_NAME: 宏部件名（含宏模板核心拒绝规则）。
        REJECT_PART_NAMES: 在模板包内出现的绝对拒绝部件名（宏/外部内容）。
        UPLOAD_DIR: 上传模板落盘根目录（已重命名，不可执行）。
        OUTPUT_DIR: 生成 docx 落盘根目录。
        VALIDATE_STRICT: openxml-audit 是否开启严格 schema 校验。
        VALIDATE_MAX_ERRORS: 校验最多记录的错误条数。
    """

    #: 模板大小上限（MB）
    MAX_TEMPLATE_SIZE_MB: int = int(os.getenv("DOCX_MAX_TEMPLATE_SIZE_MB", "50"))
    #: 生成产物大小上限（MB）
    MAX_GENERATED_SIZE_MB: int = int(os.getenv("DOCX_MAX_GENERATED_SIZE_MB", "100"))
    #: 模板扩展名白名单（仅 .docx，拒绝带宏的 .docm/.dotm/.dot/.doc）
    ALLOWED_EXTENSIONS: set[str] = {".docx"}
    #: 宏部件名（OOXML 宏项目，检测到即拒绝）
    MACRO_PART_NAME: str = "vbaProject.bin"
    #: 绝对拒绝的部件名集合（宏、外部嵌入等）
    REJECT_PART_NAMES: set[str] = {"vbaProject.bin"}
    #: 上传模板存储目录
    UPLOAD_DIR: Path = Path(
        os.getenv(
            "DOCX_UPLOAD_DIR",
            str(Path(__file__).resolve().parent / "storage" / "templates"),
        )
    )
    #: 生成产物存储目录
    OUTPUT_DIR: Path = Path(
        os.getenv(
            "DOCX_OUTPUT_DIR",
            str(Path(__file__).resolve().parent / "storage" / "outputs"),
        )
    )
    #: 内置论文模板路径（无用户模板时的兜底模板，含标准论文占位符）。
    #: 默认位于本包 templates/ 下，可通过 DOCX_BUILTIN_TEMPLATE_PATH 环境变量覆盖。
    BUILTIN_TEMPLATE_PATH: Path = Path(
        os.getenv(
            "DOCX_BUILTIN_TEMPLATE_PATH",
            str(Path(__file__).resolve().parent / "templates" / "builtin_thesis_template.docx"),
        )
    )
    #: openxml-audit 是否严格 schema 校验
    VALIDATE_STRICT: bool = os.getenv("DOCX_VALIDATE_STRICT", "true").lower() == "true"
    #: 校验最多记录错误数
    VALIDATE_MAX_ERRORS: int = int(os.getenv("DOCX_VALIDATE_MAX_ERRORS", "200"))
