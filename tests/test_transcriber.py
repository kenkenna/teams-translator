"""Unit tests for WhisperTranscriber."""
import struct
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from app.services.transcriber import WhisperTranscriber


def make_pcm_bytes(samples: list[int]) -> bytes:
    """Pack a list of int16 samples into raw PCM bytes (little-endian)."""
    return struct.pack(f"<{len(samples)}h", *samples)


class TestPcmBytesToFloat32:
    def test_zero_sample(self):
        t = WhisperTranscriber()
        data = make_pcm_bytes([0])
        result = t._pcm_bytes_to_float32(data)
        assert result[0] == pytest.approx(0.0)

    def test_max_positive(self):
        t = WhisperTranscriber()
        data = make_pcm_bytes([32767])
        result = t._pcm_bytes_to_float32(data)
        assert result[0] == pytest.approx(32767 / 32768.0)

    def test_negative_sample(self):
        t = WhisperTranscriber()
        data = make_pcm_bytes([-16384])
        result = t._pcm_bytes_to_float32(data)
        assert result[0] == pytest.approx(-0.5)

    def test_multiple_samples(self):
        t = WhisperTranscriber()
        data = make_pcm_bytes([0, 16384, -32768])
        result = t._pcm_bytes_to_float32(data)
        assert len(result) == 3
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(0.5)
        assert result[2] == pytest.approx(-1.0)

    def test_output_dtype(self):
        t = WhisperTranscriber()
        data = make_pcm_bytes([100, 200])
        result = t._pcm_bytes_to_float32(data)
        assert result.dtype == np.float32


class TestIsSilence:
    def test_all_zeros_is_silence(self):
        t = WhisperTranscriber()
        audio = np.zeros(1600, dtype=np.float32)
        assert t._is_silence(audio)

    def test_loud_audio_is_not_silence(self):
        t = WhisperTranscriber()
        # RMS of a 0.5-amplitude signal is 0.5, well above default threshold 0.01
        audio = np.full(1600, 0.5, dtype=np.float32)
        assert not t._is_silence(audio)

    def test_custom_threshold(self):
        t = WhisperTranscriber()
        audio = np.full(100, 0.05, dtype=np.float32)
        assert t._is_silence(audio, threshold=0.1)
        assert not t._is_silence(audio, threshold=0.01)


class TestTranscribeChunk:
    @pytest.mark.asyncio
    async def test_too_short_returns_empty(self):
        """Chunks < 3200 bytes are skipped without loading the model."""
        t = WhisperTranscriber()
        result = await t.transcribe_chunk(b"\x00" * 100)
        assert result == ""

    @pytest.mark.asyncio
    async def test_silence_chunk_returns_empty(self):
        """Silent audio returns empty string without calling the model."""
        t = WhisperTranscriber()
        silent_pcm = make_pcm_bytes([0] * 1600)  # 3200 bytes, all zeros
        with patch.object(t, "_load_realtime_model") as mock_load:
            result = await t.transcribe_chunk(silent_pcm)
        mock_load.assert_not_called()
        assert result == ""

    @pytest.mark.asyncio
    async def test_transcribe_chunk_calls_model(self):
        """Non-silent chunk calls the model and returns its output."""
        t = WhisperTranscriber()

        mock_segment = MagicMock()
        mock_segment.text = "  Test transcription  "
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())

        with patch.object(t, "_load_realtime_model", return_value=mock_model):
            loud_pcm = make_pcm_bytes([16000] * 1600)  # 3200 bytes, loud audio
            result = await t.transcribe_chunk(loud_pcm)

        assert result == "Test transcription"

    @pytest.mark.asyncio
    async def test_transcribe_chunk_filters_blank_audio(self):
        """[BLANK_AUDIO] segments are filtered out."""
        t = WhisperTranscriber()

        mock_segment = MagicMock()
        mock_segment.text = "[BLANK_AUDIO]"
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())

        with patch.object(t, "_load_realtime_model", return_value=mock_model):
            loud_pcm = make_pcm_bytes([16000] * 1600)
            result = await t.transcribe_chunk(loud_pcm)

        assert result == ""
