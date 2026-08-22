# -*- coding: utf-8 -*-
"""文献检索源注册表（Source Registry）——标准检索通道。

产品登记"在册"的检索源白名单，用户/环3 检索时必须经注册表路由，
只能查登记源；未登记/禁用源拒绝（标准通道约束）。

登记的源：
    - 英文权威：crossref（DOI 权威）/ openalex / semanticscholar（当前可用）
    - 中文：metaso（0.03元/次，需 API key；默认 disabled）
    - 中文登记位（未接入，网页引导）：ncpssd（国家社科文献中心，无 API）/
      chinaxiv（中科院预印本，OAI 拒绝匿名）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SearchSource:
    """单个检索源登记项。"""

    source_id: str  # crossref / openalex / semanticscholar / metaso / ...
    name: str
    language: str  # en / zh / mixed
    category: str  # academic / preprint / oa_public / aggregator
    reliability: str  # authoritative / good / supplementary / discovery
    compliant: bool  # 合规标识（True=公开授权/官方 API）
    endpoint: str
    enabled: bool  # 是否可被检索路由使用
    needs_key: bool = False
    notes: str = ""


#: 登记在册的源表（产品标准通道）
_REGISTRY: dict[str, SearchSource] = {
    "crossref": SearchSource(
        source_id="crossref", name="Crossref", language="mixed", category="academic",
        reliability="authoritative", compliant=True,
        endpoint="https://api.crossref.org/works", enabled=True,
        notes="DOI 权威，含注册 DOI 的中文期刊（理工为主），免费 open API",
    ),
    "openalex": SearchSource(
        source_id="openalex", name="OpenAlex", language="en", category="academic",
        reliability="good", compliant=True,
        endpoint="https://api.openalex.org/works", enabled=True,
        notes="大规模学术图，免费 key，中文覆盖有限（37% 期刊/24% 文章，语言常误标）",
    ),
    "semanticscholar": SearchSource(
        source_id="semanticscholar", name="Semantic Scholar", language="en", category="academic",
        reliability="supplementary", compliant=True,
        endpoint="https://api.semanticscholar.org/graph/v1", enabled=True,
        notes="英文为主，免 key 限流 100次/5min（共用池）",
    ),
    "metaso": SearchSource(
        source_id="metaso", name="秘塔AI搜索", language="zh", category="aggregator",
        reliability="discovery", compliant=False,  # 聚合第三方授权数据，合规灰色（知网事件）
        endpoint="https://metaso.cn/api", enabled=False, needs_key=True,
        notes="中文聚合检索 0.03元/次，scope=scholar 学术；数据源由第三方授权，灰色谨慎",
    ),
    "ncpssd": SearchSource(
        source_id="ncpssd", name="国家哲学社会科学文献中心", language="zh", category="oa_public",
        reliability="good", compliant=True,
        endpoint="https://www.ncpssd.cn/", enabled=False,
        notes="国内最大公益社科 OA（免费注册直下），无公开 API（前端 JS 渲染），登记位待网页引导",
    ),
    "chinaxiv": SearchSource(
        source_id="chinaxiv", name="ChinaXiv 中科院预印本", language="zh", category="preprint",
        reliability="supplementary", compliant=True,
        endpoint="https://www.chinaxiv.org/oai/", enabled=False,
        notes="中文理工预印本，OAI-PMH 但拒绝匿名访问（可能需机构授权），登记位待确认",
    ),
}

#: scope 预定义：用户可选范围
SCOPE_PRESETS: dict[str, List[str]] = {
    "english": ["crossref", "openalex", "semanticscholar"],
    "chinese": ["metaso", "ncpssd", "chinaxiv"],  # 未启用源由路由层跳过并提示
    "all": ["crossref", "openalex", "semanticscholar", "metaso", "ncpssd", "chinaxiv"],
}


def get_source(source_id: str) -> Optional[SearchSource]:
    """按 ID 取登记源；未登记返回 None。"""
    return _REGISTRY.get(source_id)


def get_registry() -> Dict[str, SearchSource]:
    """全部登记源（只读视图）。"""
    return dict(_REGISTRY)


def get_enabled_sources() -> List[str]:
    """当前启用（可检索）的源 ID。返回 API 层启用源 + 引导层源。

    引导层源（ncpssd/chinaxiv 等）不需要 API key，`enabled=False` 表示
    "未接 API 但作为网页引导层始终提供"——用户自取，不受开关限制。
    """
    result: List[str] = []
    for sid, s in _REGISTRY.items():
        if s.enabled or s.category in ("oa_public", "preprint", "aggregator"):
            result.append(sid)
    return result


def resolve_scope(scope: Optional[str] = None, source_ids: Optional[List[str]] = None) -> List[str]:
    """把 scope/source_ids 解析为"要路由的源 ID 列表"（已启用且已登记的）。

    Args:
        scope: 预定义范围 english/chinese/all；None 用 source_ids。
        source_ids: 显式源列表。
    Returns:
        启用的源 ID 列表（禁用/未登记被剔除）。
    Raises:
        ValueError: 请求了未登记/未知的源 ID。
    """
    if source_ids:
        # 显式源列表：校验登记 + 启用
        unknown = [sid for sid in source_ids if sid not in _REGISTRY]
        if unknown:
            raise ValueError(f"未登记的检索源: {unknown}（仅支持 {'/'.join(_REGISTRY)}）")
        disabled = [sid for sid in source_ids if not _REGISTRY[sid].enabled]
        # 返回启用部分；禁用的由调用方提示（不静默跳过）
        return [sid for sid in source_ids if _REGISTRY[sid].enabled]

    if scope is None or scope == "all":
        return get_enabled_sources()
    preset = SCOPE_PRESETS.get(scope)
    if preset is None:
        raise ValueError(f"未知检索范围 scope: {scope}（可选 {', '.join(SCOPE_PRESETS)}）")
    # 引导层源始终提供（用户自取平台），API 层需 enabled
    return [sid for sid in preset if _REGISTRY[sid].enabled or _REGISTRY[sid].category in
            ("oa_public", "preprint", "aggregator")]


def registry_summary() -> List[Dict[str, Any]]:
    """注册表摘要（供 API/展示）。"""
    return [
        {
            "source_id": s.source_id,
            "name": s.name,
            "language": s.language,
            "category": s.category,
            "reliability": s.reliability,
            "compliant": s.compliant,
            "enabled": s.enabled,
            "endpoint": s.endpoint,
            "notes": s.notes,
        }
        for s in _REGISTRY.values()
    ]
