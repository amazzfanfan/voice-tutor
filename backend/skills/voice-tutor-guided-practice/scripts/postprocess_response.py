#!/usr/bin/env python3
"""Deterministic response cleanup and validation for the guided voice tutor."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List


DEFAULT_MAX_CHARS = 500
TRUNCATE_SUFFIX = "如果你想了解更多，可以继续问我。"


def extract_choice_question_blocks(text: str) -> List[str]:
    """Extract learner-facing multiple-choice question blocks."""
    if not text:
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[str] = []
    option_pattern = re.compile(r"^\s*[A-DＡ-Ｄ][\.．、]\s*.+")

    for end_idx, line in enumerate(lines):
        if "你觉得是哪个" not in line:
            continue

        option_start = None
        appended = False
        for idx in range(end_idx - 1, -1, -1):
            if option_pattern.match(lines[idx]):
                option_start = idx
            elif option_start is not None and lines[idx].strip():
                start_idx = max(0, idx - 1)
                block_lines = [
                    item.strip()
                    for item in lines[start_idx : end_idx + 1]
                    if item.strip()
                ]
                blocks.append("\n".join(block_lines))
                appended = True
                break
            elif option_start is not None:
                block_lines = [
                    item.strip()
                    for item in lines[option_start : end_idx + 1]
                    if item.strip()
                ]
                blocks.append("\n".join(block_lines))
                appended = True
                break

        if option_start is not None and not appended:
            start_idx = max(0, option_start - 2)
            block_lines = [
                item.strip()
                for item in lines[start_idx : end_idx + 1]
                if item.strip()
            ]
            blocks.append("\n".join(block_lines))

    return blocks


def extract_choice_question_spans(text: str) -> List[Dict[str, Any]]:
    """Extract multiple-choice blocks with line spans for replacement."""
    if not text:
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    spans: List[Dict[str, Any]] = []
    option_pattern = re.compile(r"^\s*[A-DＡ-Ｄ][\.．、]\s*.+")

    for end_idx, line in enumerate(lines):
        if "你觉得是哪个" not in line:
            continue

        option_start = None
        appended = False
        for idx in range(end_idx - 1, -1, -1):
            if option_pattern.match(lines[idx]):
                option_start = idx
            elif option_start is not None and lines[idx].strip():
                start_idx = max(0, idx - 1)
                block_lines = [
                    item.strip()
                    for item in lines[start_idx : end_idx + 1]
                    if item.strip()
                ]
                spans.append(
                    {"start": start_idx, "end": end_idx, "block": "\n".join(block_lines)}
                )
                appended = True
                break
            elif option_start is not None:
                block_lines = [
                    item.strip()
                    for item in lines[option_start : end_idx + 1]
                    if item.strip()
                ]
                spans.append(
                    {"start": option_start, "end": end_idx, "block": "\n".join(block_lines)}
                )
                appended = True
                break

        if option_start is not None and not appended:
            start_idx = max(0, option_start - 2)
            block_lines = [
                item.strip()
                for item in lines[start_idx : end_idx + 1]
                if item.strip()
            ]
            spans.append(
                {"start": start_idx, "end": end_idx, "block": "\n".join(block_lines)}
            )

    return spans


def question_signature(block: str) -> str:
    """Build a compact signature for exact duplicate-question detection."""
    if not block:
        return ""

    option_pattern = re.compile(r"^\s*[A-DＡ-Ｄ][\.．、]\s*(.+)")
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    first_option_idx = None
    option_texts: List[str] = []
    for idx, line in enumerate(lines):
        match = option_pattern.match(line)
        if match:
            if first_option_idx is None:
                first_option_idx = idx
            option_texts.append(match.group(1))

    if first_option_idx is None:
        return ""

    question_line = ""
    lead_ins = {"下一题", "我们再练一道巩固下", "我们再练一道"}
    for idx in range(first_option_idx - 1, -1, -1):
        candidate = lines[idx].strip("：: ")
        if candidate and candidate not in lead_ins:
            question_line = candidate
            break

    raw = question_line + " " + " ".join(option_texts)
    return re.sub(r"[\s，。！？、；：:,.!?;“”\"'《》（）()【】\[\]—-]+", "", raw)


def extract_choice_options(block: str) -> Dict[str, str]:
    """Extract normalized option labels and option text."""
    options: Dict[str, str] = {}
    if not block:
        return options

    option_pattern = re.compile(r"^\s*([A-DＡ-Ｄ])[\.．、]\s*(.+)")
    for line in block.splitlines():
        match = option_pattern.match(line.strip())
        if match:
            label = match.group(1).translate(str.maketrans("ＡＢＣＤ", "ABCD")).upper()
            options[label] = match.group(2).strip()
    return options


def normalize_answer_text(text: str) -> str:
    """Normalize learner speech for loose option-content matching."""
    if not text:
        return ""
    normalized = text.translate(str.maketrans("ＡＢＣＤａｂｃｄ", "ABCDabcd"))
    return re.sub(
        r"[\s，。！？、；：:,.!?;“”\"'《》（）()【】\[\]—-]+",
        "",
        normalized,
    ).lower()


def looks_like_choice_answer(query: str, options: Dict[str, str]) -> bool:
    """Return whether ASR text plausibly answers the pending question."""
    normalized = normalize_answer_text(query)
    if not normalized:
        return False
    if re.search(r"(?<![A-Za-z])([A-Za-zＡ-Ｚａ-ｚ])(?![A-Za-z])", query):
        return True

    answer_markers = (
        "不知道", "不清楚", "不会", "没听清", "听不清", "第一个", "第一项",
        "第二个", "第二项", "第三个", "第三项", "第四个", "第四项",
        "选一", "选二", "选三", "选四",
    )
    if any(marker in query for marker in answer_markers):
        return True
    return any(
        len(option_norm) >= 2 and option_norm in normalized
        for option_norm in (normalize_answer_text(value) for value in options.values())
    )


def looks_like_teaching_topic(query: str) -> bool:
    """Detect a deliberate new teaching question while a quiz is pending."""
    topic_markers = (
        "什么", "为什么", "怎么", "如何", "讲", "解释", "说明", "意思",
        "规定", "要求", "标准", "规程", "安全", "检查", "运输", "线路",
        "轨道", "坡度", "曲线", "道床", "路肩", "车辆", "轴距",
    )
    return any(marker in query for marker in topic_markers)


def replace_question_span(text: str, span: Dict[str, Any], replacement: str) -> str:
    """Replace one extracted question span in the original text."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    prefix = "\n".join(lines[: span["start"]]).rstrip()
    suffix = "\n".join(lines[span["end"] + 1 :]).lstrip()
    parts = [part for part in (prefix, replacement.strip(), suffix) if part]
    return "\n".join(parts).strip()


