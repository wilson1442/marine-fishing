from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()

JOB_ID = "daily_backup"


def _get_backup_func():
    from app.api.routes.admin import run_scheduled_backup
    return run_scheduled_backup


def set_daily_backup(enabled: bool):
    """Add or remove the daily midnight backup job."""
    if enabled:
        if not scheduler.get_job(JOB_ID):
            scheduler.add_job(
                _get_backup_func(),
                trigger=CronTrigger(hour=0, minute=0),
                id=JOB_ID,
                replace_existing=True,
            )
    else:
        if scheduler.get_job(JOB_ID):
            scheduler.remove_job(JOB_ID)


def init_scheduler():
    """Start the scheduler and restore saved schedule from disk."""
    from app.api.routes.admin import _read_schedule_file

    data = _read_schedule_file()
    if data.get("daily_enabled", False):
        scheduler.add_job(
            _get_backup_func(),
            trigger=CronTrigger(hour=0, minute=0),
            id=JOB_ID,
            replace_existing=True,
        )

    scheduler.start()


def shutdown_scheduler():
    """Shut down the scheduler gracefully."""
    scheduler.shutdown(wait=False)
