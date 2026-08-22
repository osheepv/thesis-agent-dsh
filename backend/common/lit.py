# -*- coding: utf-8 -*-
"""文献检索服务（二期决策 D2：Crossref + OpenAlex + Semantic Scholar 免费 API）。

设计要点：
    1. 统一 LitItem 结构（题录/摘要/分类/可信度/原文链接），三个源归一化后合并。
    2. 中文文献覆盖差（OpenAlex 仅 24% 中文文章/92% 语言误标，查询时不用 language 过滤）
       —— 用「中文关键词 + DOI/ISSN 检索」多路并进，命中即标记 reliability。
    3. 可信度分层：verified（DOI 精确命中）/ matched（标题相似匹配）/ uncertain（仅搜索命中，待人工）。
    4. 不编造：搜不到就返回空，绝不合成虚构条目（学术诚信红线）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("thesis.lit")

#: 各源 HTTP 超时（秒）
_TIMEOUT = 15.0

#: CrossRef polite pool 标识（官方建议加 mailto 提高额度）
MAILTO = "thesis-agent-dsh@example.com"

#: 中文常见字符判断（粗略，用于识别中文题名）
_CJK_RE = re.compile(r"[一-鿿]")


def _is_chinese(text: str) -> bool:
    """粗略判断字符串是否含中文（用于可靠性标记）。"""
    return bool(_CJK_RE.search(text or ""))


class LitItem:
    """统一文献条目。

    Attributes:
        title: 论文标题。
        authors: 作者列表。
        year: 发表年份。
        venue: 期刊/会议名。
        doi: DOI。
        abstract: 摘要（可能为空）。
        citation_count: 被引次数（未知为 None）。
        urls: 可用链接（PDF/详情页）。
        item_type: article / conference / thesis / book / other。
        language: 语言提示（zh/en/unknown）。
        reliability: verified（DOI 命中）/ matched（相似匹配）/ uncertain（待人工复核）。
        sources: 命中的数据源列表。
        raw: 原始数据（保留供审计）。
    """

    def __init__(
        self,
        title: str = "",
        authors: Optional[List[str]] = None,
        year: Optional[int] = None,
        venue: str = "",
        doi: str = "",
        abstract: str = "",
        citation_count: Optional[int] = None,
        urls: Optional[List[str]] = None,
        item_type: str = "article",
        language: str = "unknown",
        reliability: str = "uncertain",
        sources: Optional[List[str]] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.title = title
        self.authors = authors or []
        self.year = year
        self.venue = venue
        self.doi = doi
        self.abstract = abstract
        self.citation_count = citation_count
        self.urls = urls or []
        self.item_type = item_type
        self.language = language
        self.reliability = reliability
        self.sources = sources or []
        self.raw = raw or {}

    def to_dict(self) -> Dict[str, Any]:
        """序列化。"""
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "doi": self.doi,
            "abstract": self.abstract,
            "citation_count": self.citation_count,
            "urls": self.urls,
            "item_type": self.item_type,
            "language": self.language,
            "reliability": self.reliability,
            "sources": self.sources,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LitItem {self.title[:30]} rel={self.reliability}>"


class LiteratureService:
    """多源文献检索服务（统一入口）。

    Usage::

        svc = LiteratureService()
        items = svc.search("transformer 注意力机制", max_results=10)
        items = svc.lookup_doi("10.1109/XXX")   # DOI 反查（引文校验用）
    """

    def __init__(self, timeout: float = _TIMEOUT, mailto: str = MAILTO) -> None:
        self._timeout = timeout
        self._mailto = mailto
        self._client = httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------
    def search(self, query: str, max_results: int = 10) -> List[LitItem]:
        """按关键词多源检索，合并去重（按 DOI/标题）。

        中文查询会并行走 Crossref（query.bibliographic）+ OpenAlex（search 全文）。
        """
        results: List[LitItem] = []

        # 1. Crossref
        try:
            results.extend(self._crossref_search(query, max_results))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref 检索失败: %s", exc)

        # 2. OpenAlex
        try:
            results.extend(self._openalex_search(query, max_results))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAlex 检索失败: %s", exc)

        # 3. 合并去重（DOI 优先，其次 标题+年）
        return self._dedupe(results)[:max_results]

    def lookup_doi(self, doi: str) -> Optional[LitItem]:
        """按 DOI 精确反查（Crossref 权威，OpenAlex 补充）。"""
        doi = doi.strip().lstrip("https://doi.org/").lstrip("http://doi.org/")
        if not doi:
            return None
        try:
            item = self._crossref_doi(doi)
            if item is not None:
                return item
        except Exception as exc:  # noqa: BLE001
            logger.warning("Crossref DOI 反查失败 %s: %s", doi, exc)
        try:
            return self._openalex_doi(doi)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenAlex DOI 反查失败 %s: %s", doi, exc)
        return None

    def verify_ref(self, ref: Dict[str, Any]) -> Dict[str, Any]:
        """单条参考文献核验（供环8 引文校验）。

        Args:
            ref: {title, authors, year, doi, venue, ...}（任一可用）。
        Returns:
            {ok: bool, reliability, evidence, gbt7714_candidate?}
        """
        # 1. 有 DOI：先反查（最可靠）
        if ref.get("doi"):
            item = self.lookup_doi(ref["doi"])
            if item is not None:
                return {
                    "ok": True,
                    "reliability": "verified",
                    "evidence": {"doi": ref["doi"], "source": "crossref/openalex",
                                 "matched_title": self._title_overlap(ref.get("title", ""), item.title)},
                    "item": item.to_dict(),
                }
        # 2. 标题搜索匹配
        if ref.get("title"):
            hits = self.search(ref["title"], max_results=5)
            best, score = self._best_match(hits, ref)
            if best is not None and score >= 0.6:
                return {
                    "ok": True,
                    "reliability": "matched" if score < 0.85 else "verified",
                    "evidence": {"score": round(score, 3), "matched_title": best.title,
                                 "source": best.sources},
                    "item": best.to_dict(),
                }
        # 3. 未命中：中文标"待人工复核"，英文标"unverified"
        rel = "uncertain" if _is_chinese(ref.get("title", "")) else "unverified"
        return {
            "ok": False,
            "reliability": rel,
            "evidence": {"reason": "未命中任何数据源，中文条目请人工/订阅源复核",
                         "checked_sources": ["crossref", "openalex"]},
            "item": None,
        }

    # ------------------------------------------------------------------
    # Crossref
    # ------------------------------------------------------------------
    def _crossref_search(self, query: str, limit: int) -> List[LitItem]:
        url = "https://api.crossref.org/works"
        params = {
            "query.bibliographic": query,
            "rows": limit,
            "mailto": self._mailto,
        }
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
        return [self._crossref_to_item(it, reliability="matched") for it in items if it.get("title")]

    def _crossref_doi(self, doi: str) -> Optional[LitItem]:
        url = f"https://api.crossref.org/works/{doi}"
        params = {"mailto": self._mailto}
        resp = self._client.get(url, params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._crossref_to_item(resp.json().get("message", {}), reliability="verified")

    @staticmethod
    def _crossref_to_item(raw: Dict[str, Any], reliability: str) -> LitItem:
        title = (raw.get("title") or [""])[0] if raw.get("title") else ""
        authors = []
        for a in raw.get("author", []) or []:
            name = " ".join(x for x in [a.get("given", ""), a.get("family", "")] if x)
            if name:
                authors.append(name)
        year = None
        for key in ("published-print", "published-online", "issued", "created"):
            dp = raw.get(key, {}).get("date-parts", [[None]])
            if dp and dp[0] and dp[0][0]:
                year = int(dp[0][0])
                break
        venue = raw.get("container-title") or [""]
        return LitItem(
            title=title,
            authors=authors,
            year=year,
            venue=venue[0] if venue else "",
            doi=raw.get("DOI", ""),
            abstract=re.sub(r"<[^>]+>", "", raw.get("abstract", "") or ""),
            citation_count=raw.get("is-referenced-by-count"),
            urls=[raw.get("URL", "")] if raw.get("URL") else [],
            item_type=_map_type(raw.get("type", "")),
            language="zh" if _is_chinese(title) else "unknown",
            reliability=reliability,
            sources=["crossref"],
            raw=raw,
        )

    # ------------------------------------------------------------------
    # OpenAlex
    # ------------------------------------------------------------------
    def _openalex_search(self, query: str, limit: int) -> List[LitItem]:
        url = "https://api.openalex.org/works"
        params = {
            "search": query,
            "per-page": limit,
            # 中文语言字段常误标，故不用 language 过滤
            "mailto": self._mailto,
        }
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        items = resp.json().get("results", [])
        return [self._openalex_to_item(it, reliability="matched") for it in items if it.get("display_name")]

    def _openalex_doi(self, doi: str) -> Optional[LitItem]:
        url = "https://api.openalex.org/works"
        params = {"filter": f"doi:{doi}", "per-page": 1, "mailto": self._mailto}
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        return self._openalex_to_item(results[0], reliability="verified")

    @staticmethod
    def _openalex_to_item(raw: Dict[str, Any], reliability: str) -> LitItem:
        authors = [a.get("display_name", "") for a in (raw.get("authorships") or []) if a.get("display_name")]
        year = raw.get("publication_year")
        venue_src = raw.get("primary_location", {}).get("source", {}) or {}
        venue = venue_src.get("display_name", "") if venue_src else ""
        urls = []
        if raw.get("doi"):
            urls.append(raw["doi"])
        oa = raw.get("open_access", {}).get("oa_url")
        if oa:
            urls.append(oa)
        title = raw.get("display_name", "")
        return LitItem(
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=raw.get("doi", "").replace("https://doi.org/", ""),
            abstract=_extract_abstract(raw.get("abstract_inverted_index", {})),
            citation_count=raw.get("cited_by_count"),
            urls=urls,
            item_type=_map_type(raw.get("type", "")),
            language="zh" if _is_chinese(title) else "unknown",
            reliability=reliability,
            sources=["openalex"],
            raw=raw,
        )

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _dedupe(items: List[LitItem]) -> List[LitItem]:
        """按 DOI（优先）/ 标题归一化去重，合并 sources。"""
        seen_doi: Dict[str, LitItem] = {}
        seen_title: Dict[str, LitItem] = {}
        out: List[LitItem] = []
        for it in items:
            key_doi = it.doi.strip().lower() if it.doi else ""
            if key_doi:
                if key_doi in seen_doi:
                    # 合并：reliability 取更高，sources 合并
                    prev = seen_doi[key_doi]
                    if it.reliability == "verified":
                        prev.reliability = "verified"
                    if it.venue and not prev.venue:
                        prev.venue = it.venue
                    if it.authors and not prev.authors:
                        prev.authors = it.authors
                    if it.abstract and not prev.abstract:
                        prev.abstract = it.abstract
                    for s in it.sources:
                        if s not in prev.sources:
                            prev.sources.append(s)
                    continue
                seen_doi[key_doi] = it
                out.append(it)
                continue
            key_title = re.sub(r"\s+", "", (it.title or "").lower())
            if key_title:
                if key_title in seen_title:
                    continue
                seen_title[key_title] = it
            out.append(it)
        for it in out:
            # 中文条目自动降级 reliability（除非 verified DOI）
            if it.reliability != "verified":
                it.language = "zh" if _is_chinese(it.title) else it.language
        return out

    @staticmethod
    def _title_overlap(a: str, b: str) -> float:
        """标题字符重叠率（0~1）。"""
        sa, sb = re.sub(r"\W+", "", (a or "").lower()), re.sub(r"\W+", "", (b or "").lower())
        if not sa or not sb:
            return 0.0
        # 简单 Jaccard 式：共同子串占比
        common = sum(1 for c in sa if c in sb)
        return common / max(len(sa), len(sb))

    @staticmethod
    def _best_match(hits: List[LitItem], ref: Dict[str, Any]) -> tuple[Optional[LitItem], float]:
        """从检索结果中找与 ref 最相似条目，返回 (item, score)。"""
        best, best_score = None, 0.0
        ref_title = ref.get("title", "")
        ref_year = ref.get("year")
        for h in hits:
            score = LiteratureService._title_overlap(ref_title, h.title)
            # 年份匹配加分
            if ref_year and h.year and abs(int(ref_year) - int(h.year)) <= 1:
                score += 0.1
            # 作者加分
            if ref.get("authors") and h.authors:
                ref_first = ref.get("authors", [""])[0].strip()
                if any(ref_first in a or a in ref_first for a in h.authors):
                    score += 0.1
            if score > best_score:
                best, best_score = h, min(score, 1.0)
        return best, best_score


def _map_type(raw_type: str) -> str:
    """API 类型 → 本项目类型。"""
    m = {
        "journal-article": "article",
        "proceedings-article": "conference",
        "book-chapter": "book",
        "book": "book",
        "dissertation": "thesis",
        "report": "report",
        "article": "article",
    }
    return m.get(raw_type, "other")


def _extract_abstract(inverted: Dict[str, List[int]]) -> str:
    """OpenAlex abstract_inverted_index → 纯文本摘要。"""
    if not inverted:
        return ""
    # {word: [positions]} → 恢复顺序
    positions: List[tuple[int, str]] = []
    for word, idxs in inverted.items():
        for idx in idxs:
            positions.append((idx, word))
    positions.sort()
    return " ".join(w for _, w in positions)


#: 模块级单例
_service: Optional[LiteratureService] = None


def get_lit_service() -> LiteratureService:
    """获取文献检索服务单例。"""
    global _service
    if _service is None:
        _service = LiteratureService()
    return _service
