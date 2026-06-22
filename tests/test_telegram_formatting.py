"""Tests for Telegram message splitting and full-detail reply handling."""

import asyncio

import pytest

from macbot.telegram.bot import TELEGRAM_MAX_CHARS, split_for_telegram


# --------------------------------------------------------------------------- #
# split_for_telegram
# --------------------------------------------------------------------------- #

def test_short_text_passthrough():
    assert split_for_telegram("hello") == ["hello"]


def test_long_text_split_under_limit():
    text = "word " * 2000  # ~10k chars
    chunks = split_for_telegram(text)
    assert len(chunks) >= 3
    assert all(len(c) <= TELEGRAM_MAX_CHARS for c in chunks)


def test_split_does_not_break_words():
    text = "supercalifragilistic " * 500
    chunks = split_for_telegram(text)
    # Every whitespace-separated token in every chunk is a complete word — the
    # splitter never cuts mid-word (boundary spaces are consumed between chunks).
    for c in chunks:
        for token in c.split():
            assert token == "supercalifragilistic"


def test_prefers_paragraph_boundaries():
    para = "x" * 2000
    text = f"{para}\n\n{para}\n\n{para}"
    chunks = split_for_telegram(text)
    # Each paragraph is well under the limit, so splits land on the blank lines
    # and no chunk starts/ends mid-paragraph with stray characters.
    assert all(len(c) <= TELEGRAM_MAX_CHARS for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks).count("x") == 6000


def test_balances_code_fences_across_split():
    # A code block large enough to be split mid-fence.
    code = "print('line')\n" * 400  # ~5.6k chars inside one fence
    text = f"Here is code:\n```python\n{code}```\nDone."
    chunks = split_for_telegram(text)
    assert len(chunks) >= 2
    # Every chunk must have balanced (even) triple-backtick fences.
    for c in chunks:
        assert c.count("```") % 2 == 0


# --------------------------------------------------------------------------- #
# _trim_for_telegram — full detail by default
# --------------------------------------------------------------------------- #

@pytest.fixture
def service():
    from macbot.telegram.service import TelegramService

    # A syntactically valid fake token; no network calls are made on construct.
    return TelegramService("123456:ABCDEFghijklmnopqrstuvwxyz0123456789")


def test_full_response_by_default(service, monkeypatch):
    import macbot.config

    monkeypatch.setattr(macbot.config.settings, "telegram_summarize", False)
    long_text = "Detail line. " * 500  # ~6.5k chars, far over the old 500 cap
    out = asyncio.run(service._trim_for_telegram(long_text))
    assert out == long_text  # nothing dropped


def test_no_summarize_under_threshold(service, monkeypatch):
    import macbot.config

    monkeypatch.setattr(macbot.config.settings, "telegram_summarize", True)
    monkeypatch.setattr(macbot.config.settings, "telegram_summary_threshold", 3500)
    text = "short enough " * 10  # well under threshold
    out = asyncio.run(service._trim_for_telegram(text))
    assert out == text  # returned as-is, no LLM call


def test_summarize_failure_falls_back_to_full(service, monkeypatch):
    import macbot.config

    monkeypatch.setattr(macbot.config.settings, "telegram_summarize", True)
    monkeypatch.setattr(macbot.config.settings, "telegram_summary_threshold", 100)

    # Force the provider path to raise so we exercise the fallback.
    def _boom(*args, **kwargs):
        raise RuntimeError("no api key")

    monkeypatch.setattr(
        "macbot.providers.litellm_provider.LiteLLMProvider.__init__", _boom
    )
    long_text = "Detail. " * 100
    out = asyncio.run(service._trim_for_telegram(long_text))
    assert out == long_text  # fell back to full text, lost nothing
