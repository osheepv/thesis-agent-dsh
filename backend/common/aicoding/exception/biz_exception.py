# -*- coding: utf-8 -*-
"""业务异常定义。"""
from __future__ import annotations

from typing import Any, Optional

from .error_code import ErrorCode


class BizException(Exception):
    """业务异常。

    Attributes:
        code: 6 位字符串错误码（ErrorCode）。
        msg: 可读错误信息。
        http_status: 建议映射的 HTTP 状态码（默认 200，业务信封统一用 code 表达）。
        detail: 附加上下文。
    """

    def __init__(
        self,
        code: str | ErrorCode,
        msg: Optional[str] = None,
        http_status: int = 200,
        detail: Optional[Any] = None,
    ) -> None:
        self.code = code.value if isinstance(code, ErrorCode) else code
        self.error_code = code
        self.msg = msg or (
            code.default_msg if isinstance(code, ErrorCode) else "业务处理失败"
        )
        self.http_status = http_status
        self.detail = detail
        super().__init__(self.msg)

    def to_dict(self) -> dict[str, Any]:
        """转为可序列化字典（供 Result.fail 组装）。"""
        return {
            "code": int(self.code) if self.code.isdigit() else self.code,
            "msg": self.msg,
            "detail": self.detail,
        }
