"""
End-to-end test for the real-time translation pipeline.

What this does:
  1. Synthesizes English speech using edge-tts
  2. Converts it to 16kHz mono PCM (required by the server)
  3. Connects to /ws/display to receive translations
  4. Streams the audio to /ws/capture
  5. Prints received translations in real time
"""
import asyncio
import io
import struct
import wave
import tempfile
from pathlib import Path

import edge_tts
import websockets


SERVER = "ws://localhost:8000"
SAMPLE_TEXT = (
    "Hello everyone. Today we will discuss the quarterly results. "
    "Sales have increased by twenty percent compared to last year. "
    "We need to focus on the Asian market in the next quarter."
)


def mp3_to_pcm16k(mp3_bytes: bytes) -> bytes:
    """Convert MP3 bytes to 16kHz mono 16-bit PCM using miniaudio."""
    import miniaudio
    decoded = miniaudio.decode(mp3_bytes, nchannels=1, sample_rate=16000,
                               output_format=miniaudio.SampleFormat.SIGNED16)
    return bytes(decoded.samples)


async def synthesize_speech(text: str) -> bytes:
    """Generate English speech MP3 using edge-tts."""
    print(f"音声合成中: '{text[:50]}...'")
    communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    mp3_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_data.extend(chunk["data"])
    print(f"音声合成完了: {len(mp3_data):,} bytes")
    return bytes(mp3_data)


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw PCM in WAV container so we can inspect it."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


async def listen_for_translations(received: list, stop_event: asyncio.Event):
    """Connect to /ws/display and print translations as they arrive."""
    uri = f"{SERVER}/ws/display"
    async with websockets.connect(uri) as ws:
        print(f"\n[display] 接続完了: {uri}")
        while not stop_event.is_set():
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                import json
                data = json.loads(msg)
                if data.get("type") == "translation":
                    print(f"\n--- 翻訳受信 ---")
                    print(f"  原文:   {data['original']}")
                    print(f"  翻訳:   {data['translated']}")
                    received.append(data)
                elif data.get("type") == "status":
                    print(f"[display] ステータス: is_capturing={data.get('is_capturing')}")
            except asyncio.TimeoutError:
                continue
            except websockets.ConnectionClosed:
                break


async def stream_audio(pcm_data: bytes, chunk_size: int = 16000):
    """Send PCM audio to /ws/capture in small chunks (simulates real-time capture)."""
    uri = f"{SERVER}/ws/capture?mode=realtime"
    async with websockets.connect(uri) as ws:
        print(f"\n[capture] 接続完了: {uri}")
        total = len(pcm_data)
        sent = 0
        while sent < total:
            chunk = pcm_data[sent:sent + chunk_size]
            await ws.send(chunk)
            sent += len(chunk)
            print(f"[capture] 送信中: {sent:,}/{total:,} bytes ({100*sent//total}%)", end="\r")
            await asyncio.sleep(0.05)  # 実時間に近いペースで送る
        print(f"\n[capture] 送信完了")


async def main():
    # Step 1: Synthesize English speech
    mp3_data = await synthesize_speech(SAMPLE_TEXT)

    # Step 2: Convert to 16kHz mono PCM
    print("PCM変換中...")
    pcm_data = mp3_to_pcm16k(mp3_data)

    duration = len(pcm_data) / (16000 * 2)
    print(f"PCM変換完了: {len(pcm_data):,} bytes ({duration:.1f}秒)")

    # Step 3: Start display listener and audio streamer concurrently
    received = []
    stop_event = asyncio.Event()

    listener_task = asyncio.create_task(listen_for_translations(received, stop_event))

    await asyncio.sleep(0.5)  # displayソケットが準備できるのを待つ

    # Step 4: Stream audio
    await stream_audio(pcm_data)

    # Step 5: Wait a bit for remaining translations
    print("\n翻訳完了を待機中...")
    await asyncio.sleep(15)
    stop_event.set()
    await listener_task

    # Summary
    print(f"\n===== 結果 =====")
    print(f"受信した翻訳: {len(received)}件")
    if not received:
        print("翻訳が受信されませんでした。サーバーログを確認してください。")
    return len(received) > 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
