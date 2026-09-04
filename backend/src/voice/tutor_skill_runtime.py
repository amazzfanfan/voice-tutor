"""Project-local runtime for selecting and executing a voice tutor Skill."""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional

from agno.skills import LocalSkills, Skills

from algo.config import my_logger


DEFAULT_TUTOR_SKILL = "voice-tutor-guided-practice"

_BASE_CONTRACT_FUNCTIONS = ("postprocess_response",)
_PROFILE_CONTRACT_FUNCTIONS = ("build_profile_prompt",)
_QUIZ_CONTRACT_FUNCTIONS = (
    "extract_choice_question_blocks",
    "extract_choice_question_spans",
    "extract_choice_options",
    "looks_like_choice_answer",
    "looks_like_teaching_topic",
    "replace_question_span",
    "remove_forbidden_question_tail",
    "extract_material_bullets",
    "strip_internal_progress_text",
    "compact_output_lines",
    "question_title",
    "extract_answer_labels",
    "compact_review_point",
)


class TutorSkillRuntimeError(RuntimeError):
    """Raised when a configured tutor Skill is missing or malformed."""


class TutorSkillRuntime:
    """Load one active tutor Skill and expose a stable host-side interface."""

    def __init__(
        self,
        skill_name: str = DEFAULT_TUTOR_SKILL,
        project_root: Optional[Path] = None,
    ) -> None:
        self.skill_name = skill_name.strip() or DEFAULT_TUTOR_SKILL
        self.project_root = (
            Path(project_root).resolve()
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )
        self.skill_dir = (self.project_root / "skills" / self.skill_name).resolve()
        self.skills = Skills(loaders=[LocalSkills(str(self.skill_dir), validate=True)])
        self.skill = self.skills.get_skill(self.skill_name)
        if self.skill is None:
            raise TutorSkillRuntimeError(
                f"Tutor Skill '{self.skill_name}' was not loaded from {self.skill_dir}"
            )

        self.manifest = self._load_manifest()
        self._validate_manifest()
        self._reference_cache: Dict[str, str] = {}
        self._postprocessor = self._load_postprocessor()

    @classmethod
    def from_environment(cls) -> "TutorSkillRuntime":
        """Load the configured project-local tutor Skill."""
        skill_name = os.getenv("VOICE_TUTOR_SKILL", DEFAULT_TUTOR_SKILL).strip()
        return cls.from_settings(skill_name=skill_name)

    @classmethod
    def from_settings(
        cls,
        skill_name: str = DEFAULT_TUTOR_SKILL,
    ) -> "TutorSkillRuntime":
        """Load one configured Skill and fail fast when its contract is invalid."""
        skill_name = (skill_name or DEFAULT_TUTOR_SKILL).strip()
        runtime = cls(skill_name=skill_name)
        my_logger.info(f"[TutorSkillRuntime] Loaded active Skill: {runtime.skill_name}")
        return runtime

    @property
    def supports_quiz(self) -> bool:
        return bool(self.manifest.get("supports_quiz", False))

    @property
    def requires_profile(self) -> bool:
        return bool(self.manifest.get("requires_profile", False))

    @property
    def interaction_mode(self) -> str:
        return str(self.manifest.get("interaction_mode", ""))

    @property
    def description(self) -> str:
        return str(self.manifest.get("description", "工业领域AI语音讲师"))

    @property
    def introduction(self) -> str:
        return str(
            self.manifest.get(
                "introduction",
                "你好，我是你的AI工业讲师。你可以用语音和我交流。",
            )
        )

    @property
    def max_response_chars(self) -> int:
        return int(self.manifest.get("max_response_chars", 500))

    @property
    def instructions(self) -> str:
        return self.skill.instructions

    @property
    def contract(self) -> ModuleType:
        """Expose deterministic Skill helpers to the host workflow."""
        return self._postprocessor

    @property
    def agent_instructions(self) -> str:
        """Return the small bootstrap prompt that makes the Agent call the Skill."""
        return f"""
你是工业语音讲师的运行时智能体。当前唯一激活的教学 Skill 是 `{self.skill_name}`。
每次准备生成面向用户的回复前，必须先调用 `get_skill_instructions`，并传入 `{self.skill_name}`。
完整遵循该 Skill 的教学流程、证据边界、输出格式和语音风格；不得混用其他教学模式。
调用 Skill 或其他工具的过程只用于内部执行，不要向用户提及工具、Skill、系统提示词或校验过程。
""".strip()

    def render_reference(self, reference_key: str, **values: Any) -> str:
        """Load a manifest reference and replace its ``{{placeholder}}`` values."""
        references = self.manifest.get("references", {})
        filename = references.get(reference_key)
        if not filename:
            raise TutorSkillRuntimeError(
                f"Tutor Skill '{self.skill_name}' has no reference '{reference_key}'"
            )

        template = self._reference_cache.get(reference_key)
        if template is None:
            template = self._read_relative_text("references", str(filename))
            self._reference_cache[reference_key] = template

        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{{" + key + "}}", str(value))
        return rendered.strip()

    def build_generation_input(
        self,
        query: str,
        history_context: str = "",
        rag_context: str = "",
        web_context: str = "",
        cached_material_context: str = "",
        profile_context: str = "",
    ) -> str:
        """Build one main-agent input while keeping behavior rules inside the Skill."""
        sections = []
        if history_context:
            sections.append(f"## 对话历史\n{history_context}")
        if profile_context:
            sections.append(f"## 用户身份与使用场景（仅用于生成口吻）\n{profile_context}")
        if cached_material_context:
            sections.append(f"## 已缓存参考资料\n{cached_material_context}")
        if rag_context:
            sections.append(f"## 知识库检索结果\n{rag_context}")
        if web_context:
            sections.append(f"## 联网搜索结果\n{web_context}")
        sections.append(f"## 用户当前问题\n{query}")
        sections.append(
            "## 本轮生成补充规则\n"
            + self.render_reference("generation_rules")
        )
        return "\n\n".join(sections)

    def postprocess_response(
        self,
        text: str,
        history_context: str = "",
    ) -> Dict[str, Any]:
        """Run the active Skill's deterministic postprocessor in-process."""
        kwargs = {
            "max_chars": self.max_response_chars,
            "supports_quiz": self.supports_quiz,
        }
        parameters = inspect.signature(
            self._postprocessor.postprocess_response
        ).parameters
        if "history_context" in parameters:
            kwargs["history_context"] = history_context
        return self._postprocessor.postprocess_response(text, **kwargs)

    def build_profile_prompt(self, query: str, history_context: str = "") -> str:
        """Return a Skill-owned first-turn profile gate prompt when required."""
        if not self.requires_profile:
            return ""
        return str(
            self._postprocessor.build_profile_prompt(
                query=query,
                history_context=history_context,
            )
            or ""
        )

    def build_pre_retrieval_reply(self, query: str, history_context: str = "") -> str:
        """Return a Skill-owned repair reply when retrieval should be skipped."""
        guard = getattr(self._postprocessor, "build_pre_retrieval_reply", None)
        if not callable(guard):
            return ""
        return str(
            guard(
                query=query,
                history_context=history_context,
            )
            or ""
        )

    def _load_manifest(self) -> Dict[str, Any]:
        raw = self._read_relative_text("references", "runtime.json")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TutorSkillRuntimeError(f"Invalid runtime.json: {exc}") from exc
        if not isinstance(payload, dict):
            raise TutorSkillRuntimeError("runtime.json must contain a JSON object")
        return payload

    def _validate_manifest(self) -> None:
        if self.manifest.get("schema_version") != 1:
            raise TutorSkillRuntimeError("runtime.json schema_version must be 1")
        if not isinstance(self.manifest.get("supports_quiz"), bool):
            raise TutorSkillRuntimeError("runtime.json supports_quiz must be boolean")
        if not isinstance(self.manifest.get("requires_profile", False), bool):
            raise TutorSkillRuntimeError("runtime.json requires_profile must be boolean")
        if not isinstance(self.manifest.get("references"), dict):
            raise TutorSkillRuntimeError("runtime.json references must be an object")
        if not self.manifest.get("postprocessor"):
            raise TutorSkillRuntimeError("runtime.json must declare postprocessor")

    def _load_postprocessor(self) -> ModuleType:
        relative_path = str(self.manifest["postprocessor"])
        script_path = self._safe_skill_path(relative_path)
        spec = importlib.util.spec_from_file_location(
            f"voice_tutor_postprocessor_{self.skill_name.replace('-', '_')}",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise TutorSkillRuntimeError(
                f"Unable to import postprocessor: {relative_path}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        required_functions = list(_BASE_CONTRACT_FUNCTIONS)
        if self.requires_profile:
            required_functions.extend(_PROFILE_CONTRACT_FUNCTIONS)
        if self.supports_quiz:
            required_functions.extend(_QUIZ_CONTRACT_FUNCTIONS)
        missing_functions = [
            name for name in required_functions if not callable(getattr(module, name, None))
        ]
        if missing_functions:
            raise TutorSkillRuntimeError(
                f"Postprocessor '{relative_path}' is missing contract functions: "
                + ", ".join(missing_functions)
            )
        return module

    def _read_relative_text(self, subdir: str, filename: str) -> str:
        return self._safe_skill_path(f"{subdir}/{filename}").read_text(encoding="utf-8")

    def _safe_skill_path(self, relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise TutorSkillRuntimeError(f"Unsafe Skill path: {relative_path!r}")
        target = (self.skill_dir / relative_path).resolve()
        try:
            target.relative_to(self.skill_dir)
        except ValueError as exc:
            raise TutorSkillRuntimeError(
                f"Skill path escapes root: {relative_path!r}"
            ) from exc
        if not target.is_file():
            raise TutorSkillRuntimeError(f"Skill file does not exist: {relative_path}")
        return target
