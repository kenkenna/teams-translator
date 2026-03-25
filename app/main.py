import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.database import init_db
from app.services.transcriber import WhisperTranscriber
from app.services.translator import TranslatorService
from app.services.summarizer import SummarizerService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Singleton service instances
transcriber: WhisperTranscriber = None
translator: TranslatorService = None
summarizer: SummarizerService = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcriber, translator, summarizer

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Create recordings directory
    recordings_dir = Path(settings.recordings_dir)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Recordings directory ready: {recordings_dir.resolve()}")

    # Initialize services (models loaded lazily on first use)
    transcriber = WhisperTranscriber()
    translator = TranslatorService()
    summarizer = SummarizerService()
    logger.info("Services initialized")

    yield

    logger.info("Shutting down")


app = FastAPI(
    title="Teams Meeting Translator",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from app.api.routes import realtime, meetings  # noqa: E402

app.include_router(realtime.router)
app.include_router(meetings.router)

# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return RedirectResponse(url="/static/index.html")