def remove_forbidden_question_tail(text: str, asked_questions: List[str]) -> str:
    """Remove an exact duplicate or a question beyond the three-question limit."""
    spans = extract_choice_question_spans(text)
    if not spans:
        return text

    asked_signatures = {
        signature
        for signature in (question_signature(block) for block in asked_questions)
        if signature
    }
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for span in spans:
        signature = question_signature(span["block"])
        is_duplicate = bool(signature and signature in asked_signatures)
        is_over_limit = len(asked_questions) >= 3
        if not is_duplicate and not is_over_limit:
            continue
        prefix = "\n".join(lines[: span["start"]]).rstrip()
        closing = (
            "这轮我们先收住。"
            if is_over_limit
            else "这道题刚才已经练过了，我们不重复。你把刚才讲的正确答案和关键数值先记住，有其他想问的可以继续问我。"
        )
        return f"{prefix}\n{closing}".strip() if prefix else closing
    return text


def extract_material_bullets(material_context: str) -> str:
    """Extract concise original bullet-like points for repair prompts."""
    if not material_context:
        return ""
    bullets: List[str] = []
    for line in material_context.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        item = line.strip()
        if not item or not item.startswith(("——", "-", "－", "•")):
            continue
        item = re.sub(r"^[——\-－•\s]+", "", item).strip()
        if item and item not in bullets:
            bullets.append(item)
    return "\n".join(f"- {item}" for item in bullets[:20])


def question_title(block: str) -> str:
    """Extract the natural question line from a choice-question block."""
    if not block:
        return ""
    option_pattern = re.compile(r"^\s*[A-DＡ-Ｄ][\.．、]\s*.+")
    lead_ins = {"下一题", "我们再练一道巩固下", "我们再练一道"}
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if not option_pattern.match(line):
            continue
        for candidate in reversed(lines[:idx]):
            title = candidate.strip("：: ")
            if title and title not in lead_ins:
                title = re.sub(r"[，,]?\s*(下列|以下)哪项.*$", "", title)
                title = re.sub(r"[，,]?\s*最低不得小于多少.*$", "", title)
                title = re.sub(r"[，,]?\s*应不小于多少.*$", "", title)
                title = re.sub(r"[，,]?\s*应不大于多少.*$", "", title)
                return re.sub(r"[？?。；;：:]+$", "", title)
        return ""
    return ""


def extract_answer_labels(text: str) -> List[str]:
    """Extract correct-answer labels from tutor judgement text in order."""
    if not text:
        return []
    return [
        match.group(1).translate(str.maketrans("ＡＢＣＤ", "ABCD")).upper()
        for match in re.finditer(r"正确答案(?:也是|是)\s*([A-DＡ-Ｄ])", text)
    ]


def compact_review_point(title: str, option_text: str) -> str:
    """Turn a question title and correct option into one concise review point."""
    title = re.sub(r"^铁路运输线路的?", "", title or "").strip() or "这个要点"
    option_text = (option_text or "").strip()
    if not option_text:
        return title

    value_only = re.fullmatch(
        r"不?[小大]于\s*.+|[0-9０-９]+(?:\.\d+)?\s*[a-zA-Z%‰°°毫米米倍:：.]+.*",
        option_text,
    )
    if value_only:
        if "半径" in title:
            return f"{title}不小于{option_text.lstrip('不小于')}"
        if "坡度" in title:
            return f"{title}{option_text if option_text.startswith('不') else '为' + option_text}"
        return f"{title}{option_text if option_text.startswith('不') else '不小于' + option_text}"
    if option_text.startswith(title):
        return option_text
    return f"{title}：{option_text}"


