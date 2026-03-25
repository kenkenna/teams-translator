import logging

import anthropic

from app.core.config import settings

logger = logging.getLogger(__name__)


class TranslatorService:
    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.translation_model
        self._system_prompt = (
            "You are a professional interpreter. "
            "Translate the following English speech to natural Japanese. "
            "Output only the Japanese translation, nothing else."
        )

    async def translate(self, text: str) -> str:
        """Translate English text to Japanese."""
        if not text or not text.strip():
            return ""

        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=self._system_prompt,
                messages=[
                    {"role": "user", "content": text.strip()},
                ],
            )
            translated = message.content[0].text.strip()
            return translated
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return ""
