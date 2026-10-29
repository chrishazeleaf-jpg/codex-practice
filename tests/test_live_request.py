"""Checks the request the live client sends, against a local fake API server (no network)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from atlas.budget import Budget
from atlas.llm import RefusalError, make_client

anthropic = pytest.importorskip("anthropic")


def _serve(reply):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def _message(stop_reason="end_turn", **extra):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": "ok"}], "stop_reason": stop_reason,
            "stop_sequence": None, "usage": {"input_tokens": 1000, "output_tokens": 100}, **extra}


@pytest.fixture
def no_proxy(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)


def _client(server, tmp_path):
    client = make_client(Budget(0, tmp_path / "spend.json"), api_key="test-key")
    client.raw = client.raw.with_options(base_url=f"http://127.0.0.1:{server.server_port}",
                                         max_retries=0)
    return client


def test_live_request_shape(tmp_path, no_proxy):
    server, seen = _serve(_message())
    try:
        client = _client(server, tmp_path)
        resp = client.create(model="claude-opus-5-5", max_tokens=500, system="sys",
                             messages=[{"role": "user", "content": "hi"}],
                             tools=[{"name": "t", "description": "d",
                                     "input_schema": {"type": "object", "properties": {}}}],
                             effort="high")
    finally:
        server.shutdown()

    assert resp.content[0].text == "ok"
    req = seen[0]
    assert req["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in req["headers"].get("anthropic-beta", "")
    body = req["body"]
    assert body["fallbacks"] == "default"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["output_config"] == {"effort": "high"}
    assert body["tools"][0]["name"] == "t"
    assert client.budget.spent_today() == pytest.approx((1000 * 4 + 100 * 20) / 1e6)


def test_refusal_raises(tmp_path, no_proxy):
    server, _ = _serve(_message("refusal", stop_details={
        "type": "refusal", "category": "cyber", "explanation": "declined"}))
    try:
        with pytest.raises(RefusalError):
            _client(server, tmp_path).create(model="claude-opus-5-5", max_tokens=100, system="s",
                                              messages=[{"role": "user", "content": "x"}])
    finally:
        server.shutdown()
