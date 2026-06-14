from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from app import api
from app.discovery.providers.base import UnsupportedProviderError
from app.discovery import service


def _start_server(monkeypatch, tmp_path):
    monkeypatch.setattr(api.settings, "discovery_db_path", tmp_path / "discovery.db")
    monkeypatch.setattr(api.settings, "download_media_dir", tmp_path / "downloads")
    monkeypatch.setattr(api.settings, "api_token", "")
    server = api.run_api_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_discovery_preview_http(monkeypatch, tmp_path):
    called = {}

    def fake_preview(*, top_n=0):
        called["top_n"] = top_n
        return {
            "provider": "fake",
            "raw_count": 2,
            "selected_count": 1,
            "items": [{"video_id": "abc123def45"}],
            "raw_items": [{"video_id": "abc123def45"}, {"video_id": "abc123def46"}],
        }

    monkeypatch.setattr(service, "discovery_preview", fake_preview)
    server, base = _start_server(monkeypatch, tmp_path)

    try:
        req = urllib.request.Request(
            base + "/api/discovery/preview",
            data=json.dumps({"top_n": 1}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert called["top_n"] == 1
        assert body["ok"] is True
        assert body["data"]["provider"] == "fake"
        assert body["data"]["selected_count"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_discovery_preview_reports_unsupported_provider(monkeypatch, tmp_path):
    def fake_preview(*, top_n=0):
        raise UnsupportedProviderError("not supported")

    monkeypatch.setattr(service, "discovery_preview", fake_preview)
    server, base = _start_server(monkeypatch, tmp_path)

    try:
        req = urllib.request.Request(base + "/api/discovery/preview", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as resp:
            body = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 400
            assert body["ok"] is False
            assert body["error"]["code"] == "unsupported_provider"
        else:
            raise AssertionError("Expected HTTP 400")
    finally:
        server.shutdown()
        server.server_close()

