from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


class ImageError(Exception):
    """Base exception for image generation failures."""


class InvalidPromptError(ImageError):
    """Raised when an image prompt is missing or invalid."""


class ImageGenerationError(ImageError):
    """Raised when image generation or editing fails."""


class ImageNotFoundError(ImageError):
    """Raised when a requested image cannot be found in history."""


@dataclass(slots=True)
class ImageRequest:
    prompt: str
    size: str = "1024x1024"
    style: str = "realistic"
    format: str = "png"


class ImageManager:
    """Mock image generation manager with in-memory history tracking."""

    def __init__(self, *, logger: logging.Logger | None = None) -> None:
        self._history: list[dict[str, Any]] = []
        self._history_index: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.logger = logger or logging.getLogger(__name__)
        if logger is None and not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())

    def generate(self, request: ImageRequest | str, *, size: str | None = None, style: str | None = None, format: str | None = None) -> dict[str, Any]:
        """Generate a mock image from text input and store the result in history."""

        image_request = self._coerce_request(request, size=size, style=style, format=format)
        self._validate_request(image_request)
        self.logger.info("Generating image from prompt")
        self.logger.debug("Image request: %s", image_request)

        try:
            rendered = self._render_image(image_request, operation="generate")
        except ImageError:
            self.logger.exception("Image generation failed")
            raise
        except Exception as exc:  # pragma: no cover - exercised through error-path tests
            self.logger.exception("Unexpected image generation failure")
            raise ImageGenerationError("Image generation failed") from exc

        record = self._store_record(
            operation="generate",
            request=image_request,
            rendered=rendered,
            source_image_id=None,
            edit_prompt=None,
        )
        self.logger.info("Generated image %s", record["image_id"])
        return copy.deepcopy(record)

    def edit(
        self,
        input_image: str | dict[str, Any],
        edit_prompt: str,
        *,
        size: str | None = None,
        style: str | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        """Edit an existing image using a prompt and store the derived result."""

        self._validate_prompt(edit_prompt)
        source = self._resolve_source_image(input_image)
        image_request = ImageRequest(
            prompt=edit_prompt,
            size=size or source["size"],
            style=style or source["style"],
            format=format or source["format"],
        )
        self._validate_request(image_request)
        self.logger.info("Editing image %s", source["image_id"])
        self.logger.debug("Edit prompt: %s", image_request.prompt)

        try:
            rendered = self._render_image(
                image_request,
                operation="edit",
                source_image=source,
            )
        except ImageError:
            self.logger.exception("Image editing failed")
            raise
        except Exception as exc:  # pragma: no cover - exercised through error-path tests
            self.logger.exception("Unexpected image editing failure")
            raise ImageGenerationError("Image editing failed") from exc

        record = self._store_record(
            operation="edit",
            request=image_request,
            rendered=rendered,
            source_image_id=source["image_id"],
            edit_prompt=edit_prompt,
        )
        self.logger.info("Edited image %s from source %s", record["image_id"], source["image_id"])
        return copy.deepcopy(record)

    def list_history(self) -> list[dict[str, Any]]:
        """Return a copy of the full generation history."""

        with self._lock:
            return [copy.deepcopy(item) for item in self._history]

    def get_image(self, image_id: str) -> dict[str, Any]:
        """Return a stored image by id."""

        if not isinstance(image_id, str) or not image_id.strip():
            raise ImageNotFoundError("Image id must be a non-empty string")

        with self._lock:
            record = self._history_index.get(image_id)
            if record is None:
                raise ImageNotFoundError(f"Image not found: {image_id}")
            return copy.deepcopy(record)

    def _coerce_request(
        self,
        request: ImageRequest | str,
        *,
        size: str | None,
        style: str | None,
        format: str | None,
    ) -> ImageRequest:
        if isinstance(request, ImageRequest):
            return ImageRequest(
                prompt=request.prompt,
                size=size or request.size,
                style=style or request.style,
                format=format or request.format,
            )
        if isinstance(request, str):
            return ImageRequest(
                prompt=request,
                size=size or "1024x1024",
                style=style or "realistic",
                format=format or "png",
            )
        raise InvalidPromptError("Prompt must be provided as text or ImageRequest")

    @staticmethod
    def _validate_prompt(prompt: str) -> None:
        if not isinstance(prompt, str) or not prompt.strip():
            raise InvalidPromptError("Prompt must be a non-empty string")

    def _validate_request(self, request: ImageRequest) -> None:
        self._validate_prompt(request.prompt)
        if not isinstance(request.size, str) or not request.size.strip():
            raise InvalidPromptError("Image size must be a non-empty string")
        if not isinstance(request.style, str) or not request.style.strip():
            raise InvalidPromptError("Image style must be a non-empty string")
        if not isinstance(request.format, str) or not request.format.strip():
            raise InvalidPromptError("Image format must be a non-empty string")

    def _resolve_source_image(self, input_image: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(input_image, str):
            return self.get_image(input_image)
        if isinstance(input_image, dict):
            image_id = input_image.get("image_id")
            if isinstance(image_id, str) and image_id.strip():
                return self.get_image(image_id)
        raise ImageNotFoundError("Input image must be an image id or stored image record")

    def _render_image(
        self,
        request: ImageRequest,
        *,
        operation: str,
        source_image: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        seed_payload = {
            "operation": operation,
            "prompt": request.prompt.strip(),
            "size": request.size.strip(),
            "style": request.style.strip(),
            "format": request.format.strip(),
            "source_image_id": source_image["image_id"] if source_image else None,
        }
        digest_source = json.dumps(seed_payload, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        return {
            "image_data": f"mock-image://{digest[:24]}",
            "render_hash": digest,
            "operation": operation,
            "generated_with": "mock-placeholder",
        }

    def _store_record(
        self,
        *,
        operation: str,
        request: ImageRequest,
        rendered: dict[str, Any],
        source_image_id: str | None,
        edit_prompt: str | None,
    ) -> dict[str, Any]:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record: dict[str, Any] = {
            "image_id": uuid.uuid4().hex,
            "operation": operation,
            "request": asdict(request),
            "prompt": request.prompt.strip(),
            "size": request.size.strip(),
            "style": request.style.strip(),
            "format": request.format.strip(),
            "image_data": rendered["image_data"],
            "render_hash": rendered["render_hash"],
            "generated_with": rendered["generated_with"],
            "created_at": created_at,
            "source_image_id": source_image_id,
            "edit_prompt": edit_prompt,
            "metadata": {
                "operation": operation,
                "source_image_id": source_image_id,
                "edit_prompt": edit_prompt,
                "render_hash": rendered["render_hash"],
                "generated_with": rendered["generated_with"],
            },
        }

        with self._lock:
            self._history.append(record)
            self._history_index[record["image_id"]] = record
        return record
