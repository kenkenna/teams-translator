import asyncio
import io
import logging
import struct
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self) -> None:
        self.display_connections: list[WebSocket] = []
        self.is_capturing: bool = False

    async def connect_display(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.display_connections.append(websocket)
        await websocket.send_json({
            "type": "status",
            "is_capturing": self.is_capturing,
        })

    def disconnect_display(self, websocket: WebSocket) -> None:
        if websocket in self.display_connections:
            self.display_connections.remove(websocket)

    async def broadcast_translation(self, data: dict) -> None:
        dead_connections = []
        for connection in self.display_connections:
            try:
                await connection.send_json(data)
            except Exception:
                dead_connections.append(connection)
        for conn in dead_connections:
            self.disconnect_display(conn)

    async def broadcast_status(self) -> None:
        await self.broadcast_translation({
            "type": "status",
            "is_capturing": self.is_capturing,
        })


manager = ConnectionManager()


def _make_wav_header(num_samples: int, sample_rate: int = 16000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """Create a WAV file header for the given PCM parameters."""
    data_size = num_samples * num_channels * (bits_per_sample // 8)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(bits_per_sample // 8)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * data_size)
    header = buffer.getvalue()[:44]
    return header


def _write_wav_file(file_path: str, pcm_data: bytes, sample_rate: int = 16000) -> None:
    """Write raw PCM data to a WAV file."""
    with wave.open(file_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


@router.websocket("/ws/capture")
async def websocket_capture(
    websocket: WebSocket,
    mode: str = Query(default="realtime", pattern="^(realtime|record)$"),
    meeting_id: Optional[int] = Query(default=None),
):
    from app.main import transcriber, translator
    from app.database import get_db

    await websocket.accept()
    manager.is_capturing = True
    await manager.broadcast_status()

    CHUNK_SIZE = 96000  # 3 seconds at 16000 Hz, 16-bit mono
    audio_buffer = bytearray()
    recording_data = bytearray()
    audio_file_path: Optional[str] = None
    started_at = datetime.now(timezone.utc)

    if mode == "record" and meeting_id is not None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        recordings_dir = Path(settings.recordings_dir)
        recordings_dir.mkdir(parents=True, exist_ok=True)
        audio_file_path = str(recordings_dir / f"meeting_{meeting_id}_{timestamp}.wav")
        async with get_db() as db:
            await db.execute(
                "UPDATE meetings SET started_at = ?, status = 'recording', audio_file = ? WHERE id = ?",
                (started_at.isoformat(), audio_file_path, meeting_id),
            )
            await db.commit()

    try:
        while True:
            data = await websocket.receive_bytes()
            audio_buffer.extend(data)

            if mode == "record":
                recording_data.extend(data)

            while len(audio_buffer) >= CHUNK_SIZE:
                chunk = bytes(audio_buffer[:CHUNK_SIZE])
                audio_buffer = audio_buffer[CHUNK_SIZE:]

                text = await transcriber.transcribe_chunk(chunk)
                if text and text.strip():
                    translated = await translator.translate(text)
                    if translated:
                        await manager.broadcast_translation({
                            "type": "translation",
                            "original": text,
                            "translated": translated,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })

    except WebSocketDisconnect:
        logger.info(f"Capture WebSocket disconnected (mode={mode}, meeting_id={meeting_id})")
    except Exception as e:
        logger.error(f"Error in capture WebSocket: {e}")
    finally:
        manager.is_capturing = False
        await manager.broadcast_status()

        if mode == "record" and meeting_id is not None and recording_data:
            try:
                _write_wav_file(audio_file_path, bytes(recording_data))
                ended_at = datetime.now(timezone.utc)
                duration = (ended_at - started_at).total_seconds()
                async with get_db() as db:
                    await db.execute(
                        "UPDATE meetings SET ended_at = ?, duration_seconds = ?, status = 'done' WHERE id = ?",
                        (ended_at.isoformat(), duration, meeting_id),
                    )
                    await db.commit()
                logger.info(f"Saved recording: {audio_file_path} ({duration:.1f}s)")
            except Exception as e:
                logger.error(f"Error saving WAV file: {e}")
                async with get_db() as db:
                    await db.execute(
                        "UPDATE meetings SET status = 'error' WHERE id = ?",
                        (meeting_id,),
                    )
                    await db.commit()


@router.websocket("/ws/display")
async def websocket_display(websocket: WebSocket):
    await manager.connect_display(websocket)
    try:
        while True:
            # Keep connection alive; client may send pings
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        logger.info("Display WebSocket disconnected")
    except Exception as e:
        logger.debug(f"Display WebSocket error: {e}")
    finally:
        manager.disconnect_display(websocket)


@router.get("/api/realtime/status")
async def get_realtime_status():
    return {"is_capturing": manager.is_capturing}
