#!/usr/bin/env python3
"""Deterministic output cleanup for the explain-only voice tutor."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Dict, List


DEFAULT_MAX_CHARS = 500
TRUNCATE_SUFFIX = "需要的话，我可以继续结合你的实际场景往下讲。"

ROLE_MARKERS = (
    "操作员", "操作工", "司机", "维修", "检修", "点检", "安全员", "安全管理",
    "班组长", "教师", "讲师", "管理人员", "负责人", "工程师", "技术员",
    "设计", "学生", "学员", "考生", "新员工", "新人", "岗位",
)
DIRECT_EXPLANATION_MARKERS = (
    "直接讲", "不用问", "别问", "不方便说", "不想说", "按通用", "通用讲解",
)
PROFILE_QUESTION_MARKERS = (
    "什么岗位", "哪个岗位", "岗位是什么", "用在什么场景", "使用场景",
    "培训、考试", "培训还是", "现场还是",
)


def _information_units(text: str) -> int:
    """Approximate whether an utterance carries enough content to act on."""
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text or ""))


def _looks_substantive_learning_request(text: str) -> bool:
    """Avoid a brittle technical keyword gate; use information content instead."""
    text = (text or "").strip()
    if _information_units(text) < 4:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", text))


def build_pre_retrieval_reply(query: str, history_context: str = "") -> str:
    """Return a short repair prompt when retrieval should clearly be skipped."""
    query = (query or "").strip()
    history_context = history_context or ""
    if not query:
        return "我刚才可能没听清，你可以重新说一遍问题。"

    if _looks_substantive_learning_request(query):
        return ""

    if history_context:
        return "好，我先慢下来。你可以继续说，或者重新说一下你想问的点。"
    return "我刚才可能没听清，你可以重新说一遍问题。"


def _has_role_profile(text: str) -> bool:
    role_terms = "|".join(re.escape(marker) for marker in ROLE_MARKERS)
    return bool(
        re.search(
            rf"(?:我是|我现在是|我目前是|目前是|现在是|我做|我在做|我的岗位是|我负责|本人是|作为)"
            rf"[^，。！？\n]{{0,12}}(?:{role_terms})",
            text,
        )
    )


def _has_usage_scenario(text: str) -> bool:
    return bool(
        re.search(
            r"用于|用来|准备用|拿来|主要用|使用场景是|"
            r"现场(?:用|工作|作业|检查|讲解)|培训(?:用|讲解)|"
            r"考试(?:用|准备)|备考|取证|班前会|上岗前|入职学习",
            text,
        )
    )


def build_profile_prompt(query: str, history_context: str = "") -> str:
    """Return the mandatory first technical-turn profile question, if needed."""
    query = (query or "").strip()
    history_context = history_context or ""
    if not query or any(marker in query for marker in DIRECT_EXPLANATION_MARKERS):
        return ""
    if any(marker in history_context for marker in PROFILE_QUESTION_MARKERS):
        return ""
    if not _looks_substantive_learning_request(query):
        return ""

    profile_context = f"{history_context}\n{query}"
    has_role = _has_role_profile(profile_context)
    has_scenario = _has_usage_scenario(profile_context)
    if has_role and has_scenario:
        return ""
    if has_role:
        return "为了给你讲得更贴合，我再确认一下：这个问题主要会用在什么场景，比如现场工作、培训讲解或者考试学习？"
    if has_scenario:
        return "为了给你讲得更贴合，我再确认一下：你现在是什么岗位，或者有什么专业背景？"
    return "为了给你讲得更贴合，我先问一句：你现在是什么岗位，这个问题主要会用在什么场景？"


def clean_response(text: str) -> str:
    """Remove forbidden wrappers while preserving display-safe Markdown."""
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
    cleaned = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", cleaned.strip())
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return cleaned.strip()


def strip_profile_display_labels(text: str) -> str:
    """Apply learner profiles implicitly instead of exposing UI edition labels."""
    if not text:
        return ""

    role_pattern = "|".join(re.escape(term) for term in ROLE_MARKERS)
    scenario_pattern = "现场|培训|讲解|考试|学习|检查|巡查|班前会"
    # A role plus a scenario inside parentheses is a visible edition badge,
    # regardless of whether the model calls it “版”“专用” or “要点”.
    cleaned = re.sub(
        rf"[\uFF08(【\[][^\uFF09)】\]\n]{{0,30}}(?:{role_pattern})"
        rf"[^\uFF09)】\]\n]{{0,30}}(?:{scenario_pattern}|版|专用)"
        rf"[^\uFF09)】\]\n]{{0,20}}[\uFF09)】\]]",
        "",
        text,
    )
    cleaned = re.sub(
        rf"[\uFF08(【\[][^\uFF09)】\]\n]{{0,30}}(?:{scenario_pattern})"
        rf"[^\uFF09)】\]\n]{{0,20}}(?:版|专用)[\uFF09)】\]]",
        "",
        cleaned,
    )
    # A standalone bold line is a fake heading. Convert it to actual Markdown so
    # the display and TTS cleanup layers both interpret it deterministically.
    cleaned = re.sub(
        r"(?m)^\s*\*\*([^*\n]{2,60})\*\*\s*$",
        lambda match: f"### {match.group(1).strip()}",
        cleaned,
    )
    return cleaned.strip()


def _safe_bold_content(content: str) -> bool:
    """Return whether one bold span is a short, self-contained Markdown atom."""
    content = content.strip()
    if not content or len(content) > 30:
        return False
    if re.match(r"^[：:；;，,。！？!?、—-]", content):
        return False
    if content.endswith(("-", "—", "+", "*")):
        return False
    if re.search(r"(?:^|\s)[-*+]\s", content):
        return False
    return True


def normalize_markdown_emphasis(text: str) -> str:
    """Keep valid short bold spans and strip malformed markers safely."""
    if not text:
        return ""

    repaired_lines: List[str] = []
    for raw_line in text.split("\n"):
        line = raw_line
        if line.count("**") % 2:
            repaired_lines.append(line.replace("**", ""))
            continue

        def repair_span(match: re.Match) -> str:
            content = match.group(1).strip()
            return f"**{content}**" if _safe_bold_content(content) else content

        line = re.sub(r"\*\*([^*\n]+)\*\*", repair_span, line)
        repaired_lines.append(line)

    repaired = "\n".join(repaired_lines)
    repaired = re.sub(
        r"(?<=[\u4e00-\u9fff：:。；;])[—-]\s*(?=[\u4e00-\u9fffA-Za-z0-9])",
        "\n- ",
        repaired,
    )
    repaired = re.sub(
        r"(超过|不大于|不少于|不小于|等于|为|是)\s*[：:]\s*",
        r"\1",
        repaired,
    )
    return repaired.strip()


def normalize_spoken_units(text: str) -> str:
    """Repair reversed spoken permille wording without changing source units."""
    if not text:
        return ""
    return re.sub(
        r"([零〇一二三四五六七八九十百两点\d]+)千分之一",
        r"千分之\1",
        text,
    )


def strip_redundant_permille_explanations(text: str) -> str:
    """Keep source permille notation on screen; pronunciation belongs to TTS."""
    if not text:
        return ""

    pattern = re.compile(
        r"([零〇一二三四五六七八九十百千万两点\d.]+‰)\s*"
        r"[（(]([^（）()\n]{1,60})[）)]"
    )

    def remove_spoken_duplicate(match: re.Match) -> str:
        explanation = match.group(2)
        is_spoken_duplicate = "千分之" in explanation
        is_equivalent_percent = bool(
            re.search(
                r"(?:也就是|即|相当于|等于)[^，。；;]{0,20}[%％]",
                explanation,
            )
        )
        if is_spoken_duplicate or is_equivalent_percent:
            return match.group(1)
        return match.group(0)

    return pattern.sub(remove_spoken_duplicate, text)


def strip_internal_reference_labels(text: str) -> str:
    """Hide retrieval chunk labels while preserving learner-facing content."""
    if not text:
        return ""

    cleaned = text
    cleaned = re.sub(r"\s*\[(?:W|R)\d+(?:\.\d+)?\]", "", cleaned)
    cleaned = re.sub(
        r"[（(][^（）()\n]{0,80}(?:W|R)\d+(?:\.\d+)?[^（）()\n]{0,120}[）)]",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:W|R)\d+(?:\.\d+)?(?:材料|资料|片段|原文)?"
        r"(?:指出|提到|显示|要求|明确|强调|说明|规定)[：:]?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:如|见|参考)?(?:W|R)\d+(?:\.\d+)?(?:图\d+)?(?:所示|中|材料|资料|片段|原文)?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?:W|R)\d+(?:\.\d+)?(?=(?:明确|强调|要求|指出|规定|提到|显示|说明))",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?:W|R)\d+(?:\.\d+)?", "", cleaned)
    cleaned = re.sub(r"（\s*）|\(\s*\)", "", cleaned)
    cleaned = re.sub(r"如\s*所示", "", cleaned)
    cleaned = re.sub(r"[，,]\s*[，,]", "，", cleaned)
    cleaned = re.sub(r"：\s*，", "：", cleaned)
    cleaned = "\n".join(
        re.sub(r"[ \t]+", " ", line).strip()
        for line in cleaned.split("\n")
    )
    return cleaned.strip()


def strip_quiz_judgement(text: str) -> str:
    """Remove answer-judging phrases that do not belong in explanation mode."""
    if not text:
        return ""

    cleaned = re.sub(
        r"你选的是\s*[A-DＡ-Ｄ][^。！？\n]*"
        r"正确答案(?:也是|是)\s*[A-DＡ-Ｄ][^—。！？\n]*[—-]*",
        "",
        text,
    )
    cleaned = re.sub(
        r"(?:你(?:的)?(?:回答|选择)(?:是)?(?:正确|错误)|你答对了|你答错了)"
        r"[，,：:—-]*",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"正确答案(?:也是|是)\s*[A-DＡ-Ｄ][^。！？\n]*[。！？]?",
        "",
        cleaned,
    )
    return cleaned.strip(" \n—-")


def strip_repetitive_profile_intro(text: str, history_context: str = "") -> str:
    """Remove explicit profile recaps while keeping the technical sentence."""
    if not text:
        return ""
    del history_context

    role_pattern = "|".join(re.escape(marker) for marker in ROLE_MARKERS)
    # Keep the technical sentence while removing a leading role/scenario label.
    without_profile_clause = re.sub(
        rf"(?m)^(?:作为|针对)\s*[^，。！？\n]{{0,15}}(?:{role_pattern})"
        r"[^，。！？\n]{0,20}(?:用于|用在|面向)"
        r"[^，。！？\n]{0,30}[，,]\s*",
        "",
        text,
        count=1,
    )
    text = without_profile_clause.strip()

    # The same service-style recap may appear on the first body line after a
    # Markdown heading, so do not limit this cleanup to the whole-string start.
    text = re.sub(
        r"(?m)^(?:明白，|明白了，)"
        r"(?=[^。！？\n]{0,180}(?:你是|你的岗位|要用于|用在|使用场景))"
        r"(?=[^。！？\n]{0,180}(?:我这就|马上|为你|给你讲|聚焦))"
        r"[^。！？\n]{0,180}[。！？]\s*",
        "",
        text,
        count=1,
    ).strip()

    match = re.match(r"^([^。！？]{0,180}[。！？])\s*(.+)$", text, flags=re.DOTALL)
    if not match:
        return text
    first_sentence, remainder = match.groups()
    repeats_profile = any(
        marker in first_sentence
        for marker in ("你是", "你的岗位", "要用于", "用在", "使用场景", "这个场景")
    )
    service_preamble = first_sentence.startswith(("明白，", "明白了，")) and any(
        marker in first_sentence
        for marker in ("我这就", "马上", "为你", "给你讲", "聚焦")
    )
    if repeats_profile and service_preamble:
        return remainder.strip()
    return text


def remove_quiz_content(text: str) -> str:
    """Remove learner-facing option blocks, including inline option layouts."""
    if not text:
        return ""

    normalized = re.sub(
        r"[ \t]+(?=[A-DＡ-Ｄ][\.．、][ \t]*)",
        "\n",
        text,
    )
    lines = normalized.split("\n")
    option_pattern = re.compile(r"^\s*[A-DＡ-Ｄ][\.．、]\s*.+")
    ending_pattern = re.compile(r"你觉得是哪个|请(?:你)?(?:选择|作答)|说出你的答案")

    remove_indexes = set()
    idx = 0
    while idx < len(lines):
        if not option_pattern.match(lines[idx]):
            idx += 1
            continue

        option_indexes = []
        cursor = idx
        while cursor < len(lines):
            if option_pattern.match(lines[cursor]):
                option_indexes.append(cursor)
                cursor += 1
                continue
            if not lines[cursor].strip():
                cursor += 1
                continue
            break

        if len(option_indexes) >= 2:
            start = option_indexes[0]
            if start > 0 and re.search(
                r"[？?]|问题|哪(?:一|个|项)|多少|是否|应为|考考你",
                lines[start - 1],
            ):
                start -= 1
            if start > 0 and re.search(r"下一题|练一道|考考你", lines[start - 1]):
                start -= 1
            end = cursor - 1
            while end + 1 < len(lines) and (
                not lines[end + 1].strip() or ending_pattern.search(lines[end + 1])
            ):
                end += 1
            remove_indexes.update(range(start, end + 1))
        idx = max(cursor, idx + 1)

    cleaned = "\n".join(
        line for line_idx, line in enumerate(lines) if line_idx not in remove_indexes
    )
    cleaned = re.sub(
        r"[^。！？\n]*(?:你觉得是哪个|请(?:你)?(?:选择|作答)|说出你的答案)[？?。！!]?",
        "",
        cleaned,
    )
    return compact_output_lines(cleaned)


def normalize_markdown_sections(text: str) -> str:
    """Repair common Markdown list shapes into readable compact output."""
    if not text:
        return ""

    text = re.sub(
        r"\*\*\s*-\s+\*\*([^*\n：:]{1,40})\*\*[：:]?",
        r"- **\1**：",
        text,
    )
    text = re.sub(
        r"\*\*\s*-\s+([^*\n：:]{1,40})\*\*[：:]?",
        r"- **\1**：",
        text,
    )
    text = re.sub(
        r"(?m)^\s*\*\*\s*-\s+\*\*([^*\n：:]{1,40})\*\*[：:]?",
        r"- **\1**：",
        text,
    )
    text = re.sub(
        r"(?m)^\s*\*\*\s*-\s+([^*\n：:]{1,40})\*\*[：:]?",
        r"- **\1**：",
        text,
    )
    text = re.sub(
        r"(?m)^\s*[-*+]\s+\*\*\s*[-*+]\s+\*\*([^*\n：:]{1,40})\*\*[：:]?",
        r"- **\1**：",
        text,
    )
    text = re.sub(r"\s+(?=[-*+]\s+(?:\*\*|[\u4e00-\u9fffA-Za-z0-9]))", "\n", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "- ", text)

    heading_pattern = r"\*\*[一二三四五六七八九十]+[、.．][^*\n]{1,40}\*\*"
    if not re.search(heading_pattern, text):
        return text

    normalized = re.sub(rf"[ \t]+(?={heading_pattern})", "\n", text)
    normalized = re.sub(rf"({heading_pattern})[ \t]+", r"\1\n", normalized)
    normalized = re.sub(
        r"(?<=[。！？])[ \t]+(?=(?:这些|以上|总的来说|作为|你在|在现场|日常检查))",
        "\n",
        normalized,
    )

    lines = normalized.split("\n")
    repaired: List[str] = []
    inside_section = False
    has_section_detail = False
    closing_pattern = re.compile(
        r"^(?:这些|以上|总的来说|作为|你在|在现场|日常检查)"
    )
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if re.fullmatch(heading_pattern, line):
            repaired.append(f"### {line[2:-2].strip()}")
            inside_section = True
            has_section_detail = False
            continue
        if re.fullmatch(
            r"###\s+[一二三四五六七八九十]+[、.．][^\n]{1,40}",
            line,
        ):
            repaired.append(line)
            inside_section = True
            has_section_detail = False
            continue
        if inside_section and closing_pattern.match(line) and has_section_detail:
            inside_section = False
        if inside_section:
            if not re.match(r"^(?:[-*+]\s+|\d+[.)、]\s*)", line):
                line = f"- {line}"
            has_section_detail = True
        repaired.append(line)
    return "\n".join(repaired).strip()


def compact_output_lines(text: str) -> str:
    """Preserve one Markdown paragraph break and trim excess whitespace."""
    if not text:
        return ""

    compacted: List[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            if compacted and compacted[-1] != "":
                compacted.append("")
            continue
        compacted.append(line)
    compacted_text = "\n".join(compacted).strip()
    return re.sub(
        r"(?m)^(#{1,6}\s+[^\n]+)\n(?=\S)",
        r"\1\n\n",
        compacted_text,
    )


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
    result = truncated[: last_period + 1] if last_period > 0 else truncated.rstrip() + "..."
    if len(result) + len(TRUNCATE_SUFFIX) <= max_chars + 30:
        result += TRUNCATE_SUFFIX
    return result


def validate_response(text: str) -> List[str]:
    """Return explain-only contract violations still present in text."""
    violations: List[str] = []
    if not text.strip():
        return ["empty_response"]
    if re.search(r"</?(?:answer|references)>|\[(?:W|R)\d+(?:\.\d+)?\]", text):
        violations.append("forbidden_structured_markup")
    if "```" in text:
        violations.append("markdown_code_fence")
    if re.search(r"\*\*\s*[-*+]\s+\*\*", text):
        violations.append("malformed_markdown_list")
    bold_markers = text.count("**")
    unsafe_bold = any(
        not _safe_bold_content(content)
        for content in re.findall(r"\*\*([^*\n]+)\*\*", text)
    )
    if bold_markers % 2 or unsafe_bold:
        violations.append("malformed_markdown_emphasis")
    if re.search(
        r"(?:W|R)\d+(?:\.\d+)?(?:材料|资料|片段|原文|图\d+)?"
        r"|(?:如|见|参考)(?:W|R)\d+",
        text,
    ):
        violations.append("internal_reference_label")
    if re.search(r"你觉得是哪个|请(?:你)?(?:选择|作答)|说出你的答案", text):
        violations.append("quiz_not_allowed")
    option_lines = re.findall(r"(?m)^\s*[A-DＡ-Ｄ][\.．、]\s*.+", text)
    if len(option_lines) >= 2:
        violations.append("quiz_options_not_allowed")
    if re.search(r"正确答案(?:也是|是)\s*[A-DＡ-Ｄ]", text):
        violations.append("answer_judgement_not_allowed")
    return violations


def postprocess_response(
    text: str,
    max_chars: int = DEFAULT_MAX_CHARS,
    supports_quiz: bool = False,
    history_context: str = "",
) -> Dict[str, object]:
    """Clean a draft and return processed text plus validation metadata."""
    del supports_quiz
    original_violations = validate_response(text)
    processed = clean_response(text)
    processed = strip_profile_display_labels(processed)
    processed = normalize_spoken_units(processed)
    processed = strip_redundant_permille_explanations(processed)
    processed = normalize_markdown_emphasis(processed)
    processed = strip_internal_reference_labels(processed)
    processed = strip_repetitive_profile_intro(processed, history_context=history_context)
    processed = strip_quiz_judgement(processed)
    processed = remove_quiz_content(processed)
    processed = normalize_markdown_sections(processed)
    processed = strip_internal_reference_labels(processed)
    processed = compact_output_lines(processed)
    processed = truncate_response(processed, max_chars=max_chars)
    remaining_violations = validate_response(processed)
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
    parser.add_argument("--text", help="Draft text; JSON stdin is used when omitted")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.text is not None:
        payload = {"text": args.text, "max_chars": args.max_chars}
    else:
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
    result = postprocess_response(
        str(payload.get("text", "")),
        max_chars=int(payload.get("max_chars", args.max_chars)),
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
