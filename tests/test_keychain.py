"""Tests for macOS Keychain integration."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from macbot.core.keychain import (
    ACCOUNT_MAP,
    SERVICE_NAME,
    delete_keychain,
    get_key_source,
    get_keychain,
    set_keychain,
)


class TestGetKeychain:
    """Tests for get_keychain()."""

    @patch("macbot.core.keychain.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="sk-ant-test123\n")
        result = get_keychain("anthropic_api_key")
        assert result == "sk-ant-test123"
        mock_run.assert_called_once_with(
            ["security", "find-generic-password", "-a", "anthropic_api_key", "-s", SERVICE_NAME, "-w"],
            capture_output=True, text=True, timeout=5,
        )

    @patch("macbot.core.keychain.subprocess.run")
    def test_not_found_rc44(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=44, stdout="")
        result = get_keychain("anthropic_api_key")
        assert result is None

    @patch("macbot.core.keychain.subprocess.run")
    def test_other_error_code(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        result = get_keychain("anthropic_api_key")
        assert result is None

    @patch("macbot.core.keychain.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_binary(self, mock_run: MagicMock) -> None:
        result = get_keychain("anthropic_api_key")
        assert result is None

    @patch("macbot.core.keychain.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="security", timeout=5))
    def test_timeout(self, mock_run: MagicMock) -> None:
        result = get_keychain("anthropic_api_key")
        assert result is None

    @patch("macbot.core.keychain.subprocess.run", side_effect=OSError("disk error"))
    def test_os_error(self, mock_run: MagicMock) -> None:
        result = get_keychain("anthropic_api_key")
        assert result is None


class TestSetKeychain:
    """Tests for set_keychain()."""

    @patch("macbot.core.keychain.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = set_keychain("anthropic_api_key", "sk-ant-test123")
        assert result is True
        mock_run.assert_called_once_with(
            [
                "security", "add-generic-password",
                "-a", "anthropic_api_key",
                "-s", SERVICE_NAME,
                "-w", "sk-ant-test123",
                "-U",
            ],
            capture_output=True, text=True, timeout=5,
        )

    @patch("macbot.core.keychain.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1)
        result = set_keychain("anthropic_api_key", "sk-ant-test123")
        assert result is False

    @patch("macbot.core.keychain.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_binary(self, mock_run: MagicMock) -> None:
        result = set_keychain("anthropic_api_key", "sk-ant-test123")
        assert result is False

    @patch("macbot.core.keychain.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="security", timeout=5))
    def test_timeout(self, mock_run: MagicMock) -> None:
        result = set_keychain("anthropic_api_key", "sk-ant-test123")
        assert result is False


class TestDeleteKeychain:
    """Tests for delete_keychain()."""

    @patch("macbot.core.keychain.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        result = delete_keychain("anthropic_api_key")
        assert result is True

    @patch("macbot.core.keychain.subprocess.run")
    def test_not_found(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=44)
        result = delete_keychain("anthropic_api_key")
        assert result is False

    @patch("macbot.core.keychain.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_binary(self, mock_run: MagicMock) -> None:
        result = delete_keychain("anthropic_api_key")
        assert result is False


class TestGetKeySource:
    """Tests for get_key_source() priority."""

    @patch("macbot.core.keychain.get_keychain")
    def test_keychain_wins(self, mock_get: MagicMock) -> None:
        """Keychain takes priority over env."""
        mock_get.return_value = "kc-value"
        result = get_key_source("anthropic_api_key", "env-value")
        assert result == "keychain"

    @patch("macbot.core.keychain.get_keychain")
    def test_env_fallback(self, mock_get: MagicMock) -> None:
        """Falls back to env when Keychain has nothing."""
        mock_get.return_value = None
        result = get_key_source("anthropic_api_key", "env-value")
        assert result == "env"

    @patch("macbot.core.keychain.get_keychain")
    def test_none_when_both_empty(self, mock_get: MagicMock) -> None:
        """Returns 'none' when neither source has a key."""
        mock_get.return_value = None
        result = get_key_source("anthropic_api_key", "")
        assert result == "none"

    @patch("macbot.core.keychain.get_keychain", side_effect=Exception("boom"))
    def test_keychain_exception_falls_to_env(self, mock_get: MagicMock) -> None:
        """If Keychain raises, falls back to env."""
        result = get_key_source("anthropic_api_key", "env-value")
        assert result == "env"


class TestAccountMap:
    """Tests for ACCOUNT_MAP constants."""

    def test_known_providers(self) -> None:
        assert "anthropic" in ACCOUNT_MAP
        assert "openai" in ACCOUNT_MAP
        assert "openrouter" in ACCOUNT_MAP
        assert "paperless" in ACCOUNT_MAP
        assert "telegram" in ACCOUNT_MAP
