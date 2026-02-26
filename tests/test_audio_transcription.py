"""Tests for audio transcription in MacbotService."""

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from macbot.service import MacbotService


@pytest.fixture
def service():
    """Create a MacbotService instance with mocked internals."""
    with patch("macbot.service.create_default_registry"), \
         patch("macbot.service.Agent"):
        return MacbotService()


class TestTranscribeAudio:
    """Tests for _transcribe_audio()."""

    @pytest.mark.asyncio
    async def test_transcribe_audio_success(self, service: MacbotService) -> None:
        """Test successful audio transcription."""
        audio_data = b"fake-audio-data"
        audio_b64 = base64.b64encode(audio_data).decode()

        mock_transcript = MagicMock()
        mock_transcript.text = "Hello, world!"

        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value=mock_transcript)

        with patch("macbot.service.settings") as mock_settings, \
             patch("macbot.service.Path.unlink"), \
             patch("openai.AsyncOpenAI", return_value=mock_client):
            mock_settings.openai_api_key = "sk-test-key"

            result = await service._transcribe_audio(audio_b64, "webm")

        assert result == "Hello, world!"
        mock_client.audio.transcriptions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_audio_no_api_key(self, service: MacbotService) -> None:
        """Test that missing API key raises ValueError."""
        audio_b64 = base64.b64encode(b"data").decode()

        with patch("macbot.service.settings") as mock_settings:
            mock_settings.openai_api_key = ""

            with pytest.raises(ValueError, match="OpenAI API key not configured"):
                await service._transcribe_audio(audio_b64, "webm")
