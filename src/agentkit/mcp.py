"""The skeleton every agent's MCP tool server shares (agent-os docs/agent-standard.md, §4): a FastMCP server on
streamable HTTP that cannot be built without its guard on Host, the errors a tool tells apart, and the wrapper that
turns them into one sentence for the model.

Needs the `mcp` extra (`agentkit[mcp]`); the stdlib core does not import this module. A server whose errors have a
root of their own (a package it shares with others, such as denodo_exec) passes that root as `sentences` rather than
subclassing these.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

STREAMABLE_HTTP_PATH = "/mcp"
# The names a request arrives under: compose publishes the port on the host's loopback alone, where agent-os asks.
LOOPBACK_NAMES = ("127.0.0.1", "localhost")
INTERNAL = "внутренняя ошибка сервера; подробности — в его журнале"


class AgentError(Exception):
    """Base for everything a server raises on purpose: its text is a sentence for the model."""


class ConfigError(AgentError):
    """The server's environment is missing or malformed, so it refuses to start: a typo is a line in the container's
    log, never a server listening where it should not."""


class Refused(AgentError):
    """What was asked is refused before anything moved; asking the same again never helps, asking otherwise may."""

    def __str__(self) -> str:
        return f"Отказ: {super().__str__()}"


class Unavailable(AgentError):
    """What the server stands on did not answer: a fact about the moment, the same call may work later."""

    def __str__(self) -> str:
        return f"Недоступно: {super().__str__()}"


def host_names(port: int, names: Sequence[str] = LOOPBACK_NAMES) -> tuple[str, ...]:
    """The Host values a request to this port may carry: `127.0.0.1:<port>`, `localhost:<port>`."""
    return tuple(f"{name}:{port}" for name in names)


def build_server(name: str, *, instructions: str, host: str, port: int, allowed_hosts: Sequence[str]) -> FastMCP:
    """A server with its guard on Host. Set here, not left to FastMCP: in a container it listens on 0.0.0.0, and
    FastMCP guards only a server bound to loopback by itself; without the guard a page in the owner's browser whose
    name resolves to 127.0.0.1 could call the tools (DNS rebinding)."""
    hosts = [h.strip() for h in allowed_hosts if h and h.strip()]
    if not hosts:
        raise ConfigError("allowed_hosts is empty: the server would answer any Host (DNS rebinding); name the "
                          "host:port pairs it is reached at, such as 127.0.0.1:8699")
    return FastMCP(
        name,
        instructions=instructions,
        host=host,
        port=port,
        streamable_http_path=STREAMABLE_HTTP_PATH,
        # No session state: a restarted container strands no client.
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=[]),
    )


def _told(log: logging.Logger, what: str, name: str, internal: str, sentences: tuple[type[BaseException], ...],
          error: Exception) -> ToolError:
    """A sentence for the model: the text of a sentence class, one line for a defect (logged whole — its text can
    carry a path or a header that belongs in the log)."""
    if isinstance(error, sentences):
        return ToolError(str(error))
    log.error("%s %s failed", what, name, exc_info=error)
    return ToolError(internal)


def guarded(log: logging.Logger, *, sentences: Sequence[type[BaseException]] = (AgentError,),
            internal: str = INTERNAL, limiter: Any = None, what: str = "tool"
            ) -> Callable[[Callable[..., Any]], Callable[..., Awaitable[Any]]]:
    """A tool's synchronous body as a coroutine on a worker thread (limiter: anyio's, to bound the threads). An error
    of sentences becomes a ToolError with its text; anything else is a defect: logged whole, told to the model as
    internal. functools.wraps keeps the body's signature for FastMCP's schema."""
    kinds = tuple(sentences)

    def decorate(function: Callable[..., Any]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(function)
        async def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return await anyio.to_thread.run_sync(functools.partial(function, *args, **kwargs), limiter=limiter)
            except ToolError:
                raise
            except Exception as error:  # noqa: BLE001 — sorted into a sentence or a defect by _told
                raise _told(log, what, function.__name__, internal, kinds, error) from (
                    error if isinstance(error, kinds) else None)

        return call

    return decorate


def guarded_async(log: logging.Logger, *, sentences: Sequence[type[BaseException]] = (AgentError,),
                  internal: str = INTERNAL, what: str = "tool"
                  ) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """guarded for a tool that is a coroutine already (it awaits a subprocess rather than blocking a thread)."""
    kinds = tuple(sentences)

    def decorate(function: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(function)
        async def call(*args: Any, **kwargs: Any) -> Any:
            try:
                return await function(*args, **kwargs)
            except ToolError:
                raise
            except Exception as error:  # noqa: BLE001 — sorted into a sentence or a defect by _told
                raise _told(log, what, function.__name__, internal, kinds, error) from (
                    error if isinstance(error, kinds) else None)

        return call

    return decorate
