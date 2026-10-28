"""X2-22 (а): one HTTP client of agents' own code — no redirect, no proxy, a bounded body, a text without the URL."""

import http.server
import threading

import pytest

from agentkit import fetch as kit


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server's name
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/elsewhere")
            self.end_headers()
            return
        if self.path == "/big":
            body = b"x" * 100
        elif self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "no"}')
            return
        else:
            body = (self.headers.get("Authorization") or "").encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET  # noqa: N815

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_an_answer_whatever_its_status_and_no_redirect_followed(server):
    answer = kit.fetch(server + "/redirect", headers={"Authorization": "Bearer k"})
    assert answer.status == 302 and answer.headers["Location"] == "http://example.invalid/elsewhere"
    missing = kit.fetch(server + "/missing")
    assert missing.status == 404 and missing.json() == {"error": "no"}
    ok = kit.fetch(server + "/echo", headers={"Authorization": "Bearer k"}, method="POST", json={"a": 1})
    assert ok.status == 200 and ok.body == b"Bearer k" and not ok.cut


def test_the_body_is_bounded(server):
    answer = kit.fetch(server + "/big", most=10)
    assert answer.body == b"x" * 10 and answer.cut


def test_no_proxy_of_the_environment(server, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")  # nothing listens there
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert kit.fetch(server + "/echo").status == 200


def test_a_failure_says_its_kind_not_the_address():
    with pytest.raises(kit.FetchFailed) as error:
        kit.fetch("http://127.0.0.1:9/path?key=SECRET", timeout=2)
    assert "SECRET" not in str(error.value) and "127.0.0.1" not in str(error.value)
    with pytest.raises(kit.FetchFailed) as refused:
        kit.fetch("http://127.0.0.1:9/", headers={"Authorization": "Bearer SECRET\nX: y"})
    assert "SECRET" not in str(refused.value)


@pytest.mark.parametrize("address, public", [
    ("8.8.8.8", True), ("2606:4700:4700::1111", True),
    ("10.0.0.1", False), ("127.0.0.1", False), ("169.254.1.1", False), ("100.64.0.1", False),
    ("224.0.0.1", False), ("::1", False), ("::ffff:10.0.0.1", False), ("64:ff9b::a00:1", False),
    ("2002:a00:1::", False), ("not an address", False),
])
def test_is_public(address, public):
    assert kit.is_public(address) is public
