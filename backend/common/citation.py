# -*- coding: utf-8 -*-
"""GB/T 7714-2015 参考文献格式化（决策 D5：pybtex + bib_lookup GBT7714Style）。

设计要点：
    1. 优先用 bib_lookup.styles.GBT7714Style（纯 Python，无需 LaTeX），
       把 LitItem 映射为 pybtex Entry 后格式化。
    2. bib_lookup 不可用时回退自研格式化器（期刊/会议/学位论文/专著四类）。
    3. 输出严格国标风格：`作者1, 作者2, 作者3, 等. 标题[J]. 期刊, 年, 卷(期): 页.`
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("thesis.citation")


def _to_bib_entry(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """LitItem dict → pybtex Entry 字段（用于格式化）。"""
    title = item.get("title", "")
    if not title:
        return None
    authors = item.get("authors") or []
    year = item.get("year") or ""
    venue = item.get("venue", "")
    doi = item.get("doi", "")
    item_type = item.get("item_type", "article")

    fields: Dict[str, Any] = {
        "title": title,
        "year": str(year) if year else "",
    }
    if authors:
        fields["author"] = " and ".join(authors)

    # 按类型填充
    if item_type == "thesis":
        fields["type"] = "博士/硕士学位论文"
        fields["school"] = venue
    elif item_type == "conference":
        fields["booktitle"] = venue
    elif item_type == "book":
        fields["publisher"] = venue
    else:  # article / other
        fields["journal"] = venue
        if item.get("volume"):
            fields["volume"] = str(item["volume"])
        if item.get("issue"):
            fields["number"] = str(item["issue"])
        if item.get("pages"):
            fields["pages"] = str(item["pages"]).replace("-", "--")

    return {"bib_type": item_type, "fields": fields}


def format_gbt7714(item: Dict[str, Any]) -> str:
    """把一条文献题录格式化为 GB/T 7714-2015 字符串。

    优先走 pybtex + GBT7714Style；库不可用时自研格式化。
    """
    try:
        from pybtex.database import Entry, BibliographyData
        bib = _to_bib_entry(item)
        if bib is not None:
            from bib_lookup.styles import GBT7714Style

            entry = Entry(bib["bib_type"] if bib["bib_type"] != "article" else "article",
                          fields={k: v for k, v in bib["fields"].items()})
            data = BibliographyData(entries={"_": entry})
            style = GBT7714Style()
            formatted = style.format_bibliography(data)
            if formatted.entries:
                return str(formatted.entries[0].text)
    except Exception as exc:  # noqa: BLE001
        logger.info("pybtex 格式化不可用，回退自研: %s", exc)

    return _fallback_format(item)


def _fallback_format(item: Dict[str, Any]) -> str:
    """自研 GB/T 7714 格式化（pybtex 不可用时）。"""
    title = item.get("title", "")
    authors = item.get("authors") or []
    year = item.get("year") or ""
    venue = item.get("venue") or ""
    item_type = item.get("item_type", "article")
    doi = item.get("doi", "")

    # 作者：前3 + 等
    if authors:
        auth_txt = ", ".join(authors[:3])
        if len(authors) > 3:
            auth_txt += ", 等."
        else:
            auth_txt += "."
    else:
        auth_txt = "佚名."

    # 类型标识
    type_marker = {
        "article": "[J]",
        "conference": "[C]",
        "thesis": "[D]",
        "book": "[M]",
        "report": "[R]",
    }.get(item_type, "[J]")

    rest = []
    if item_type == "article":
        rest.append(f"{venue}, {year}" if venue else str(year))
        if item.get("volume"):
            vol = f"{item['volume']}({item['issue']})" if item.get("issue") else f"{item['volume']}"
            rest[-1] += f", {vol}"
        if item.get("pages"):
            rest[-1] += f": {item['pages']}."
        else:
            rest[-1] += "."
    elif item_type == "thesis":
        rest.append(f"{venue}, {year}." if venue else f"{year}.")
    elif item_type == "conference":
        rest.append(f"{venue}, {year}." if venue else f"{year}.")
    else:
        rest.append(f"{venue}, {year}." if venue else f"{year}.")

    return f"{auth_txt} {title}{type_marker}. {' '.join(rest)}"


def format_many(items: List[Dict[str, Any]]) -> List[str]:
    """批量格式化。"""
    out = []
    for it in items:
        try:
            out.append(format_gbt7714(it))
        except Exception as exc:  # noqa: BLE001
            logger.warning("格式化失败: %s", exc)
            out.append(f"[未格式化] {it.get('title', '')}")
    return out
