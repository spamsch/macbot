"""Tests for Paperless-ngx tasks.

Focus: the partial-update semantics of paperless_update_document, which used to
clobber metadata when the LLM filled unused optional params with empty placeholders
(title="", custom_fields=[]), and choked on custom_fields passed as a list of JSON
strings (HTTP 400).
"""

from __future__ import annotations

from typing import Any

import pytest

import macbot.tasks.paperless as pl
from macbot.tasks.paperless import (
    PaperlessUpdateDocumentTask,
    _blank_to_none,
    _normalize_custom_fields,
)


def test_blank_to_none() -> None:
    assert _blank_to_none("") is None
    assert _blank_to_none("   ") is None
    assert _blank_to_none(None) is None
    assert _blank_to_none("title") == "title"
    assert _blank_to_none(0) == 0  # non-strings pass through unchanged
    assert _blank_to_none([]) == []


def test_normalize_custom_fields_shapes() -> None:
    # list of JSON strings — the shape that produced HTTP 400 before
    assert _normalize_custom_fields(['{"field":1,"value":"USD222.12"}']) == [
        {"field": 1, "value": "USD222.12"}
    ]
    # list of dicts
    assert _normalize_custom_fields([{"field": 1, "value": "EUR9.99"}]) == [
        {"field": 1, "value": "EUR9.99"}
    ]
    # whole value as a JSON string holding a list
    assert _normalize_custom_fields('[{"field": 1, "value": "X"}]') == [
        {"field": 1, "value": "X"}
    ]
    # single dict gets wrapped
    assert _normalize_custom_fields({"field": 1, "value": "Y"}) == [
        {"field": 1, "value": "Y"}
    ]
    # numeric field id passed as string is coerced
    assert _normalize_custom_fields([{"field": "3", "value": "Z"}]) == [
        {"field": 3, "value": "Z"}
    ]
    # empty string -> empty list (handled separately as "unchanged" by execute)
    assert _normalize_custom_fields("") == []


def test_normalize_custom_fields_rejects_garbage() -> None:
    assert _normalize_custom_fields(["not json at all"]) is None
    assert _normalize_custom_fields("{not valid json") is None
    assert _normalize_custom_fields([{"value": "no field key"}]) is None
    assert _normalize_custom_fields([{"field": "abc", "value": "x"}]) is None


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _CapturingClient:
    """Minimal async httpx.AsyncClient stand-in that records the PATCH body."""

    captured: dict[str, Any] | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _CapturingClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def patch(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _FakeResponse:  # noqa: A002
        _CapturingClient.captured = json
        # Echo back a plausible document body
        return _FakeResponse({"id": 1388, **json})


@pytest.fixture
def capture_patch(monkeypatch: pytest.MonkeyPatch) -> type[_CapturingClient]:
    _CapturingClient.captured = None
    monkeypatch.setattr(pl.settings, "paperless_url", "http://localhost:8099", raising=False)
    monkeypatch.setattr(pl.settings, "paperless_api_token", "test-token", raising=False)
    monkeypatch.setattr(pl.httpx, "AsyncClient", _CapturingClient)

    # Resolvers would hit the network; make them deterministic.
    async def _fake_resolve_resource(value: Any, endpoint: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            v = value.strip().strip('"').strip("'")
            return int(v) if v.isdigit() else None
        return None

    async def _fake_resolve_tags(tags: Any) -> list[int]:
        items = tags if isinstance(tags, list) else [tags]
        return [t for t in items if isinstance(t, int)]

    monkeypatch.setattr(pl, "_resolve_resource", _fake_resolve_resource)
    monkeypatch.setattr(pl, "_resolve_tags", _fake_resolve_tags)
    return _CapturingClient


@pytest.mark.asyncio
async def test_empty_placeholders_do_not_clobber(capture_patch: type[_CapturingClient]) -> None:
    """The exact destructive call from the bug report must touch nothing but created."""
    result = await PaperlessUpdateDocumentTask().execute(
        document_id=1388,
        title="",
        created="2026-06-18",
        tags=[],
        correspondent="",
        document_type="",
        custom_fields=[],
    )
    assert result["success"] is True
    sent = capture_patch.captured
    assert sent == {"created": "2026-06-18"}
    # The fields the LLM left empty must be absent from the PATCH body.
    assert "title" not in sent
    assert "tags" not in sent
    assert "custom_fields" not in sent
    assert "correspondent" not in sent
    assert "document_type" not in sent


@pytest.mark.asyncio
async def test_custom_fields_list_of_json_strings(capture_patch: type[_CapturingClient]) -> None:
    await PaperlessUpdateDocumentTask().execute(
        document_id=1388,
        custom_fields=['{"field":1,"value":"USD222.12"}'],
    )
    assert capture_patch.captured == {
        "custom_fields": [{"field": 1, "value": "USD222.12"}]
    }


@pytest.mark.asyncio
async def test_clear_flags_are_explicit(capture_patch: type[_CapturingClient]) -> None:
    await PaperlessUpdateDocumentTask().execute(
        document_id=1388, clear_tags=True, clear_custom_fields=True
    )
    assert capture_patch.captured == {"tags": [], "custom_fields": []}


@pytest.mark.asyncio
async def test_bad_custom_fields_returns_error(capture_patch: type[_CapturingClient]) -> None:
    result = await PaperlessUpdateDocumentTask().execute(
        document_id=1388, custom_fields=["totally not json"]
    )
    assert result["success"] is False
    assert "custom_fields" in result["error"]
    # Nothing should have been sent.
    assert capture_patch.captured is None


@pytest.mark.asyncio
async def test_no_fields_to_update(capture_patch: type[_CapturingClient]) -> None:
    result = await PaperlessUpdateDocumentTask().execute(document_id=1388, title="  ")
    assert result["success"] is False
    assert "No fields" in result["error"]
    assert capture_patch.captured is None
