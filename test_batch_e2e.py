"""
End-to-end test for the batch processing pipeline.

What this does:
  1. Synthesizes English speech using edge-tts
  2. Saves it as a WAV file in recordings/
  3. Creates a meeting via API
  4. Links the WAV to the meeting
  5. Triggers batch processing (transcription → translation → summary)
  6. Polls until done, then prints the results
"""
import asyncio
import io
import wave
import httpx
import miniaudio
import edge_tts

SERVER = "http://localhost:8000"
SPEECH_TEXT = (
    "Good morning everyone. Let's start today's meeting. "
    "First, I'd like to review the progress from last week. "
    "The development team has completed the new feature implementation. "
    "Testing is scheduled for next week. "
    "We also need to discuss the budget allocation for Q2. "
    "The marketing team has requested additional resources. "
    "Please review the proposal and share your feedback by Friday. "
    "Any questions before we move on?"
)


async def synthesize_wav(text: str, output_path: str) -> None:
    """Generate English speech and save as 16kHz mono WAV."""
    print("音声合成中...")
    communicate = edge_tts.Communicate(text, voice="en-US-AriaNeural")
    mp3_data = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            mp3_data.extend(chunk["data"])

    decoded = miniaudio.decode(
        bytes(mp3_data), nchannels=1, sample_rate=16000,
        output_format=miniaudio.SampleFormat.SIGNED16,
    )
    pcm = bytes(decoded.samples)

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(pcm)

    duration = len(pcm) / (16000 * 2)
    print(f"WAV保存完了: {output_path} ({duration:.1f}秒)")


async def main():
    async with httpx.AsyncClient(base_url=SERVER, timeout=300) as client:
        # Step 1: テスト用WAVを生成
        wav_path = "recordings/batch_test.wav"
        await synthesize_wav(SPEECH_TEXT, wav_path)

        # Step 2: 会議を作成
        resp = await client.post("/api/meetings", json={"name": "バッチ処理テスト会議"})
        resp.raise_for_status()
        meeting_id = resp.json()["meeting_id"]
        print(f"会議作成: meeting_id={meeting_id}")

        # Step 3: WAVファイルを紐付けてステータスをdoneに変更
        import aiosqlite
        async with aiosqlite.connect("meetings.db") as db:
            await db.execute(
                "UPDATE meetings SET audio_file=?, status='done' WHERE id=?",
                (wav_path, meeting_id),
            )
            await db.commit()
        print("WAVファイルを会議に紐付け完了")

        # Step 4: バッチ処理を起動
        resp = await client.post(f"/api/meetings/{meeting_id}/process")
        resp.raise_for_status()
        print("バッチ処理開始...")

        # Step 5: 完了するまでポーリング
        for i in range(120):
            await asyncio.sleep(3)
            resp = await client.get(f"/api/meetings/{meeting_id}/status")
            status = resp.json()["status"]
            print(f"  [{i*3:3d}s] status: {status}")
            if status in ("done", "error"):
                break

        # Step 6: 結果を表示
        resp = await client.get(f"/api/meetings/{meeting_id}")
        data = resp.json()

        print(f"\n===== バッチ処理結果 =====")
        print(f"ステータス: {data['status']}")
        print(f"文字起こし件数: {len(data['transcripts'])}件\n")

        for t in data["transcripts"]:
            ts = int(t["timestamp_seconds"])
            print(f"  [{ts//60:02d}:{ts%60:02d}] 原文: {t['original_text']}")
            print(f"         翻訳: {t['translated_text']}")
            print()

        if data["summary"]:
            print("===== サマリー =====")
            print(data["summary"]["content"])
        else:
            print("サマリーなし")


if __name__ == "__main__":
    asyncio.run(main())
