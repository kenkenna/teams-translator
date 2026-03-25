"""Unit tests for SummarizerService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.summarizer import SummarizerService


def make_summarizer(summary_text: str = "## 会議サマリー\n\n内容") -> SummarizerService:
    """Create a SummarizerService with a mocked Anthropic client."""
    with patch("app.services.summarizer.anthropic.AsyncAnthropic"):
        svc = SummarizerService()

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=f"  {summary_text}  ")]
    svc._client = MagicMock()
    svc._client.messages.create = AsyncMock(return_value=mock_message)
    return svc


SAMPLE_TRANSCRIPTS = [
    {"timestamp_seconds": 0.0, "original_text": "Hello", "translated_text": "こんにちは"},
    {"timestamp_seconds": 65.0, "original_text": "Goodbye", "translated_text": "さようなら"},
]


class TestFormatTimestamp:
    def test_zero(self):
        svc = make_summarizer()
        assert svc._format_timestamp(0) == "00:00"

    def test_seconds_only(self):
        svc = make_summarizer()
        assert svc._format_timestamp(45) == "00:45"

    def test_one_minute(self):
        svc = make_summarizer()
        assert svc._format_timestamp(60) == "01:00"

    def test_minutes_and_seconds(self):
        svc = make_summarizer()
        assert svc._format_timestamp(65) == "01:05"

    def test_two_digit_minutes(self):
        svc = make_summarizer()
        assert svc._format_timestamp(3661) == "61:01"


class TestSummarize:
    @pytest.mark.asyncio
    async def test_empty_transcripts_returns_default(self):
        svc = make_summarizer()
        result = await svc.summarize([], "テスト会議")
        svc._client.messages.create.assert_not_called()
        assert "文字起こしデータがありません" in result

    @pytest.mark.asyncio
    async def test_returns_summary_text(self):
        svc = make_summarizer("## 会議サマリー\n\n議題: テスト")
        result = await svc.summarize(SAMPLE_TRANSCRIPTS, "週次MTG")
        assert result == "## 会議サマリー\n\n議題: テスト"

    @pytest.mark.asyncio
    async def test_includes_meeting_name_in_prompt(self):
        svc = make_summarizer()
        await svc.summarize(SAMPLE_TRANSCRIPTS, "重要な会議")
        call_args = svc._client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "重要な会議" in user_content

    @pytest.mark.asyncio
    async def test_includes_timestamps_in_prompt(self):
        svc = make_summarizer()
        await svc.summarize(SAMPLE_TRANSCRIPTS, "MTG")
        call_args = svc._client.messages.create.call_args
        user_content = call_args.kwargs["messages"][0]["content"]
        assert "00:00" in user_content
        assert "01:05" in user_content

    @pytest.mark.asyncio
    async def test_api_error_returns_error_message(self):
        with patch("app.services.summarizer.anthropic.AsyncAnthropic"):
            svc = SummarizerService()
        svc._client = MagicMock()
        svc._client.messages.create = AsyncMock(side_effect=Exception("network error"))

        result = await svc.summarize(SAMPLE_TRANSCRIPTS, "MTG")
        assert "エラー" in result
