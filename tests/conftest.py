"""Shared test fixtures."""
import os

# Must be set before any app imports since settings is a singleton
os.environ.setdefault("ANTHROPIC_API_KEY", "test-api-key")

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport


@pytest_asyncio.fixture
async def initialized_db(tmp_path):
    """Initialize a fresh in-memory test database and patch settings."""
    from app.core.config import settings

    original_db_path = settings.db_path
    settings.db_path = str(tmp_path / "test.db")

    from app.database import init_db
    await init_db()

    yield settings.db_path

    settings.db_path = original_db_path


@pytest.fixture
def mock_transcriber():
    m = MagicMock()
    m.transcribe_chunk = AsyncMock(return_value="Hello world")
    m.transcribe_file = AsyncMock(return_value=[
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
    ])
    return m


@pytest.fixture
def mock_translator():
    m = MagicMock()
    m.translate = AsyncMock(return_value="こんにちは世界")
    return m


@pytest.fixture
def mock_summarizer():
    m = MagicMock()
    m.summarize = AsyncMock(return_value="## 会議サマリー\n\nテスト内容")
    return m


@pytest_asyncio.fixture
async def client(initialized_db, mock_transcriber, mock_translator, mock_summarizer):
    """HTTP test client with mocked services and isolated DB."""
    import app.main as main_module

    main_module.transcriber = mock_transcriber
    main_module.translator = mock_translator
    main_module.summarizer = mock_summarizer

    async with AsyncClient(
        transport=ASGITransport(app=main_module.app),
        base_url="http://test",
    ) as ac:
        yield ac
