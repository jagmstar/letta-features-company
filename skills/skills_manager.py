from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SkillError(Exception):
    """Base class for skill management errors."""


class SkillNotFoundError(SkillError):
    """Raised when a requested skill does not exist."""


class DisabledSkillError(SkillError):
    """Raised when a disabled skill is executed."""


class SkillExecutionError(SkillError):
    """Raised when a skill fails during execution."""


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    version: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


SkillExecutor = Callable[..., Any]


class SkillsManager:
    """Register, manage, load, and execute skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._executors: dict[str, SkillExecutor] = {}
        self.execution_log: list[dict[str, Any]] = []

    def register(self, skill: Skill, execute: SkillExecutor | None = None) -> Skill:
        """Register a skill and optionally its executable handler."""

        self._skills[skill.name] = skill
        if execute is not None:
            self._executors[skill.name] = execute
        return skill

    def enable(self, name: str) -> Skill:
        skill = self.get(name)
        skill.enabled = True
        return skill

    def disable(self, name: str) -> Skill:
        skill = self.get(name)
        skill.enabled = False
        return skill

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise SkillNotFoundError(f"Skill not found: {name}") from exc

    def execute(self, name: str, *args: Any, **kwargs: Any) -> Any:
        skill = self.get(name)
        if not skill.enabled:
            raise DisabledSkillError(f"Skill is disabled: {name}")

        executor = self._executors.get(name)
        if executor is None:
            raise SkillExecutionError(f"No executor registered for skill: {name}")

        try:
            result = executor(*args, **kwargs)
        except Exception as exc:  # pragma: no cover - exercised through failure handling tests
            logger.exception("Skill %s execution failed", name)
            self.execution_log.append(
                {
                    "skill": name,
                    "status": "failed",
                    "args": args,
                    "kwargs": kwargs,
                    "error": str(exc),
                }
            )
            raise SkillExecutionError(f"Skill execution failed: {name}") from exc

        logger.info("Skill %s executed successfully", name)
        logger.debug("Skill %s result: %r", name, result)
        self.execution_log.append(
            {
                "skill": name,
                "status": "success",
                "args": args,
                "kwargs": kwargs,
                "result": result,
            }
        )
        return result

    def load_skills_from_directory(self, directory: str | Path) -> list[Skill]:
        """Load skills from Python modules in a directory."""

        directory_path = Path(directory)
        if not directory_path.exists():
            raise FileNotFoundError(f"Skills directory does not exist: {directory_path}")

        loaded: list[Skill] = []
        for skill_path in sorted(directory_path.glob("*.py")):
            if skill_path.name in {"__init__.py", "skills_manager.py"} or skill_path.name.startswith("_"):
                continue

            module = self._load_module_from_path(skill_path)
            meta = getattr(module, "SKILL_META", None)
            execute = getattr(module, "execute", None)
            if not isinstance(meta, dict):
                logger.debug("Skipping %s because SKILL_META is missing or invalid", skill_path)
                continue
            if not callable(execute):
                logger.debug("Skipping %s because execute() is missing or invalid", skill_path)
                continue

            skill = self._skill_from_meta(meta)
            self.register(skill, execute)
            loaded.append(skill)

        return loaded

    @staticmethod
    def _load_module_from_path(path: Path) -> ModuleType:
        module_name = f"_loaded_skill_{abs(hash(path.resolve()))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise SkillExecutionError(f"Unable to load skill module: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _skill_from_meta(meta: dict[str, Any]) -> Skill:
        try:
            name = str(meta["name"])
            description = str(meta["description"])
            version = str(meta["version"])
        except KeyError as exc:
            raise ValueError("SKILL_META must include name, description, and version") from exc

        enabled = bool(meta.get("enabled", True))
        config: dict[str, Any] = {}

        raw_config = meta.get("config", {})
        if isinstance(raw_config, dict):
            config.update(raw_config)

        for key, value in meta.items():
            if key not in {"name", "description", "version", "enabled", "config"}:
                config[key] = value

        return Skill(name=name, description=description, version=version, enabled=enabled, config=config)
