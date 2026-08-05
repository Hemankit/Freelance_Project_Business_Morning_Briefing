# src/api/app.py

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from src.api.routes.onboarding import router as onboarding_router
from src.run import run_all_active_clients

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()


def _run_daily_briefings() -> None:
    for briefing_run in run_all_active_clients():
        logger.info("briefing run finished: %s", briefing_run)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs in the same process/volume as the web server, so it shares
    # data/app.db without needing a second Railway service.
    hour = int(os.getenv("BRIEFING_RUN_HOUR_UTC", "11"))
    minute = int(os.getenv("BRIEFING_RUN_MINUTE_UTC", "0"))
    _scheduler.add_job(
        _run_daily_briefings,
        CronTrigger(hour=hour, minute=minute, timezone="UTC"),
        id="daily_briefing_run",
        replace_existing=True,
    )
    _scheduler.start()
    yield
    _scheduler.shutdown()


app = FastAPI(title="Morning Briefing Setup", lifespan=lifespan)
app.include_router(onboarding_router)