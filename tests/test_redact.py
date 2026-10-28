"""X2-19: one mask, one recipe (keys out, credentials masked, then the cut), thresholds as parameters."""

import pytest

from agentkit.redact import CREDENTIALS, LOOSE, MASK, Redactor, env_values, scrub_credentials, scrub_text

TOKEN = "abcDEF0123456789xyz"


@pytest.mark.parametrize("text, expected", [
    (f"Authorization: Bearer {TOKEN}", f"Authorization: Bearer {MASK}"),
    (f"basic {TOKEN}", f"basic {MASK}"),
    (f'{{"x-api-key": "{TOKEN}"}}', f'{{"x-api-key": "{MASK}"}}'),
    (f"?api_key={TOKEN}&q=1", f"?api_key={MASK}&q=1"),
    (f"access-token: {TOKEN}", f"access-token: {MASK}"),
    ("ghp_" + "a1" * 18, MASK),
    ("token github_pat_11ABCDEFG0123456789_abcdef", f"token {MASK}"),
    ("sk-ant-api03-" + "x9" * 20, MASK),
    ("sk-proj-" + "Q1" * 12, MASK),
    ("key AKIAIOSFODNN7EXAMPLE here", f"key {MASK} here"),
    ("tvly-dev-0123456789abcdefSECRET", MASK),
])
def test_written_out_credentials_are_masked(text, expected):
    assert scrub_credentials(text) == expected


@pytest.mark.parametrize("prose", [
    "send Authorization: Bearer $KEY",
    "basic authentication/authorization",
    "the bearer of the key",
    "task-reminders-board-2026",  # holds "sk-" inside a word
    "a snake_case hf_model_name_without_digits",
    "sha256 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
])
def test_prose_and_digests_are_left_alone(prose):
    assert scrub_credentials(prose) == prose


def test_loose_patterns_take_any_bearer_and_long_runs_for_third_parties():
    text = "Bearer short and " + "A" * 40 + " and sk-abcdefgh9"
    assert scrub_credentials(text, patterns=(*CREDENTIALS, *LOOSE)) == f"{MASK} and {MASK} and {MASK}"
    assert scrub_credentials("Bearer short") == "Bearer short"


def test_scrub_text_takes_the_keys_out_before_the_cut():
    key = "k" * 30
    text = f"refused: {key} and more"
    assert scrub_text(text, [key, None, ""]) == f"refused: {MASK} and more"
    # A cut through the key would leave its head; masked first, the cut cannot.
    assert scrub_text(text, [key], cut=20) == f"refused: {MASK} an"[:20]
    assert key[:5] not in scrub_text(text, [key], cut=20)
    assert scrub_text(f"x {TOKEN}", (), cut=None, mask="[m]") == f"x {TOKEN}"
    assert scrub_text(f"Bearer {TOKEN}", (), mask="[m]") == "Bearer [m]"


@pytest.mark.parametrize("min_len, kept", [(1, False), (4, False), (6, True), (16, True)])
def test_redactor_threshold_is_a_parameter(min_len, kept):
    text = Redactor(["admin"], min_len=min_len).text("user admin logged in")
    assert ("admin" in text) is kept


def test_redactor_longest_first_and_heads_of_cut_values():
    secret = "S3cretValueThatIsLong0123"
    redactor = Redactor([secret, secret[:8]], min_len=8, head_chars=12)
    assert redactor.values[0] == secret
    assert redactor.text(f"a {secret} b") == f"a {MASK} b"
    # Cut somewhere before it got here: its head is still masked, as far as it agrees with the secret.
    cut = secret[:15]
    assert redactor.text(f"error: {cut}…") == f"error: {MASK}…"
    without_heads = Redactor([secret], min_len=8)
    assert without_heads.text(f"error: {secret[:15]}") == f"error: {secret[:15]}"


def test_redactor_data_walks_a_structure_keys_included():
    secret = "S3cretValueThatIsLong0123"
    redactor = Redactor([secret], min_len=16)
    data = {"a": [secret, 1, {secret: None}], "n": 2}
    assert redactor.data(data) == {"a": [MASK, 1, {MASK: None}], "n": 2}
    assert redactor.scrub(secret) == MASK


def test_env_values(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text("# comment\nA=one\nB='quoted value'\nC=\"x\"\nD\nE=on\n")
    assert env_values(path, min_len=3) == {"one", "quoted value"}
    assert env_values(tmp_path / "missing.env") == set()
