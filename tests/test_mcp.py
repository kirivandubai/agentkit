"""X2-21: one MCP server skeleton — no server without its guard on Host, a sentence for the model, a defect logged."""

from __future__ import annotations

import asyncio
import logging

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from agentkit import mcp as kit  # noqa: E402

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
LOG = logging.getLogger("test.kit")


class OwnRoot(Exception):
    """A server's own root of sentences, not a subclass of AgentError (denodo_exec's ExecError is one)."""


def test_no_server_without_its_guard_on_host():
    with pytest.raises(kit.ConfigError, match="allowed_hosts is empty"):
        kit.build_server("x", instructions="", host="0.0.0.0", port=1, allowed_hosts=["", " "])


def test_a_request_under_a_foreign_host_is_refused():
    server = kit.build_server("x", instructions="i", host="0.0.0.0", port=8699, allowed_hosts=kit.host_names(8699))
    assert kit.host_names(8699) == ("127.0.0.1:8699", "localhost:8699")
    with TestClient(server.streamable_http_app(), base_url="http://127.0.0.1:8699") as client:
        assert client.post(kit.STREAMABLE_HTTP_PATH, json=INIT, headers=HEADERS).status_code == 200
        foreign = client.post("/mcp", json=INIT, headers={**HEADERS, "Host": "rebound.example:8699"})
        assert foreign.status_code == 421


def test_sentences_reach_the_model_and_defects_the_log(caplog):
    @kit.guarded(LOG)
    def refused() -> str:
        raise kit.Refused("пустой текст")

    @kit.guarded(LOG)
    def down() -> str:
        raise kit.Unavailable("сервис не ответил")

    @kit.guarded(LOG, internal="internal; see the log", what="deck tool")
    def broken() -> str:
        raise RuntimeError("/secret/path in the message")

    with pytest.raises(ToolError, match="^Отказ: пустой текст$"):
        asyncio.run(refused())
    with pytest.raises(ToolError, match="^Недоступно: сервис не ответил$"):
        asyncio.run(down())
    with caplog.at_level(logging.ERROR, logger="test.kit"), pytest.raises(ToolError) as raised:
        asyncio.run(broken())
    assert str(raised.value) == "internal; see the log" and raised.value.__cause__ is None
    assert "deck tool broken failed" in caplog.text and "/secret/path" in caplog.text


def test_a_servers_own_root_is_its_sentences():
    @kit.guarded(LOG, sentences=(OwnRoot,))
    def own() -> str:
        raise OwnRoot("the stand did not answer")

    @kit.guarded_async(LOG, sentences=(OwnRoot,))
    async def own_async() -> str:
        raise OwnRoot("refused")

    @kit.guarded_async(LOG)
    async def fine(x: int) -> int:
        return x + 1

    with pytest.raises(ToolError, match="^the stand did not answer$"):
        asyncio.run(own())
    with pytest.raises(ToolError, match="^refused$"):
        asyncio.run(own_async())
    assert asyncio.run(fine(1)) == 2
    assert fine.__name__ == "fine"  # wraps: FastMCP builds the schema from the body's signature
