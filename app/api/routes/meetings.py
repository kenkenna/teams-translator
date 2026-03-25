import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.database import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateMeetingRequest(BaseModel):
    name: str


async def _process_meeting(meeting_id: int) -> None:
    """Background task: transcribe, translate, and summarize a recorded meeting."""
    from app.main import transcriber, translator, summarizer

    logger.info(f"Starting batch processing for meeting {meeting_id}")

    async with get_db() as db:
        await db.execute(
            "UPDATE meetings SET status = 'processing' WHERE id = ?",
            (meeting_id,),
        )
        await db.commit()

        row = await db.execute_fetchall(
            "SELECT audio_file, name FROM meetings WHERE id = ?",
            (meeting_id,),
        )

    if not row:
        logger.error(f"Meeting {meeting_id} not found")
        return

    audio_file = row[0]["audio_file"]
    meeting_name = row[0]["name"]

    if not audio_file or not Path(audio_file).exists():
        logger.error(f"Audio file not found for meeting {meeting_id}: {audio_file}")
        async with get_db() as db:
            await db.execute(
                "UPDATE meetings SET status = 'error' WHERE id = ?",
                (meeting_id,),
            )
            await db.commit()
        return

    try:
        # Step 1: Transcribe
        logger.info(f"Transcribing {audio_file}")
        segments = await transcriber.transcribe_file(audio_file)

        if not segments:
            logger.warning(f"No transcription segments for meeting {meeting_id}")

        # Step 2: Translate each segment
        translated_segments = []
        for segment in segments:
            translated_text = await translator.translate(segment["text"])
            translated_segments.append({
                "timestamp_seconds": segment["start"],
                "original_text": segment["text"],
                "translated_text": translated_text or segment["text"],
            })

        # Step 3: Save transcripts
        async with get_db() as db:
            await db.execute(
                "DELETE FROM transcripts WHERE meeting_id = ?",
                (meeting_id,),
            )
            for t in translated_segments:
                await db.execute(
                    "INSERT INTO transcripts (meeting_id, timestamp_seconds, original_text, translated_text) VALUES (?, ?, ?, ?)",
                    (meeting_id, t["timestamp_seconds"], t["original_text"], t["translated_text"]),
                )
            await db.commit()

        # Step 4: Generate summary
        logger.info(f"Generating summary for meeting {meeting_id}")
        summary_content = await summarizer.summarize(translated_segments, meeting_name)

        # Step 5: Save summary
        async with get_db() as db:
            await db.execute(
                "INSERT INTO summaries (meeting_id, content) VALUES (?, ?) "
                "ON CONFLICT(meeting_id) DO UPDATE SET content = excluded.content, created_at = datetime('now')",
                (meeting_id, summary_content),
            )
            await db.execute(
                "UPDATE meetings SET status = 'done' WHERE id = ?",
                (meeting_id,),
            )
            await db.commit()

        logger.info(f"Batch processing complete for meeting {meeting_id}")

    except Exception as e:
        logger.error(f"Error processing meeting {meeting_id}: {e}", exc_info=True)
        async with get_db() as db:
            await db.execute(
                "UPDATE meetings SET status = 'error' WHERE id = ?",
                (meeting_id,),
            )
            await db.commit()


@router.get("/api/meetings")
async def list_meetings():
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, name, status, started_at, ended_at, duration_seconds "
            "FROM meetings ORDER BY created_at DESC"
        )
    return [dict(row) for row in rows]


@router.post("/api/meetings", status_code=201)
async def create_meeting(body: CreateMeetingRequest):
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="Meeting name cannot be empty")

    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO meetings (name, status) VALUES (?, 'recording')",
            (body.name.strip(),),
        )
        meeting_id = cursor.lastrowid
        await db.commit()

    return {"meeting_id": meeting_id, "name": body.name.strip()}


@router.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: int):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, name, status, started_at, ended_at, duration_seconds, audio_file "
            "FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Meeting not found")
        meeting = dict(rows[0])

        transcripts = await db.execute_fetchall(
            "SELECT id, timestamp_seconds, original_text, translated_text "
            "FROM transcripts WHERE meeting_id = ? ORDER BY timestamp_seconds",
            (meeting_id,),
        )
        meeting["transcripts"] = [dict(t) for t in transcripts]

        summary_rows = await db.execute_fetchall(
            "SELECT content, created_at FROM summaries WHERE meeting_id = ?",
            (meeting_id,),
        )
        meeting["summary"] = dict(summary_rows[0]) if summary_rows else None

    return meeting


@router.post("/api/meetings/{meeting_id}/process")
async def process_meeting(meeting_id: int, background_tasks: BackgroundTasks):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, status FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Meeting not found")

        status = rows[0]["status"]
        if status == "recording":
            raise HTTPException(status_code=400, detail="Meeting is still recording")
        if status == "processing":
            raise HTTPException(status_code=400, detail="Meeting is already being processed")

    background_tasks.add_task(_process_meeting, meeting_id)
    return {"message": "Processing started", "meeting_id": meeting_id}


@router.delete("/api/meetings/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: int):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT id, audio_file FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Meeting not found")

        audio_file = rows[0]["audio_file"]

        await db.execute("DELETE FROM transcripts WHERE meeting_id = ?", (meeting_id,))
        await db.execute("DELETE FROM summaries WHERE meeting_id = ?", (meeting_id,))
        await db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
        await db.commit()

    if audio_file:
        audio_path = Path(audio_file)
        if audio_path.exists():
            try:
                audio_path.unlink()
                logger.info(f"Deleted audio file: {audio_file}")
            except Exception as e:
                logger.warning(f"Could not delete audio file {audio_file}: {e}")


@router.get("/api/meetings/{meeting_id}/status")
async def get_meeting_status(meeting_id: int):
    async with get_db() as db:
        rows = await db.execute_fetchall(
            "SELECT status FROM meetings WHERE id = ?",
            (meeting_id,),
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Meeting not found")
    return {"status": rows[0]["status"]}
