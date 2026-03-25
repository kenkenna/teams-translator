"""Tests for realtime WebSocket endpoints and status API."""
import pytest


class TestRealtimeStatus:
    @pytest.mark.asyncio
    async def test_not_capturing_initially(self, client):
        resp = await client.get("/api/realtime/status")
        assert resp.status_code == 200
        assert resp.json() == {"is_capturing": False}


class TestConnectionManager:
    def test_initial_state(self):
        from app.api.routes.realtime import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.is_capturing is False
        assert mgr.display_connections == []

    def test_disconnect_unknown_websocket_is_safe(self):
        from app.api.routes.realtime import ConnectionManager
        from unittest.mock import MagicMock

        mgr = ConnectionManager()
        mgr.disconnect_display(MagicMock())  # should not raise
