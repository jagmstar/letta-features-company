from __future__ import annotations

from pathlib import Path

import pytest

from skills.skills_manager import DisabledSkillError, Skill, SkillNotFoundError, SkillsManager


SKILLS_DIR = Path(__file__).resolve().parents[1]


def test_register_skill() -> None:
    manager = SkillsManager()
    skill = Skill(name="adder", description="Add two numbers", version="1.0.0")

    manager.register(skill, lambda a, b: a + b)

    assert manager.get("adder") is skill
    assert [item.name for item in manager.list()] == ["adder"]


def test_enable_disable_skill() -> None:
    manager = SkillsManager()
    skill = Skill(name="toggle", description="Toggle a skill", version="1.0.0", enabled=False)
    manager.register(skill, lambda: "ok")

    assert manager.get("toggle").enabled is False

    manager.enable("toggle")
    assert manager.get("toggle").enabled is True

    manager.disable("toggle")
    assert manager.get("toggle").enabled is False


def test_execute_skill(capsys: pytest.CaptureFixture[str]) -> None:
    manager = SkillsManager()
    skill = Skill(name="concat", description="Concatenate strings", version="1.0.0")
    manager.register(skill, lambda first, second: f"{first}-{second}")

    result = manager.execute("concat", "alpha", "beta")

    assert result == "alpha-beta"
    assert manager.execution_log[-1]["status"] == "success"

    captured = capsys.readouterr()
    assert captured.out == ""


def test_skill_not_found() -> None:
    manager = SkillsManager()

    with pytest.raises(SkillNotFoundError):
        manager.get("missing")


def test_disabled_skill_rejection() -> None:
    manager = SkillsManager()
    skill = Skill(name="disabled", description="Disabled skill", version="1.0.0", enabled=True)
    manager.register(skill, lambda: "should not run")
    manager.disable("disabled")

    with pytest.raises(DisabledSkillError):
        manager.execute("disabled")


def test_load_skills_from_directory(capsys: pytest.CaptureFixture[str]) -> None:
    manager = SkillsManager()

    loaded = manager.load_skills_from_directory(SKILLS_DIR)

    assert any(skill.name == "example_greeting" for skill in loaded)
    assert manager.get("example_greeting").description.startswith("Print a friendly greeting")

    result = manager.execute("example_greeting", "Developer")
    captured = capsys.readouterr()

    assert result == "Hello, Developer!"
    assert "Hello, Developer!" in captured.out
