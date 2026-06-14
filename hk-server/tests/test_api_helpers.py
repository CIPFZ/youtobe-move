import io
import json

from app import api


class DummyHandler:
    def __init__(self, headers=None):
        self.headers = headers or {}
        self.status = None
        self.response_headers = []
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers.append((key, value))

    def end_headers(self):
        pass


def test_json_success_and_error_envelopes():
    ok = DummyHandler()
    api._success_response(ok, {"value": 1})
    assert ok.status == 200
    assert json.loads(ok.wfile.getvalue().decode("utf-8")) == {
        "ok": True,
        "data": {"value": 1},
    }

    err = DummyHandler()
    api._error_response(err, "bad input", status=400)
    body = json.loads(err.wfile.getvalue().decode("utf-8"))
    assert err.status == 400
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_request"
    assert body["error"]["message"] == "bad input"


def test_video_id_helpers():
    assert api._parse_video_id("/api/videos/abc123/file") == "abc123"
    assert api._parse_video_id("/api/stats") is None
    assert api._extract_youtube_video_id("https://www.youtube.com/watch?v=abc123def45") == "abc123def45"
    assert api._extract_youtube_video_id("https://youtu.be/abc123def45") == "abc123def45"
    assert api._extract_youtube_video_id("not youtube") == ""


def test_stream_file_supports_range_requests(tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"0123456789")
    handler = DummyHandler(headers={"Range": "bytes=2-5"})

    api._stream_file(handler, target, "application/octet-stream")

    assert handler.status == 206
    assert ("Content-Range", "bytes 2-5/10") in handler.response_headers
    assert handler.wfile.getvalue() == b"2345"


def test_stream_file_rejects_invalid_range(tmp_path):
    target = tmp_path / "sample.bin"
    target.write_bytes(b"0123456789")
    handler = DummyHandler(headers={"Range": "bytes=99-100"})

    api._stream_file(handler, target, "application/octet-stream")

    assert handler.status == 416
    body = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert body["ok"] is False
    assert body["error"]["code"] == "range_not_satisfiable"