def clean_response(text: str) -> str:
    """Remove output wrappers while preserving choice-option line breaks."""
    if not text:
        return ""

    cleaned = re.sub(r"<answer>\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*</answer>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"<references>.*?</references>",
        "",
        cleaned,
        flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = re.sub(r"\s*\[(?:W|R)\d+(?:\.\d+)?\]", "", cleaned)
    cleaned = re.sub(r"^\s*```[^\n]*\n?", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "\n".join(line.rstrip() for line in cleaned.split("\n"))
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned.strip())
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def strip_internal_progress_text(text: str) -> str:
    """Remove internal quiz counters and mechanical control wording."""
    if not text:
        return ""

    cleanup_patterns = (
        r"已问问题数量[^。！？\n]*[。！？]?",
        r"已达\s*\d+\s*题[^。！？\n]*[。！？]?",
        r"本次练习结束[。！？]?",
        r"这次练习结束[。！？]?",
        r"练习结束[。！？]?",
        r"辛苦了[。！？]?",
        r"这轮我们已经练了\s*\d+\s*道题[^。！？\n]*[。！？]?",
    )
    cleaned = text
    for pattern in cleanup_patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip(" \n，。；;")


def compact_output_lines(text: str) -> str:
    """Collapse repeated blank lines without joining A/B/C/D option lines."""
    if not text:
        return ""

    lines = [
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    compacted: List[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if compacted and not previous_blank:
                compacted.append("")
            previous_blank = True
            continue
        compacted.append(line)
        previous_blank = False
    return "\n".join(compacted).strip()


def normalize_choice_layout(text: str) -> str:
    """Split inline option labels and keep at most one learner-facing question."""
    if not text:
        return ""

    normalized = re.sub(
        r"[ \t]+(?=[A-DＡ-Ｄ][\.．、][ \t]*)",
        "\n",
        text,
    )
    endings = list(re.finditer(r"你觉得是哪个[？?]?", normalized))
    if len(endings) > 1:
        normalized = normalized[: endings[0].end()]
    return normalized.strip()


def truncate_response(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Trim a long response at a sentence boundary for voice playback."""
    if not text or len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    last_period = max(
        truncated.rfind("。"),
        truncated.rfind("！"),
        truncated.rfind("？"),
        truncated.rfind("."),
        truncated.rfind("!"),
        truncated.rfind("?"),
    )
    if last_period > 0:
        result = truncated[: last_period + 1]
    else:
        result = truncated.rstrip() + "..."

    if len(result) + len(TRUNCATE_SUFFIX) <= max_chars + 30:
        result += TRUNCATE_SUFFIX
    return result


def validate_response(text: str, supports_quiz: bool = True) -> List[str]:
    """Return deterministic contract violations still present in text."""
    violations: List[str] = []
    if not text.strip():
        return ["empty_response"]

    if re.search(r"</?(?:answer|references)>|\[(?:W|R)\d+(?:\.\d+)?\]", text):
        violations.append("forbidden_structured_markup")
    if "```" in text:
        violations.append("markdown_code_fence")
    if re.search(
        r"已问问题数量|已达\s*\d+\s*题|本次练习结束|这次练习结束|辛苦了",
        text,
    ):
        violations.append("internal_progress_text")

    question_count = text.count("你觉得是哪个")
    if supports_quiz and question_count > 1:
        violations.append("multiple_questions")
    if not supports_quiz and question_count:
        violations.append("quiz_not_allowed")

    inline_options = re.search(
        r"[A-DＡ-Ｄ][\.．、][ \t]*[^\n]+[ \t]+[A-DＡ-Ｄ][\.．、]",
        text,
    )
    if inline_options:
        violations.append("options_not_line_separated")

    return violations


def postprocess_response(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    supports_quiz: bool = True,
) -> Dict[str, object]:
    """Clean a draft and return its processed text plus validation metadata."""
    original_violations = validate_response(text, supports_quiz=supports_quiz)
    processed = clean_response(text)
    processed = strip_internal_progress_text(processed)
    if supports_quiz:
        processed = normalize_choice_layout(processed)
    processed = compact_output_lines(processed)
    processed = truncate_response(processed, max_chars=max_chars)
    remaining_violations = validate_response(processed, supports_quiz=supports_quiz)
    return {
        "text": processed,
        "valid": not remaining_violations,
        "violations": remaining_violations,
        "fixed_violations": [
            item for item in original_violations if item not in remaining_violations
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="Draft response text; JSON stdin is used when omitted")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument(
        "--no-quiz",
        action="store_true",
        help="Validate that the response contains no guided-practice question",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.text is not None:
        payload = {
            "text": args.text,
            "max_chars": args.max_chars,
            "supports_quiz": not args.no_quiz,
        }
    else:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}

    result = postprocess_response(
        str(payload.get("text", "")),
        max_chars=int(payload.get("max_chars", args.max_chars)),
        supports_quiz=bool(payload.get("supports_quiz", not args.no_quiz)),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
