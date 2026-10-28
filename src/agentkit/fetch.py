"""HTTP as an agent's own code makes it: no redirect followed, no proxy of the environment, a bounded body, and an
address check for a host nobody vetted.

- A redirect is the answer, not a way on: urllib would send the request's headers — a key, a PAT — on to wherever the
  server points. NoRedirect turns a 3xx into an answer with its status.
- ProxyHandler({}): the default opener takes http_proxy and the system's proxy; a key must not travel through one.
- A failure of the network or of the request itself is FetchFailed, whose text is the error's class alone: urllib's
  texts can carry the address with its query, and a refused header's text can be the header (a key's).
- is_public: whether an address is the internet's, for a fetch of an address a model chose (SSRF).

Stdlib only and Python 3.9 (annotations are never evaluated): dev's box takes a vendored copy of it.
Named fetch, not http: a vendored copy must never stand in for the standard library's http package.
"""

from __future__ import annotations

import ipaddress
import json as jsonlib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from email.message import Message
from typing import Any

MOST_BYTES = 1024 * 1024
# IPv6 ranges that carry or translate to an IPv4 address (or are retired), which `is_global` of the standard library
# does not all refuse: the address inside would be judged by no one.
NOT_PUBLIC_V6 = tuple(ipaddress.ip_network(net) for net in (
    "::/96", "::ffff:0:0:0/96", "64:ff9b::/96", "2002::/16", "2001::/32", "fec0::/10"))


class FetchFailed(OSError):
    """No answer: the network, a timeout, or a request urllib refused to send. The text says only what kind."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is the answer, not a way on: urllib then raises it as an HTTPError of its 3xx status."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def opener() -> urllib.request.OpenerDirector:
    """An opener through no proxy that follows no redirect."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)


@dataclass(frozen=True)
class Answer:
    status: int
    headers: Message
    body: bytes  # at most `most` bytes
    cut: bool  # the body was longer than `most`

    def json(self) -> Any:
        return jsonlib.loads(self.body)


def fetch(url: str, *, method: str = "GET", data: bytes | None = None, json: Any = None,
          headers: Mapping[str, str] | None = None, timeout: float = 30.0, most: int = MOST_BYTES) -> Answer:
    """One request: its answer whatever its status (a 3xx included, not followed), the body read to most bytes.
    json: a body to send as JSON (with its Content-Type). FetchFailed when no answer came."""
    sent = dict(headers or {})
    if json is not None:
        data = jsonlib.dumps(json, ensure_ascii=False).encode("utf-8")
        sent.setdefault("Content-Type", "application/json")
    try:
        request = urllib.request.Request(url, data=data, headers=sent, method=method)
        try:
            with opener().open(request, timeout=timeout) as response:
                return _answer(response.status, response.headers, response.read(most + 1), most)
        except urllib.error.HTTPError as error:
            with error:
                return _answer(error.code, error.headers, error.read(most + 1), most)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise FetchFailed(f"{method} failed ({type(error).__name__})") from None


def _answer(status: int, headers: Message, raw: bytes, most: int) -> Answer:
    return Answer(status, headers, raw[:most], len(raw) > most)


def is_public(address: str) -> bool:
    """Whether an address is the internet's. `is_global` alone lets multicast through (224/4 is "global"), and an
    IPv4-mapped IPv6 address is judged by the IPv4 address it carries."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv6Address) and any(ip in net for net in NOT_PUBLIC_V6):
        return False
    return ip.is_global and not ip.is_multicast
