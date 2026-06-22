"""Tests for headless IMAP/Graph draft creation."""

from __future__ import annotations

from email import message_from_bytes
from email.policy import default as default_policy

import pytest

from macbot.mail_imap import _addr_list, _build_draft_message
from macbot.tasks.mail_imap import MailImapCreateDraftTask


def test_addr_list_normalizes_inputs() -> None:
    assert _addr_list(None) == []
    assert _addr_list("a@x.com") == ["a@x.com"]
    assert _addr_list("a@x.com, b@y.com; c@z.com") == ["a@x.com", "b@y.com", "c@z.com"]
    assert _addr_list(["a@x.com", " b@y.com "]) == ["a@x.com", "b@y.com"]
    assert _addr_list("  ,  ") == []


def test_build_draft_plain_text_headers() -> None:
    msg = _build_draft_message(
        from_addr="me@example.com",
        to="to@example.com, two@example.com",
        subject="Hello",
        body="Body text",
        cc="cc@example.com",
    )
    parsed = message_from_bytes(msg.as_bytes(), policy=default_policy)
    assert parsed["From"] == "me@example.com"
    assert parsed["To"] == "to@example.com, two@example.com"
    assert parsed["Cc"] == "cc@example.com"
    assert parsed["Subject"] == "Hello"
    assert parsed["Message-ID"]
    assert parsed.get_body(preferencelist=("plain",)).get_content().strip() == "Body text"


def test_build_draft_html_keeps_text_alternative() -> None:
    msg = _build_draft_message(
        from_addr="me@example.com",
        to="to@example.com",
        subject="Rich",
        body="<p>Hi <b>there</b></p>",
        html=True,
    )
    parsed = message_from_bytes(msg.as_bytes(), policy=default_policy)
    assert parsed.get_body(preferencelist=("html",)).get_content().strip() == "<p>Hi <b>there</b></p>"
    text = parsed.get_body(preferencelist=("plain",)).get_content()
    assert "Hi" in text and "<p>" not in text


def test_build_draft_with_attachment(tmp_path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("file contents")
    msg = _build_draft_message(
        from_addr="me@example.com",
        to="to@example.com",
        subject="With file",
        body="see attached",
        attachments=[str(f)],
    )
    parsed = message_from_bytes(msg.as_bytes(), policy=default_policy)
    names = [a.get_filename() for a in parsed.iter_attachments()]
    assert names == ["note.txt"]


def test_build_draft_missing_attachment_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        _build_draft_message(
            from_addr="me@example.com",
            to="to@example.com",
            subject="x",
            body="y",
            attachments=[str(tmp_path / "nope.txt")],
        )


@pytest.mark.asyncio
async def test_create_draft_task_dispatches_to_client(monkeypatch) -> None:
    import macbot.mail_imap as mail_imap

    calls: dict[str, object] = {}

    class FakeClient:
        def __init__(self, email: str) -> None:
            calls["email"] = email

        def create_draft(self, to, subject, body, cc, bcc, attachments, html):  # noqa: ANN001
            calls["args"] = (to, subject, body, cc, bcc, attachments, html)
            return {"ok": True, "folder": "Drafts", "to": [to], "subject": subject}

    monkeypatch.setattr(mail_imap, "resolve_account", lambda email: "me@example.com")
    monkeypatch.setattr(mail_imap, "MailImapClient", FakeClient)

    task = MailImapCreateDraftTask()
    result = await task.execute(
        to="x@example.com",
        subject="Hi",
        body="Body",
        cc="c@example.com",
        attachments=["/tmp/a.pdf"],
    )
    assert result["success"] is True
    assert result["email"] == "me@example.com"
    assert calls["args"] == ("x@example.com", "Hi", "Body", "c@example.com", None, ["/tmp/a.pdf"], False)


@pytest.mark.asyncio
async def test_create_draft_task_reports_missing_file(monkeypatch) -> None:
    import macbot.mail_imap as mail_imap

    class FakeClient:
        def __init__(self, email: str) -> None:
            pass

        def create_draft(self, *a, **k):  # noqa: ANN002, ANN003
            raise FileNotFoundError("Attachment not found: /tmp/missing.pdf")

    monkeypatch.setattr(mail_imap, "resolve_account", lambda email: "me@example.com")
    monkeypatch.setattr(mail_imap, "MailImapClient", FakeClient)

    task = MailImapCreateDraftTask()
    result = await task.execute(to="x@example.com", attachments=["/tmp/missing.pdf"])
    assert result["success"] is False
    assert "Attachment not found" in result["error"]
