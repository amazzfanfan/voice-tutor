"""Lightweight, deterministic fusion for Voice Wiki and RAG retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from typing import Any, Iterable, Optional, Sequence


class SourceStatus(str, Enum):
    """Observable outcome of one local knowledge source."""

    SUCCESS = "success"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class WikiMaterial:
    status: SourceStatus
    context: str = ""
    matched_concepts: list[str] = field(default_factory=list)
    local_concepts: list[str] = field(default_factory=list)
    fuzzy_keywords: list[str] = field(default_factory=list)
    needs_web_search: bool = False
    search_query: str = ""
    elapsed_ms: int = 0
    error: str = ""


@dataclass
class EvidenceChunk:
    content: str
    rank: int
    title: str = ""


@dataclass
class RagMaterial:
    status: SourceStatus
    chunks: list[EvidenceChunk] = field(default_factory=list)
    raw_count: int = 0
    duplicate_count: int = 0
    elapsed_ms: int = 0
    error: str = ""


@dataclass
class RetrievalBundle:
    mode: str
    wiki: Optional[WikiMaterial] = None
    rag: Optional[RagMaterial] = None
    elapsed_ms: int = 0


@dataclass
class FusedContext:
    """Internal context passed to the answer model plus observable fusion stats."""

    text: str
    source_label: str
    mode: str
    wiki_status: Optional[SourceStatus] = None
    rag_status: Optional[SourceStatus] = None
    wiki_chars: int = 0
    rag_raw_count: int = 0
    rag_kept_count: int = 0
    duplicate_count: int = 0
    elapsed_ms: int = 0
    needs_web_search: bool = False
    search_query: str = ""

    @property
    def has_material(self) -> bool:
        return bool(self.text.strip())

    @property
    def has_source_failure(self) -> bool:
        return any(
            status in {SourceStatus.TIMEOUT, SourceStatus.ERROR}
            for status in (self.wiki_status, self.rag_status)
            if status is not None
        )

    @property
    def both_local_sources_timed_out(self) -> bool:
        """Return true only when the configured Wiki+RAG pair both timed out."""
        return (
            self.mode == "rag_wiki"
            and self.wiki_status is SourceStatus.TIMEOUT
            and self.rag_status is SourceStatus.TIMEOUT
        )


def wiki_material_from_response(
    payload: Any,
    *,
    elapsed_ms: int,
    max_chars: int,
) -> WikiMaterial:
    """Normalize the existing Wiki API response without changing its contract."""

    if not isinstance(payload, dict):
        return WikiMaterial(status=SourceStatus.EMPTY, elapsed_ms=elapsed_ms)

    context = _clean_text(payload.get("local_context"))[:max_chars]
    return WikiMaterial(
        status=SourceStatus.SUCCESS if context else SourceStatus.EMPTY,
        context=context,
        matched_concepts=_string_list(payload.get("matched_concepts")),
        local_concepts=_string_list(payload.get("local_concepts")),
        fuzzy_keywords=_string_list(payload.get("fuzzy_keywords")),
        needs_web_search=bool(payload.get("needs_web_search")),
        search_query=_clean_text(payload.get("search_query")),
        elapsed_ms=elapsed_ms,
    )


def rag_material_from_results(
    results: Any,
    *,
    elapsed_ms: int,
    max_chunks: int,
    chunk_max_chars: int,
    total_max_chars: int,
    similarity_threshold: float = 0.88,
) -> RagMaterial:
    """Normalize ranked RAG results and remove exact/near duplicates in rank order."""

    if isinstance(results, str):
        raw_items: Sequence[Any] = [results]
    elif isinstance(results, Sequence):
        raw_items = results
    else:
        raw_items = []

    kept: list[EvidenceChunk] = []
    seen_normalized: set[str] = set()
    kept_chars = 0
    duplicates = 0

    for rank, item in enumerate(raw_items, start=1):
        if len(kept) >= max_chunks or kept_chars >= total_max_chars:
            break
        content, title = _rag_item_text(item)
        content = content[:chunk_max_chars]
        normalized = _normalize_for_similarity(content)
        if not normalized:
            continue
        if normalized in seen_normalized or any(
            _similar(normalized, _normalize_for_similarity(chunk.content), similarity_threshold)
            for chunk in kept
        ):
            duplicates += 1
            continue

        remaining = total_max_chars - kept_chars
        content = content[:remaining].strip()
        if not content:
            break
        kept.append(EvidenceChunk(content=content, title=title, rank=rank))
        seen_normalized.add(normalized)
        kept_chars += len(content)

    material = RagMaterial(
        status=SourceStatus.SUCCESS if kept else SourceStatus.EMPTY,
        chunks=kept,
        raw_count=len(raw_items),
        duplicate_count=duplicates,
        elapsed_ms=elapsed_ms,
    )
    return material


def fuse_retrieval_bundle(
    bundle: RetrievalBundle,
    *,
    max_chars: int,
    similarity_threshold: float = 0.88,
) -> FusedContext:
    """Build a compact source-aware prompt; no model call is required."""

    wiki = bundle.wiki
    rag = bundle.rag
    rag_chunks = list(rag.chunks if rag else [])
    duplicate_count = 0

    wiki_blocks = _split_wiki_blocks(wiki.context if wiki else "")
    if wiki_blocks and rag_chunks:
        rag_normalized = [_normalize_for_similarity(chunk.content) for chunk in rag_chunks]
        filtered_blocks = []
        for block in wiki_blocks:
            normalized = _normalize_for_similarity(block)
            if _looks_like_heading(block):
                filtered_blocks.append(block)
            elif normalized and any(
                _similar(normalized, rag_text, similarity_threshold)
                for rag_text in rag_normalized
            ):
                duplicate_count += 1
            else:
                filtered_blocks.append(block)
        wiki_blocks = filtered_blocks

    sections: list[str] = []
    source_labels: list[str] = []
    if wiki_blocks:
        sections.append("## Wiki概念上下文\n" + "\n\n".join(wiki_blocks))
        source_labels.append("Wiki")
    if rag_chunks:
        evidence_lines = []
        for index, chunk in enumerate(rag_chunks, start=1):
            title = f"（{chunk.title}）" if chunk.title else ""
            evidence_lines.append(f"- E{index}{title}：{chunk.content}")
        sections.append("## RAG原文依据\n" + "\n".join(evidence_lines))
        source_labels.append("RAG")

    if sections:
        sections.extend(
            [
                "## 本轮资料状态\n"
                + _status_summary(bundle),
                "## 生成约束\n"
                "优先按 Wiki 的概念关系和讲解顺序组织内容；数值、条款、参数、案例和具体要求以 RAG 原文依据为锚点。\n"
                "两个来源若存在口径冲突，不要自行拼成一个结论；版本或权威性不明时，明确提醒用户需要核实。\n"
                "E 编号和来源分区仅供内部组织，最终回答不得向用户展示。",
            ]
        )

    fused_text = _truncate_sections(sections, max_chars)
    return FusedContext(
        text=fused_text,
        source_label="+".join(source_labels) if source_labels else "LLM",
        mode=bundle.mode,
        wiki_status=wiki.status if wiki else None,
        rag_status=rag.status if rag else None,
        wiki_chars=len(wiki.context) if wiki else 0,
        rag_raw_count=rag.raw_count if rag else 0,
        rag_kept_count=len(rag_chunks),
        duplicate_count=duplicate_count + (rag.duplicate_count if rag else 0),
        elapsed_ms=bundle.elapsed_ms,
        needs_web_search=bool(wiki and wiki.needs_web_search),
        search_query=wiki.search_query if wiki else "",
    )


def _rag_item_text(item: Any) -> tuple[str, str]:
    if isinstance(item, dict):
        content = (
            item.get("content")
            or item.get("content_text")
            or item.get("text")
            or ""
        )
        title = item.get("filename") or item.get("file_name") or item.get("title") or ""
        return _clean_text(content), _clean_text(title)
    return _clean_text(item), ""


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[ \t]+", " ", str(value)).strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [text for item in value if (text := _clean_text(item))]


def _normalize_for_similarity(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())


def _similar(left: str, right: str, threshold: float) -> bool:
    if not left or not right:
        return False
    shorter, longer = sorted((left, right), key=len)
    if len(shorter) >= 24 and shorter in longer:
        return True
    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= threshold


def _split_wiki_blocks(text: str) -> list[str]:
    if not text.strip():
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    return [block.strip() for block in blocks if block.strip()]


def _looks_like_heading(block: str) -> bool:
    first_line = block.splitlines()[0].strip()
    return first_line.startswith("#") or (
        len(block.splitlines()) == 1 and len(first_line) <= 24
    )


def _status_summary(bundle: RetrievalBundle) -> str:
    labels = {
        SourceStatus.SUCCESS: "成功",
        SourceStatus.EMPTY: "无结果",
        SourceStatus.TIMEOUT: "超时",
        SourceStatus.ERROR: "异常",
    }
    parts = []
    if bundle.wiki:
        parts.append(f"Wiki：{labels[bundle.wiki.status]}")
    if bundle.rag:
        parts.append(f"RAG：{labels[bundle.rag.status]}")
    return "；".join(parts)


def _truncate_sections(sections: Sequence[str], max_chars: int) -> str:
    if not sections:
        return ""

    # Always preserve source status and factual constraints at the tail. The
    # material sections absorb any truncation needed to stay inside the budget.
    tail_sections = list(sections[-2:]) if len(sections) >= 3 else []
    head_sections = list(sections[:-2]) if tail_sections else list(sections)
    tail = "\n\n".join(tail_sections)
    head_budget = max_chars - len(tail) - (2 if tail else 0)
    output = ""
    if len(head_sections) == 2 and head_budget > 2:
        # When both sources are present, reserve room for each instead of
        # allowing the first (Wiki) section to crowd out ranked RAG evidence.
        material_budget = head_budget - 2
        wiki_target = min(len(head_sections[0]), round(material_budget * 0.45))
        rag_target = min(len(head_sections[1]), material_budget - wiki_target)
        unused = material_budget - wiki_target - rag_target
        if unused:
            wiki_target += min(unused, len(head_sections[0]) - wiki_target)
            unused = material_budget - wiki_target - rag_target
        if unused:
            rag_target += min(unused, len(head_sections[1]) - rag_target)
        output = (
            head_sections[0][:wiki_target].rstrip()
            + "\n\n"
            + head_sections[1][:rag_target].rstrip()
        ).strip()
    else:
        for section in head_sections:
            separator = "\n\n" if output else ""
            remaining = head_budget - len(output) - len(separator)
            if remaining <= 0:
                break
            output += separator + section[:remaining].rstrip()
    if tail:
        if output:
            output += "\n\n"
        output += tail[: max_chars - len(output)].rstrip()
    return output.strip()
