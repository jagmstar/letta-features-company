from __future__ import annotations

import io
import json
import logging
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import schedules_api as api  # noqa: E402


class NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:  # pragma: no cover - intentional for handler lifecycle
        pass


class MockSocket:
    def __init__(self, request_bytes: bytes) -> None:
        self._request = io.BytesIO(request_bytes)
        self.response = NonClosingBytesIO()

    def makefile(self, mode: str, *args, **kwargs):
        if "r" in mode:
            return self._request
        if "w" in mode:
            return self.response
        raise ValueError(f"unsupported mode: {mode}")

    def sendall(self, data: bytes) -> None:
        self.response.write(data)

    def close(self) -> None:  # pragma: no cover - nothing to close in tests
        pass


class ImagesAPITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.repo_root = self.root / "company"
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self.request_log_path = self.root / "meta" / ".schedules-api-requests.log"
        self.api_key = "test-api-key"

        self.image_manager = api.ImageManager(logger=logging.getLogger("imagegen.api.tests"))
        self.store = api.ScheduleStore(repo_root=self.repo_root)
        api.SchedulesHTTPRequestHandler.store = self.store
        self.context = api.APIContext(
            api_key=self.api_key,
            request_log_path=self.request_log_path,
            version="9.9.9-test",
            started_at=datetime.now(timezone.utc) - timedelta(seconds=90),
            image_manager=self.image_manager,
        )
        self.context.channels_manager._post_json = mock.Mock(return_value={"status": 200, "body": {"ok": True}})

    def request(
        self,
        method: str,
        path: str,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
        remote_ip: str = "127.0.0.1",
    ):
        request_headers = {"Host": "localhost"}
        if headers:
            request_headers.update(headers)
        request_headers["Content-Length"] = str(len(body))
        header_block = "".join(f"{key}: {value}\r\n" for key, value in request_headers.items())
        raw_request = f"{method} {path} HTTP/1.1\r\n{header_block}\r\n".encode("utf-8") + body
        sock = MockSocket(raw_request)
        server = mock.Mock()
        server.server_name = "localhost"
        server.server_port = api.DEFAULT_PORT
        server.app_context = self.context
        api.SchedulesHTTPRequestHandler(sock, (remote_ip, 54321), server)
        return self.parse_response(sock.response.getvalue())

    @staticmethod
    def parse_response(raw: bytes):
        header_blob, body = raw.split(b"\r\n\r\n", 1)
        lines = header_blob.decode("utf-8").split("\r\n")
        status_line = lines[0]
        status = int(status_line.split()[1])
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if not line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip()] = value.strip()
        payload = json.loads(body.decode("utf-8")) if body else None
        return status, headers, payload

    def auth_headers(self) -> dict[str, str]:
        return {api.API_KEY_HEADER: self.api_key}

    def test_generate_image_endpoint(self) -> None:
        body = json.dumps(
            {
                "prompt": "A neon city skyline at sunset",
                "size": "1024x1024",
                "style": "cinematic",
                "format": "png",
            }
        ).encode("utf-8")

        status, headers, payload = self.request("POST", "/api/images/generate", body=body, headers=self.auth_headers())

        self.assertEqual(status, 201)
        self.assertEqual(payload["operation"], "generate")
        self.assertEqual(payload["prompt"], "A neon city skyline at sunset")
        self.assertEqual(payload["size"], "1024x1024")
        self.assertEqual(payload["style"], "cinematic")
        self.assertEqual(payload["format"], "png")
        self.assertTrue(payload["image_id"])
        self.assertTrue(payload["image_data"].startswith("mock-image://"))
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertEqual(len(self.image_manager.list_history()), 1)

    def test_generate_image_rejects_blank_prompt(self) -> None:
        body = json.dumps({"prompt": "   "}).encode("utf-8")

        status, _, payload = self.request("POST", "/api/images/generate", body=body, headers=self.auth_headers())

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_prompt")
        self.assertEqual(payload["error"]["status"], 400)
        self.assertEqual(self.image_manager.list_history(), [])

    def test_edit_image_endpoint(self) -> None:
        generated = self.request(
            "POST",
            "/api/images/generate",
            body=json.dumps({"prompt": "A friendly robot in a garden"}).encode("utf-8"),
            headers=self.auth_headers(),
        )[2]
        edit_body = json.dumps({"prompt": "Add a red scarf and glowing eyes"}).encode("utf-8")

        status, _, payload = self.request(
            "POST",
            f"/api/images/{generated['image_id']}/edit",
            body=edit_body,
            headers=self.auth_headers(),
        )

        self.assertEqual(status, 201)
        self.assertEqual(payload["operation"], "edit")
        self.assertEqual(payload["source_image_id"], generated["image_id"])
        self.assertEqual(payload["edit_prompt"], "Add a red scarf and glowing eyes")
        self.assertEqual(payload["prompt"], "Add a red scarf and glowing eyes")
        self.assertEqual(len(self.image_manager.list_history()), 2)

    def test_edit_image_rejects_unknown_image(self) -> None:
        body = json.dumps({"prompt": "Add a red scarf"}).encode("utf-8")

        status, _, payload = self.request("POST", "/api/images/missing-image/edit", body=body, headers=self.auth_headers())

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "image_not_found")
        self.assertEqual(payload["error"]["status"], 404)

    def test_list_images_endpoint(self) -> None:
        self.request(
            "POST",
            "/api/images/generate",
            body=json.dumps({"prompt": "A watercolor mountain range"}).encode("utf-8"),
            headers=self.auth_headers(),
        )
        second = self.request(
            "POST",
            "/api/images/generate",
            body=json.dumps({"prompt": "A watercolor mountain range at night"}).encode("utf-8"),
            headers=self.auth_headers(),
        )[2]

        status, _, payload = self.request("GET", "/api/images", headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["items"]), 2)
        self.assertEqual(payload["items"][1]["image_id"], second["image_id"])

    def test_list_images_rejects_post(self) -> None:
        status, headers, payload = self.request("POST", "/api/images", headers=self.auth_headers())

        self.assertEqual(status, 405)
        self.assertEqual(payload["error"]["code"], "method_not_allowed")
        self.assertEqual(payload["error"]["status"], 405)
        self.assertEqual(headers["Allow"], "GET")

    def test_get_image_endpoint(self) -> None:
        generated = self.request(
            "POST",
            "/api/images/generate",
            body=json.dumps({"prompt": "A paper airplane over the ocean"}).encode("utf-8"),
            headers=self.auth_headers(),
        )[2]

        status, _, payload = self.request("GET", f"/api/images/{generated['image_id']}", headers=self.auth_headers())

        self.assertEqual(status, 200)
        self.assertEqual(payload["image_id"], generated["image_id"])
        self.assertEqual(payload["prompt"], "A paper airplane over the ocean")
        self.assertEqual(payload["operation"], "generate")

    def test_get_image_rejects_unknown_image(self) -> None:
        status, _, payload = self.request("GET", "/api/images/missing-image", headers=self.auth_headers())

        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "image_not_found")
        self.assertEqual(payload["error"]["status"], 404)


if __name__ == "__main__":
    unittest.main()
