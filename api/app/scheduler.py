from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BackgroundScheduler()

JOB_ID = "daily_backup"
AIS_PURGE_JOB_ID = "daily_ais_purge"
AIS_ROLLING_PURGE_JOB_ID = "ais_rolling_purge"


def _get_backup_func():
    from app.api.routes.admin import run_scheduled_backup
    return run_scheduled_backup


def _get_ais_purge_func():
    from app.api.routes.admin import run_daily_ais_purge
    return run_daily_ais_purge


def _get_rolling_ais_purge_func():
    from app.api.routes.admin import run_rolling_ais_purge
    return run_rolling_ais_purge


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


def set_daily_ais_purge(enabled: bool):
    """Add or remove the daily AIS data purge job (runs at 23:55)."""
    if enabled:
        if not scheduler.get_job(AIS_PURGE_JOB_ID):
            scheduler.add_job(
                _get_ais_purge_func(),
                trigger=CronTrigger(hour=23, minute=55),
                id=AIS_PURGE_JOB_ID,
                replace_existing=True,
            )
    else:
        if scheduler.get_job(AIS_PURGE_JOB_ID):
            scheduler.remove_job(AIS_PURGE_JOB_ID)


def set_rolling_ais_purge(enabled: bool):
    """Add or remove the hourly AIS rolling purge job (runs at minute 0 of each hour)."""
    if enabled:
        if not scheduler.get_job(AIS_ROLLING_PURGE_JOB_ID):
            scheduler.add_job(
                _get_rolling_ais_purge_func(),
                trigger=CronTrigger(minute=0),
                id=AIS_ROLLING_PURGE_JOB_ID,
                replace_existing=True,
            )
    else:
        if scheduler.get_job(AIS_ROLLING_PURGE_JOB_ID):
            scheduler.remove_job(AIS_ROLLING_PURGE_JOB_ID)


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

    if data.get("ais_purge_enabled", False):
        scheduler.add_job(
            _get_ais_purge_func(),
            trigger=CronTrigger(hour=23, minute=55),
            id=AIS_PURGE_JOB_ID,
            replace_existing=True,
        )

    if data.get("ais_rolling_purge_enabled", False):
        scheduler.add_job(
            _get_rolling_ais_purge_func(),
            trigger=CronTrigger(minute=0),
            id=AIS_ROLLING_PURGE_JOB_ID,
            replace_existing=True,
        )

    scheduler.start()


def shutdown_scheduler():
    """Shut down the scheduler gracefully."""
    scheduler.shutdown(wait=False)
