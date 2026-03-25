import logging

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class SummarizerService:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.summary_model
        self._system_prompt = (
            "あなたは優秀な会議アシスタントです。"
            "提供された会議の文字起こしを分析して、構造化されたサマリーを作成してください。"
            "以下のフォーマットで出力してください：\n\n"
            "## 会議サマリー\n\n"
            "### 議題・トピック\n\n"
            "### 決定事項\n\n"
            "### アクションアイテム\n\n"
            "### その他の重要ポイント"
        )

    async def summarize(self, transcripts: list[dict], meeting_name: str) -> str:
        """Generate a structured meeting summary from transcripts."""
        if not transcripts:
            return "## 会議サマリー\n\n文字起こしデータがありません。"

        transcript_text = "\n".join(
            f"[{self._format_timestamp(t['timestamp_seconds'])}] "
            f"(原文) {t['original_text']}\n"
            f"(翻訳) {t['translated_text']}"
            for t in transcripts
        )

        user_content = (
            f"会議名: {meeting_name}\n\n"
            f"文字起こし:\n{transcript_text}"
        )

        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=self._system_prompt,
                messages=[
                    {"role": "user", "content": user_content},
                ],
            )
            return message.content[0].text.strip()
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            return f"## 会議サマリー\n\nサマリーの生成中にエラーが発生しました: {str(e)}"

    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds into MM:SS string."""
        total_seconds = int(seconds)
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"
