from __future__ import annotations

import logging
from pathlib import Path

import pytest

from skills.skills_manager import Skill, SkillExecutionError, SkillsManager


def test_register_skill_with_empty_name_rejected() -> None:
    manager = SkillsManager()
    invalid_skill = Skill(name="", description="Invalid skill", version="1.0.0")

    with pytest.raises(ValueError):
        manager.register(invalid_skill, lambda: None)


def test_execute_skill_that_raises_is_wrapped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = SkillsManager()
    skill = Skill(name="boom", description="Raises an error", version="1.0.0")

    def explode() -> None:
        raise RuntimeError("boom")

    manager.register(skill, explode)

    with caplog.at_level(logging.ERROR, logger="skills.skills_manager"):
        with pytest.raises(SkillExecutionError, match="Skill execution failed: boom"):
            manager.execute("boom")

    assert manager.execution_log[-1]["skill"] == "boom"
    assert manager.execution_log[-1]["status"] == "failed"
    assert "Skill boom execution failed" in caplog.text
    assert "RuntimeError: boom" in caplog.text


def test_load_skills_from_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_skills"
    empty_dir.mkdir()

    manager = SkillsManager()

    assert manager.load_skills_from_directory(empty_dir) == []
    assert manager.list() == []


def test_load_skills_from_nonexistent_directory_handles_gracefully(tmp_path: Path) -> None:
    manager = SkillsManager()
    missing_dir = tmp_path / "missing_skills"

    assert manager.load_skills_from_directory(missing_dir) == []
    assert manager.list() == []


def test_register_duplicate_skill_rejected() -> None:
    manager = SkillsManager()
    original = Skill(name="dup", description="First", version="1.0.0")
    replacement = Skill(name="dup", description="Second", version="1.0.1")

    manager.register(original, lambda: "first")

    with pytest.raises(ValueError):
        manager.register(replacement, lambda: "second")

    assert manager.get("dup") is original
    assert manager.execute("dup") == "first"


def test_execute_skill_with_invalid_arguments_is_wrapped() -> None:
    manager = SkillsManager()
    skill = Skill(name="needs_args", description="Needs two args", version="1.0.0")
    manager.register(skill, lambda first, second: f"{first}-{second}")

    with pytest.raises(SkillExecutionError, match="Skill execution failed: needs_args"):
        manager.execute("needs_args", "only-one-arg")

    assert manager.execution_log[-1]["skill"] == "needs_args"
    assert manager.execution_log[-1]["status"] == "failed"
    assert manager.execution_log[-1]["args"] == ("only-one-arg",)
    assert manager.execution_log[-1]["kwargs"] == {}
