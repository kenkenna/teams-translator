"""Unit tests for TranslatorService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.translator import TranslatorService


def make_translator(translated_text: str = "翻訳結果") -> TranslatorService:
    """Create a TranslatorService with a mocked Anthropic client."""
    with patch("app.services.translator.anthropic.AsyncAnthropic"):
        svc = TranslatorService()

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=f"  {translated_text}  ")]
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(return_value=mock_message)
    return svc


class TestTranslate:
    @pytest.mark.asyncio
    async def test_returns_translated_text(self):
        svc = make_translator("こんにちは")
        result = await svc.translate("Hello")
        assert result == "こんにちは"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_result(self):
        svc = make_translator("  スペースあり  ")
        result = await svc.translate("Hello")
        assert result == "スペースあり"

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty_without_api_call(self):
        svc = make_translator()
        result = await svc.translate("")
        svc._client.messages.create.assert_not_called()
        assert result == ""

    @pytest.mark.asyncio
    async def test_whitespace_only_returns_empty_without_api_call(self):
        svc = make_translator()
        result = await svc.translate("   ")
        svc._client.messages.create.assert_not_called()
        assert result == ""

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_string(self):
        with patch("app.services.translator.anthropic.AsyncAnthropic"):
            svc = TranslatorService()
        svc._client = MagicMock()
        svc._client.messages.create = AsyncMock(side_effect=Exception("API error"))

        result = await svc.translate("Hello")
        assert result == ""

    @pytest.mark.asyncio
    async def test_strips_input_before_sending(self):
        svc = make_translator("テスト")
        await svc.translate("  Hello  ")
        call_args = svc._client.messages.create.call_args
        messages = call_args.kwargs["messages"]
        assert messages[0]["content"] == "Hello"
