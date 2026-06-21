"""Tests for the Codex -> LiteLLM ChatGPT auth bridge."""

import base64
import json
import os
from pathlib import Path

import pytest

from macbot.providers import chatgpt_auth


def _jwt_with_account(account_id: str) -> str:
    """Build a minimal unsigned JWT carrying a chatgpt_account_id claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHATGPT_TOKEN_DIR", raising=False)
    monkeypatch.delenv("CHATGPT_AUTH_FILE", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)


class TestFlatten:
    def test_flattens_nested_tokens(self) -> None:
        codex = {
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": "id",
                "access_token": "access",
                "refresh_token": "refresh",
                "account_id": "acct-123",
            },
            "last_refresh": "2026-01-01T00:00:00Z",
        }
        flat = chatgpt_auth._flatten(codex)
        assert flat == {
            "id_token": "id",
            "access_token": "access",
            "refresh_token": "refresh",
            "account_id": "acct-123",
        }

    def test_derives_account_id_from_id_token(self) -> None:
        codex = {"tokens": {"access_token": "a", "id_token": _jwt_with_account("acct-xyz")}}
        flat = chatgpt_auth._flatten(codex)
        assert flat["account_id"] == "acct-xyz"

    def test_accepts_already_flat_input(self) -> None:
        flat = chatgpt_auth._flatten({"access_token": "a", "refresh_token": "r"})
        assert flat["access_token"] == "a"
        assert flat["refresh_token"] == "r"


class TestSync:
    def test_sync_creates_flat_file_and_sets_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        (codex_home / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "tok", "refresh_token": "r", "account_id": "acct"}})
        )
        token_dir = tmp_path / "macbot-chatgpt"
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        monkeypatch.setattr(chatgpt_auth, "macbot_token_dir", lambda: token_dir)

        assert chatgpt_auth.sync_codex_auth() is True

        target = token_dir / "auth.json"
        assert target.exists()
        assert json.loads(target.read_text())["access_token"] == "tok"
        assert os.environ["CHATGPT_TOKEN_DIR"] == str(token_dir)
        assert os.environ["CHATGPT_AUTH_FILE"] == "auth.json"
        # File is written with owner-only permissions.
        assert (target.stat().st_mode & 0o777) == 0o600

    def test_sync_returns_false_without_codex(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
        monkeypatch.setattr(chatgpt_auth, "macbot_token_dir", lambda: tmp_path / "out")
        assert chatgpt_auth.sync_codex_auth() is False
        assert "CHATGPT_TOKEN_DIR" not in os.environ

    def test_does_not_clobber_newer_macbot_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        codex_auth = codex_home / "auth.json"
        codex_auth.write_text(json.dumps({"tokens": {"access_token": "old"}}))
        token_dir = tmp_path / "macbot-chatgpt"
        token_dir.mkdir()
        target = token_dir / "auth.json"
        # LiteLLM already refreshed: macbot copy is newer and has a rotated token.
        target.write_text(json.dumps({"access_token": "refreshed"}))
        os.utime(codex_auth, (1000, 1000))
        os.utime(target, (2000, 2000))
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        monkeypatch.setattr(chatgpt_auth, "macbot_token_dir", lambda: token_dir)

        assert chatgpt_auth.sync_codex_auth() is True
        assert json.loads(target.read_text())["access_token"] == "refreshed"

    def test_resyncs_when_codex_newer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        codex_auth = codex_home / "auth.json"
        codex_auth.write_text(json.dumps({"tokens": {"access_token": "relogin"}}))
        token_dir = tmp_path / "macbot-chatgpt"
        token_dir.mkdir()
        target = token_dir / "auth.json"
        target.write_text(json.dumps({"access_token": "stale"}))
        # User re-logged in with Codex: its file is newer.
        os.utime(target, (1000, 1000))
        os.utime(codex_auth, (2000, 2000))
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
        monkeypatch.setattr(chatgpt_auth, "macbot_token_dir", lambda: token_dir)

        assert chatgpt_auth.sync_codex_auth() is True
        assert json.loads(target.read_text())["access_token"] == "relogin"

    def test_respects_explicit_token_dir_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_dir = tmp_path / "user-tokens"
        user_dir.mkdir()
        (user_dir / "auth.json").write_text(json.dumps({"access_token": "user"}))
        monkeypatch.setenv("CHATGPT_TOKEN_DIR", str(user_dir))
        # Even if Codex creds exist, the explicit override wins and is untouched.
        called = []
        monkeypatch.setattr(chatgpt_auth, "find_codex_auth", lambda: called.append(1))
        assert chatgpt_auth.sync_codex_auth() is True
        assert not called
