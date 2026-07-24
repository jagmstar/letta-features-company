from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from imagegen.image_manager import (  # noqa: E402
    ImageGenerationError,
    ImageManager,
    ImageNotFoundError,
    ImageRequest,
    InvalidPromptError,
)


@pytest.fixture()
def manager() -> ImageManager:
    return ImageManager(logger=logging.getLogger("imagegen.tests"))


def test_generate_image_from_text_prompt(manager: ImageManager) -> None:
    request = ImageRequest(prompt="A neon city skyline at sunset", size="1024x1024", style="cinematic", format="png")

    image = manager.generate(request)

    assert image["operation"] == "generate"
    assert image["prompt"] == "A neon city skyline at sunset"
    assert image["size"] == "1024x1024"
    assert image["style"] == "cinematic"
    assert image["format"] == "png"
    assert image["image_data"].startswith("mock-image://")
    assert image["image_id"]
    assert manager.list_history() == [image]
    assert manager.get_image(image["image_id"])["image_id"] == image["image_id"]


def test_edit_image_with_prompt(manager: ImageManager) -> None:
    source = manager.generate("A friendly robot in a garden")

    edited = manager.edit(source["image_id"], "Add a red scarf and glowing eyes")

    assert edited["operation"] == "edit"
    assert edited["source_image_id"] == source["image_id"]
    assert edited["edit_prompt"] == "Add a red scarf and glowing eyes"
    assert edited["prompt"] == "Add a red scarf and glowing eyes"
    assert edited["image_data"].startswith("mock-image://")

    history = manager.list_history()
    assert len(history) == 2
    assert [item["operation"] for item in history] == ["generate", "edit"]
    assert history[1]["source_image_id"] == source["image_id"]


def test_list_history_returns_all_images_in_order(manager: ImageManager) -> None:
    first = manager.generate("A watercolor mountain range")
    second = manager.generate("A watercolor mountain range at night")
    third = manager.edit(second["image_id"], "Add stars and a full moon")

    history = manager.list_history()

    assert [item["image_id"] for item in history] == [first["image_id"], second["image_id"], third["image_id"]]
    assert history[0]["metadata"]["operation"] == "generate"
    assert history[2]["metadata"]["source_image_id"] == second["image_id"]


def test_invalid_prompt_raises_error(manager: ImageManager) -> None:
    with pytest.raises(InvalidPromptError):
        manager.generate(ImageRequest(prompt="   "))


def test_generation_failure_is_wrapped(manager: ImageManager, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("mock render failure")

    monkeypatch.setattr(manager, "_render_image", explode)

    with pytest.raises(ImageGenerationError) as exc_info:
        manager.generate("An image that cannot be rendered")

    assert "Image generation failed" in str(exc_info.value)
