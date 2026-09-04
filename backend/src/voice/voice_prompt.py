"""Deprecated compatibility facade for the Skill-owned voice tutor contract.

New code must use :class:`voice.tutor_skill_runtime.TutorSkillRuntime` directly.
"""

from voice.tutor_skill_runtime import DEFAULT_TUTOR_SKILL, TutorSkillRuntime


_runtime = TutorSkillRuntime(DEFAULT_TUTOR_SKILL)

VOICE_TUTOR_DESCRIPTION = _runtime.description
VOICE_TUTOR_INTRODUCTION = _runtime.introduction
VOICE_TUTOR_INSTRUCTIONS = _runtime.instructions
MAX_RESPONSE_CHARS = _runtime.max_response_chars


def truncate_response(text: str) -> str:
    """Delegate legacy callers to the active Skill's truncation contract."""
    return _runtime.contract.truncate_response(
        text,
        max_chars=MAX_RESPONSE_CHARS,
    )
