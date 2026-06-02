import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.db import init_db
from app.logging_config import configure_logging
from app.poller import WeatherPoller
from app.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    init_db()

    settings = get_settings()
    poller: WeatherPoller | None = None
    poller_task: asyncio.Task[None] | None = None

    if settings.enable_poller:
        poller = WeatherPoller(settings=settings)
        poller_task = asyncio.create_task(poller.run_forever())
        logger.info("Background weather poller enabled")

    yield

    if poller is not None:
        poller.stop()
    if poller_task is not None:
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="WatchAgent", lifespan=lifespan)
app.include_router(router)
