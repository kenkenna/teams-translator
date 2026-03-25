"""Tests for WAV file utility functions."""
import io
import struct
import wave
import pytest
from pathlib import Path

from app.api.routes.realtime import _make_wav_header, _write_wav_file


class TestMakeWavHeader:
    def test_returns_44_bytes(self):
        header = _make_wav_header(num_samples=1600)
        assert len(header) == 44

    def test_starts_with_riff(self):
        header = _make_wav_header(num_samples=1600)
        assert header[:4] == b"RIFF"

    def test_contains_wave_marker(self):
        header = _make_wav_header(num_samples=1600)
        assert header[8:12] == b"WAVE"

    def test_custom_sample_rate(self):
        # The header should encode 44100 Hz
        header = _make_wav_header(num_samples=44100, sample_rate=44100)
        # Bytes 24-27 hold sample rate as little-endian uint32
        sample_rate = struct.unpack_from("<I", header, 24)[0]
        assert sample_rate == 44100


class TestWriteWavFile:
    def test_creates_file(self, tmp_path):
        path = str(tmp_path / "output.wav")
        pcm = b"\x00\x00" * 1600  # 1600 silent 16-bit samples
        _write_wav_file(path, pcm)
        assert Path(path).exists()

    def test_readable_as_wav(self, tmp_path):
        path = str(tmp_path / "output.wav")
        pcm = b"\x00\x00" * 1600
        _write_wav_file(path, pcm)

        with wave.open(path, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 1600

    def test_roundtrip_pcm_data(self, tmp_path):
        """Write PCM then read back raw frames and verify they match."""
        path = str(tmp_path / "output.wav")
        # 4 samples: 0, 1000, -1000, 32767
        pcm = struct.pack("<4h", 0, 1000, -1000, 32767)
        _write_wav_file(path, pcm)

        with wave.open(path, "rb") as wf:
            frames = wf.readframes(4)
        assert frames == pcm
