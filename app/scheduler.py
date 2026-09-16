import logging

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.sync import run_sync

logger = logging.getLogger("netbox_search.scheduler")

scheduler = BackgroundScheduler(timezone="UTC")


def _job() -> None:
    try:
        run_sync()
    except Exception:
        logger.exception("Scheduled NetBox sync failed; will retry next interval")


def start_scheduler() -> None:
    if scheduler.running:
        return
    scheduler.add_job(
        _job,
        "interval",
        hours=settings.sync_interval_hours,
        id="netbox_sync",
        next_run_time=None,  # startup sync is triggered separately in main.py
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
