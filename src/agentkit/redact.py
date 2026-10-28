"""Secrets out of text: one mask, the written-out credentials, known values, and the order the three go in.

Every place that hands text on — a journal record, a connection's failure, an install log, a door's sentence — used to
mask on its own, with its own mask and its own minimum. Here there is one recipe: known values replaced first
(longest first, so a key inside a longer secret goes with the whole of it), then credentials written out as such,
then the cut — in that order, so a cut through a key cannot leave half of it for no pattern to recognise.

Thresholds stay parameters: a journal must not blank a short word that happens to be a value ("bridge"), an install
log must catch a 4-character password. Stdlib only and Python 3.9 (annotations are never evaluated): a host script on
/usr/bin/python3 and dev's box run a vendored copy of it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

MASK = "‹secret›"

# A token-like run: 16 characters and more with a digit in them, so a sentence about «Bearer $KEY» or «basic
# authentication/roles» is left as it is.
_TOKEN = r"(?=[A-Za-z._~+/-]*\d)[A-Za-z0-9._~+/-]{16,}=*"
# An Authorization's scheme and its token; the scheme stays, so the text still says what was there.
AUTH_TOKEN = re.compile(rf"(?i)(?P<keep>\b(?:bearer|basic)\s+){_TOKEN}")
# An API key's name and its value, as a header, a query parameter or a JSON field writes it.
KEY_PAIR = re.compile(rf"(?i)(?P<keep>\b(?:x-api-key|api[_-]?key|access[_-]?token)[\"']?\s*[:=]\s*[\"']?){_TOKEN}")
# Keys whose own prefix says what they are, wherever they stand. Not after a letter, digit, '_' or '-': "task-…" holds
# "sk-", a snake_case name may hold "hf_"; and a digit in the body, so an identifier spelt like a prefix is no key.
_BODY = r"(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{16,}"
KNOWN_KEYS = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    rf"sk-(?:ant-|proj-)?{_BODY}"  # OpenAI, Anthropic
    rf"|sk_{_BODY}"  # ElevenLabs
    rf"|gh[pousr]_{_BODY}|github_pat_{_BODY}|glpat-{_BODY}"  # GitHub, GitLab
    rf"|xox[baprs]-{_BODY}|AIza{_BODY}|hf_{_BODY}|npm_{_BODY}|pypi-{_BODY}"
    rf"|tvly-(?:dev-|prod-)?{_BODY}|xai-{_BODY}|gsk_{_BODY}"
    r"|AKIA[0-9A-Z]{16}"  # AWS access key id
    r")")
CREDENTIALS: tuple[re.Pattern[str], ...] = (AUTH_TOKEN, KEY_PAIR, KNOWN_KEYS)
# For text that leaves for a third party (a gateway's error to its clients): any Authorization or x-api-key value
# however short, and any run of 40 base64-like characters — prose has no such words, and a lost word costs nothing
# there. Too eager for a journal or a chat, where a digest or a path must stay readable.
LOOSE: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+\S+"),
    re.compile(r"(?i)\bx-api-key\S*\s*[:=]\s*\S+"),
    re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}"),
)


def scrub_credentials(text: str, *, patterns: Iterable[re.Pattern[str]] = CREDENTIALS, mask: str = MASK) -> str:
    """Every match of patterns masked; a pattern's group `keep` (a scheme, a field's name) stays in front."""
    for pattern in patterns:
        if "keep" in pattern.groupindex:
            text = pattern.sub(lambda m: (m.group("keep") or "") + mask, text)
        else:
            text = pattern.sub(mask, text)
    return text


def scrub_text(text: str, keys: Iterable[str | None] = (), *, cut: int | None = None,
               patterns: Iterable[re.Pattern[str]] = CREDENTIALS, mask: str = MASK) -> str:
    """The recipe for a failure's text: the caller's own keys out (any length — the caller knows they are keys), then
    written-out credentials, then the cut."""
    for key in keys:
        if key:
            text = text.replace(key, mask)
    text = scrub_credentials(text, patterns=patterns, mask=mask)
    return text if cut is None else text[:cut]


class Redactor:
    """Known secret values out of text, then credentials by pattern.

    min_len: shorter values are not taken (they would blank ordinary words). head_chars: a value cut short somewhere
    before it got here (an error text cut to its length) still leaves its head, so any run of at least that many of
    its first characters is masked too, as far as it agrees with the value; 0 turns that off."""

    def __init__(self, values: Iterable[str] = (), *, min_len: int = 1, head_chars: int = 0,
                 patterns: Iterable[re.Pattern[str]] = CREDENTIALS, mask: str = MASK):
        # Longest first, so a password inside a connection string goes with the whole string, not half of it.
        self._values = sorted({v for v in values if v and len(v) >= min_len}, key=len, reverse=True)
        self._head = head_chars
        self._patterns = tuple(patterns)
        self._mask = mask

    @property
    def values(self) -> list[str]:
        return list(self._values)

    def text(self, text: str) -> str:
        mask = self._mask
        for value in self._values:
            text = text.replace(value, mask)
            if not self._head or len(value) <= self._head:
                continue
            head = value[:self._head]
            start = text.find(head)
            while start != -1:
                end = start + len(head)
                while end < len(text) and end - start < len(value) and text[end] == value[end - start]:
                    end += 1
                text = text[:start] + mask + text[end:]
                start = text.find(head, start + len(mask))
        return scrub_credentials(text, patterns=self._patterns, mask=mask)

    scrub = text

    def data(self, value: Any) -> Any:
        """Every string of a structure, dict keys included; the structure as it is."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self.text(k) if isinstance(k, str) else k: self.data(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.data(item) for item in value]
        return value


def env_values(path: Path, *, min_len: int = 1) -> set[str]:
    """The values of a KEY=value file (quotes taken off), at least min_len long; none when it cannot be read."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if value and len(value) >= min_len:
            found.add(value)
    return found
