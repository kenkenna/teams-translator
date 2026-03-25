"""Integration tests for /api/meetings endpoints."""
import pytest
from app.database import get_db


async def _insert_meeting(db_path: str, name: str, status: str = "recording") -> int:
    """Helper: insert a meeting directly into the test DB and return its ID."""
    from app.core.config import settings
    from app.database import get_db

    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO meetings (name, status) VALUES (?, ?)",
            (name, status),
        )
        await db.commit()
        return cursor.lastrowid


class TestListMeetings:
    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        resp = await client.get("/api/meetings")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_returns_created_meetings(self, client, initialized_db):
        await _insert_meeting(initialized_db, "MTG1")
        await _insert_meeting(initialized_db, "MTG2")

        resp = await client.get("/api/meetings")
        assert resp.status_code == 200
        names = [m["name"] for m in resp.json()]
        assert "MTG1" in names
        assert "MTG2" in names


class TestCreateMeeting:
    @pytest.mark.asyncio
    async def test_creates_meeting(self, client):
        resp = await client.post("/api/meetings", json={"name": "週次MTG"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "週次MTG"
        assert "meeting_id" in data

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_name(self, client):
        resp = await client.post("/api/meetings", json={"name": "  MTG  "})
        assert resp.status_code == 201
        assert resp.json()["name"] == "MTG"

    @pytest.mark.asyncio
    async def test_empty_name_returns_400(self, client):
        resp = await client.post("/api/meetings", json={"name": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_whitespace_name_returns_400(self, client):
        resp = await client.post("/api/meetings", json={"name": "   "})
        assert resp.status_code == 400


class TestGetMeeting:
    @pytest.mark.asyncio
    async def test_get_existing_meeting(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "テスト会議")

        resp = await client.get(f"/api/meetings/{meeting_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "テスト会議"
        assert data["id"] == meeting_id
        assert data["transcripts"] == []
        assert data["summary"] is None

    @pytest.mark.asyncio
    async def test_get_nonexistent_meeting_returns_404(self, client):
        resp = await client.get("/api/meetings/99999")
        assert resp.status_code == 404


class TestGetMeetingStatus:
    @pytest.mark.asyncio
    async def test_returns_status(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "MTG", status="done")
        resp = await client.get(f"/api/meetings/{meeting_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    @pytest.mark.asyncio
    async def test_nonexistent_returns_404(self, client):
        resp = await client.get("/api/meetings/99999/status")
        assert resp.status_code == 404


class TestProcessMeeting:
    @pytest.mark.asyncio
    async def test_recording_status_returns_400(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "MTG", status="recording")
        resp = await client.post(f"/api/meetings/{meeting_id}/process")
        assert resp.status_code == 400
        assert "still recording" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_processing_status_returns_400(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "MTG", status="processing")
        resp = await client.post(f"/api/meetings/{meeting_id}/process")
        assert resp.status_code == 400
        assert "already being processed" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_done_status_starts_processing(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "MTG", status="done")
        resp = await client.post(f"/api/meetings/{meeting_id}/process")
        assert resp.status_code == 200
        assert resp.json()["meeting_id"] == meeting_id

    @pytest.mark.asyncio
    async def test_nonexistent_returns_404(self, client):
        resp = await client.post("/api/meetings/99999/process")
        assert resp.status_code == 404


class TestDeleteMeeting:
    @pytest.mark.asyncio
    async def test_delete_existing_meeting(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "削除MTG")
        resp = await client.delete(f"/api/meetings/{meeting_id}")
        assert resp.status_code == 204

        # Verify it's gone
        resp2 = await client.get(f"/api/meetings/{meeting_id}")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_404(self, client):
        resp = await client.delete("/api/meetings/99999")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_also_removes_transcripts(self, client, initialized_db):
        meeting_id = await _insert_meeting(initialized_db, "MTG with transcripts")
        async with get_db() as db:
            await db.execute(
                "INSERT INTO transcripts (meeting_id, timestamp_seconds, original_text, translated_text) "
                "VALUES (?, 0.0, 'Hello', 'こんにちは')",
                (meeting_id,),
            )
            await db.commit()

        await client.delete(f"/api/meetings/{meeting_id}")

        async with get_db() as db:
            rows = await db.execute_fetchall(
                "SELECT id FROM transcripts WHERE meeting_id = ?", (meeting_id,)
            )
        assert rows == []
