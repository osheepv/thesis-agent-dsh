# -*- coding: utf-8 -*-
"""提示词模板仓库（轻量加载器）。

模板位置：backend/prompts/*.md
格式约定：
    第一行必须为 `SYSTEM: <系统提示词>`；
    其余内容为 USER 提示词，占位符用 {变量名}。

安全替换：只替换模板中出现的**已知变量**（{subject_field} 等），
无论模板里有多少 JSON 示例的 { } 花括号都不会误伤——它们不含已知变量名。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict
from functools import lru_cache

#: 模板根目录（backend/prompts/）
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts")

#: 变量名规则（安全替换只认这种名字）
_VAR_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@lru_cache(maxsize=64)
def load_template(name: str) -> Dict[str, str]:
    """加载模板文件，返回 {"system": ..., "prompt": ...}。"""
    path = os.path.join(_PROMPTS_DIR, f"{name}.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        raise FileNotFoundError(f"提示词模板不存在: {path}")
    if not lines or not lines[0].startswith("SYSTEM:"):
        raise ValueError(f"模板 {name}.md 首行必须以 SYSTEM: 开头")
    system = lines[0][len("SYSTEM:"):].strip()
    prompt = "".join(lines[1:]).strip("\n")
    return {"system": system, "prompt": prompt}


def render(name: str, variables: Dict[str, Any]) -> Dict[str, str]:
    """加载模板并只替换已知变量（保持 JSON 示例里的花括号原样）。"""
    tpl = load_template(name)
    return {
        "system": _safe_format(tpl["system"], variables),
        "prompt": _safe_format(tpl["prompt"], variables),
    }


def _safe_format(text: str, variables: Dict[str, Any]) -> str:
    """只替换模板中出现的已知变量；未知形如 {xxx} 的片段原样保留。"""
    def _sub(m: "re.Match") -> str:
        key = m.group(1)
        return str(variables.get(key, m.group(0)))
    return _VAR_RE.sub(_sub, text)
