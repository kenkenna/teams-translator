import asyncio
import io
import logging
import struct
import wave
from functools import partial
from typing import Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    def __init__(self) -> None:
        self._realtime_model = None
        self._batch_model = None

    def _load_realtime_model(self):
        if self._realtime_model is None:
            try:
                from faster_whisper import WhisperModel
                self._realtime_model = WhisperModel(
                    settings.whisper_realtime_model,
                    device="cpu",
                    compute_type="int8",
                )
                logger.info(f"Realtime Whisper model loaded: {settings.whisper_realtime_model}")
            except Exception as e:
                logger.error(f"Failed to load realtime Whisper model: {e}")
                raise
        return self._realtime_model

    def _load_batch_model(self):
        if self._batch_model is None:
            try:
                from faster_whisper import WhisperModel
                self._batch_model = WhisperModel(
                    settings.whisper_batch_model,
                    device="cpu",
                    compute_type="int8",
                )
                logger.info(f"Batch Whisper model loaded: {settings.whisper_batch_model}")
            except Exception as e:
                logger.error(f"Failed to load batch Whisper model: {e}")
                raise
        return self._batch_model

    def _pcm_bytes_to_float32(self, audio_bytes: bytes) -> np.ndarray:
        """Convert raw int16 PCM bytes to float32 numpy array."""
        num_samples = len(audio_bytes) // 2
        samples = struct.unpack(f"<{num_samples}h", audio_bytes)
        audio_array = np.array(samples, dtype=np.float32) / 32768.0
        return audio_array

    def _is_silence(self, audio_array: np.ndarray, threshold: float = 0.01) -> bool:
        """Check if audio chunk is silence/noise."""
        rms = np.sqrt(np.mean(audio_array ** 2))
        return rms < threshold

    def _transcribe_chunk_sync(self, audio_bytes: bytes) -> str:
        """Synchronous transcription for real-time use."""
        try:
            audio_array = self._pcm_bytes_to_float32(audio_bytes)

            if self._is_silence(audio_array):
                return ""

            model = self._load_realtime_model()
            segments, info = model.transcribe(
                audio_array,
                language="en",
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )

            texts = []
            for segment in segments:
                text = segment.text.strip()
                if text and text not in ("[BLANK_AUDIO]", "(silence)", "[Music]", "(Music)"):
                    texts.append(text)

            return " ".join(texts)
        except Exception as e:
            logger.error(f"Error transcribing chunk: {e}")
            return ""

    def _transcribe_file_sync(self, file_path: str) -> list[dict]:
        """Synchronous transcription for batch processing."""
        try:
            model = self._load_batch_model()
            segments, info = model.transcribe(
                file_path,
                language="en",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )

            results = []
            for segment in segments:
                text = segment.text.strip()
                if text and text not in ("[BLANK_AUDIO]", "(silence)", "[Music]", "(Music)"):
                    results.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": text,
                    })

            return results
        except Exception as e:
            logger.error(f"Error transcribing file {file_path}: {e}")
            return []

    async def transcribe_chunk(self, audio_bytes: bytes) -> str:
        """Transcribe a raw PCM audio chunk asynchronously."""
        if len(audio_bytes) < 3200:  # Less than 0.1 seconds of audio
            return ""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(self._transcribe_chunk_sync, audio_bytes),
        )
        return result

    async def transcribe_file(self, file_path: str) -> list[dict]:
        """Transcribe a WAV file asynchronously, returning timestamped segments."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            partial(self._transcribe_file_sync, file_path),
        )
        return result
