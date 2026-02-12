from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from pydantic import BaseModel
import hashlib
import json
import secrets
import subprocess
import shutil
import os
import re
import gzip
from datetime import datetime
from urllib.parse import urlparse

from app.api.deps import get_db, get_current_admin, _create_token, _verify_token, generate_api_key
from app.config import get_settings

router = APIRouter()


# ---------- Pydantic models ----------

class DataSourceCreate(BaseModel):
    source_key: str
    display_name: str
    description: Optional[str] = None
    source_type: Optional[str] = "harvester"
    schedule: Optional[str] = None
    api_endpoint: Optional[str] = None
    config: Optional[dict] = None


class DataSourceUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    source_type: Optional[str] = None
    schedule: Optional[str] = None
    api_endpoint: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[dict] = None


class ScheduledBackupUpdate(BaseModel):
    enabled: bool


class AisPurgeScheduleUpdate(BaseModel):
    enabled: bool


class AisRollingPurgeScheduleUpdate(BaseModel):
    enabled: bool


class RegistrationCreate(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str


class UserLoginRequest(BaseModel):
    email: str
    password: str


class ExpirationUpdate(BaseModel):
    expires_at: Optional[str] = None


class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None


class RegistrationUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    status: Optional[str] = None
    role: Optional[str] = None


class ApiKeyCreate(BaseModel):
    label: str
    duration: str  # 1_week, 1_month, 3_months, 6_months, 12_months, never


# ---------- API Keys Table ----------

def _ensure_api_keys_table(db: Session):
    """Create the api_keys table if it doesn't exist."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            key_hash VARCHAR(128) NOT NULL,
            key_prefix VARCHAR(11) NOT NULL,
            label VARCHAR(255) NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP,
            last_used_at TIMESTAMP,
            is_active BOOLEAN DEFAULT TRUE,
            request_count INTEGER DEFAULT 0
        )
    """))
    db.commit()


# ---------- Registered Users Table ----------

def _ensure_registered_users_table(db: Session):
    """Create the registered_users table if it doesn't exist."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS registered_users (
            id SERIAL PRIMARY KEY,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(128) NOT NULL,
            salt VARCHAR(64) NOT NULL,
            status VARCHAR(20) DEFAULT 'pending',
            reviewed_by INTEGER,
            reviewed_at TIMESTAMP,
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    # Migration for existing databases
    db.execute(text("""
        ALTER TABLE registered_users ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP
    """))
    db.execute(text("""
        ALTER TABLE registered_users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user'
    """))
    db.commit()


# ---------- Dashboard ----------

@router.get("/dashboard")
def get_dashboard(current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Get admin dashboard summary with table counts and data breakdowns."""

    # Table row counts
    counts_query = """
        SELECT
            (SELECT COUNT(*) FROM catches) as catches,
            (SELECT COUNT(*) FROM weather_observations) as weather_observations,
            (SELECT COUNT(*) FROM vessels) as vessels,
            (SELECT COUNT(*) FROM species) as species,
            (SELECT COUNT(*) FROM fishing_effort) as fishing_effort,
            (SELECT COUNT(*) FROM buoy_stations) as buoy_stations,
            (SELECT COUNT(*) FROM buoy_stations WHERE is_active = true) as active_buoys
    """
    counts = db.execute(text(counts_query)).fetchone()

    # Catches by source
    source_query = """
        SELECT source, COUNT(*) as count,
               MIN(catch_date) as earliest,
               MAX(catch_date) as latest
        FROM catches
        GROUP BY source
        ORDER BY count DESC
    """
    source_rows = db.execute(text(source_query)).fetchall()
    catches_by_source = []
    for row in source_rows:
        catches_by_source.append({
            "source": row.source,
            "count": row.count,
            "earliest": row.earliest.isoformat() if row.earliest else None,
            "latest": row.latest.isoformat() if row.latest else None
        })

    # Overall date range and fishing days
    range_query = """
        SELECT
            MIN(catch_date) as min_date,
            MAX(catch_date) as max_date,
            COUNT(DISTINCT catch_date) as fishing_days
        FROM catches
    """
    range_result = db.execute(text(range_query)).fetchone()

    return {
        "table_counts": {
            "catches": counts.catches,
            "weather_observations": counts.weather_observations,
            "vessels": counts.vessels,
            "species": counts.species,
            "fishing_effort": counts.fishing_effort,
            "buoy_stations": counts.buoy_stations,
            "active_buoys": counts.active_buoys
        },
        "catches_by_source": catches_by_source,
        "date_range": {
            "start": range_result.min_date.isoformat() if range_result.min_date else None,
            "end": range_result.max_date.isoformat() if range_result.max_date else None
        },
        "fishing_days": range_result.fishing_days or 0
    }


# ---------- Data Sources ----------

@router.get("/sources")
def get_data_sources(current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """List all data sources with their last sync status."""

    # Auto-cleanup stale 'running' entries
    # For streaming sources (like AIS), check the heartbeat in metadata
    # For other sources, use 1 hour timeout from started_at
    db.execute(text("""
        UPDATE data_sync_log
        SET status = 'failed',
            completed_at = NOW(),
            error_message = 'Process terminated unexpectedly (stale running entry)'
        WHERE status = 'running'
          AND (
            -- Non-streaming: stale if started more than 1 hour ago
            (sync_type != 'streaming' AND started_at < NOW() - INTERVAL '1 hour')
            OR
            -- Streaming: stale if heartbeat is more than 10 minutes old (or no heartbeat and started > 10 min ago)
            (sync_type = 'streaming' AND (
                (metadata->>'last_heartbeat' IS NOT NULL
                 AND (metadata->>'last_heartbeat')::timestamptz < NOW() - INTERVAL '10 minutes')
                OR
                (metadata->>'last_heartbeat' IS NULL
                 AND started_at < NOW() - INTERVAL '10 minutes')
            ))
          )
    """))
    db.commit()

    query = """
        SELECT
            ds.*,
            last_sync.started_at as last_sync_started,
            last_sync.completed_at as last_sync_completed,
            last_sync.status as last_sync_status,
            last_sync.records_processed as last_records_processed,
            last_sync.records_inserted as last_records_inserted,
            last_sync.error_message as last_error
        FROM data_sources ds
        LEFT JOIN LATERAL (
            SELECT started_at, completed_at, status, records_processed,
                   records_inserted, error_message
            FROM data_sync_log
            WHERE source = ds.source_key
            ORDER BY started_at DESC
            LIMIT 1
        ) last_sync ON true
        ORDER BY ds.display_name
    """
    rows = db.execute(text(query)).fetchall()

    sources = []
    for row in rows:
        sources.append({
            "id": row.id,
            "source_key": row.source_key,
            "display_name": row.display_name,
            "description": row.description,
            "source_type": row.source_type,
            "schedule": row.schedule,
            "api_endpoint": row.api_endpoint,
            "is_active": row.is_active,
            "config": row.config,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "last_sync": {
                "started_at": row.last_sync_started.isoformat() if row.last_sync_started else None,
                "completed_at": row.last_sync_completed.isoformat() if row.last_sync_completed else None,
                "status": row.last_sync_status,
                "records_processed": row.last_records_processed,
                "records_inserted": row.last_records_inserted,
                "error": row.last_error
            } if row.last_sync_started else None
        })

    return {"sources": sources, "total": len(sources)}


@router.post("/sources")
def create_data_source(source: DataSourceCreate, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Add a new data source."""

    # Check for duplicate
    existing = db.execute(
        text("SELECT id FROM data_sources WHERE source_key = :key"),
        {"key": source.source_key}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Source '{source.source_key}' already exists")

    query = """
        INSERT INTO data_sources (source_key, display_name, description, source_type, schedule, api_endpoint, config)
        VALUES (:source_key, :display_name, :description, :source_type, :schedule, :api_endpoint, :config)
        RETURNING id
    """
    result = db.execute(text(query), {
        "source_key": source.source_key,
        "display_name": source.display_name,
        "description": source.description,
        "source_type": source.source_type,
        "schedule": source.schedule,
        "api_endpoint": source.api_endpoint,
        "config": json.dumps(source.config) if source.config else None
    })
    db.commit()
    new_id = result.fetchone().id

    return {"id": new_id, "source_key": source.source_key, "message": "Data source created"}


@router.put("/sources/{source_key}")
def update_data_source(source_key: str, update: DataSourceUpdate, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Update a data source."""

    existing = db.execute(
        text("SELECT id FROM data_sources WHERE source_key = :key"),
        {"key": source_key}
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail=f"Source '{source_key}' not found")

    # Build dynamic update
    fields = []
    params = {"key": source_key}
    for field_name, value in update.dict(exclude_unset=True).items():
        if field_name == "config":
            fields.append(f"{field_name} = :{field_name}")
            params[field_name] = json.dumps(value) if value else None
        else:
            fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    query = f"UPDATE data_sources SET {', '.join(fields)} WHERE source_key = :key"
    db.execute(text(query), params)
    db.commit()

    return {"source_key": source_key, "message": "Data source updated"}


@router.delete("/sources/{source_key}")
def delete_data_source(source_key: str, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Deactivate a data source (soft delete)."""

    result = db.execute(
        text("UPDATE data_sources SET is_active = false WHERE source_key = :key RETURNING id"),
        {"key": source_key}
    )
    db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Source '{source_key}' not found")

    return {"source_key": source_key, "message": "Data source deactivated"}


# ---------- Sync History ----------

@router.get("/sync-history")
def get_sync_history(
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get recent data sync log entries."""

    query = """
        SELECT id, source, sync_type, started_at, completed_at,
               date_range_start, date_range_end,
               records_processed, records_inserted, records_updated, records_skipped,
               status, error_message, log_messages
        FROM data_sync_log
    """
    params = {"limit": limit}

    if source:
        query += " WHERE source = :source"
        params["source"] = source

    query += " ORDER BY started_at DESC LIMIT :limit"

    rows = db.execute(text(query), params).fetchall()

    entries = []
    for row in rows:
        entries.append({
            "id": row.id,
            "source": row.source,
            "sync_type": row.sync_type,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "date_range_start": row.date_range_start.isoformat() if row.date_range_start else None,
            "date_range_end": row.date_range_end.isoformat() if row.date_range_end else None,
            "records_processed": row.records_processed,
            "records_inserted": row.records_inserted,
            "records_updated": row.records_updated,
            "records_skipped": row.records_skipped,
            "status": row.status,
            "error_message": row.error_message,
            "has_logs": bool(row.log_messages),
        })

    return {"entries": entries, "total": len(entries)}


@router.get("/sync-history/{sync_id}/logs")
def get_sync_logs(
    sync_id: int,
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    """Get the captured log messages for a specific sync run."""

    row = db.execute(text("""
        SELECT id, source, status, started_at, completed_at,
               error_message, log_messages
        FROM data_sync_log WHERE id = :id
    """), {"id": sync_id}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Sync entry not found")

    return {
        "id": row.id,
        "source": row.source,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error_message": row.error_message,
        "log_messages": row.log_messages or "No log messages captured for this sync run.",
    }


def _hash_password(password: str, salt: str) -> str:
    """Hash password with SHA-256 + salt."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


# ---------- Database Backup Helpers ----------

def _find_executable(name: str) -> str:
    """Find the full path to an executable, checking common locations."""
    path = shutil.which(name)
    if path:
        return path
    for d in ["/usr/bin", "/usr/local/bin", "/bin", "/usr/lib/postgresql/16/bin"]:
        candidate = os.path.join(d, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise FileNotFoundError(f"'{name}' not found on this system")


def _parse_database_url(url: str) -> dict:
    """Parse DATABASE_URL into components for pg_dump."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "dbname": (parsed.path or "/marine_fishing").lstrip("/"),
        "user": parsed.username or "marine_user",
        "password": parsed.password or "",
    }


def _validate_backup_filename(filename: str) -> bool:
    """Validate backup filename to prevent path traversal."""
    return bool(re.match(r'^marine_fishing_\d{8}_\d{6}\.sql\.gz$', filename))


def _format_file_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ---------- Local Backups ----------

@router.post("/backups/local")
def create_local_backup(current_user: dict = Depends(get_current_admin)):
    """Create a local database backup using pg_dump."""
    settings = get_settings()
    db_info = _parse_database_url(settings.database_url)

    os.makedirs(settings.backup_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"marine_fishing_{timestamp}.sql.gz"
    filepath = os.path.join(settings.backup_dir, filename)

    env = os.environ.copy()
    env["PGPASSWORD"] = db_info["password"]

    try:
        # Run pg_dump and pipe through gzip
        pg_dump_bin = _find_executable("pg_dump")
        gzip_bin = _find_executable("gzip")

        pg_dump_cmd = [
            pg_dump_bin,
            "-h", db_info["host"],
            "-p", db_info["port"],
            "-U", db_info["user"],
            "-d", db_info["dbname"],
            "--no-password",
        ]
        dump_proc = subprocess.Popen(
            pg_dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        with open(filepath, "wb") as f:
            gzip_proc = subprocess.Popen(
                [gzip_bin],
                stdin=dump_proc.stdout,
                stdout=f,
                stderr=subprocess.PIPE,
            )
            # Close pg_dump's stdout in parent so gzip sees EOF when pg_dump finishes
            dump_proc.stdout.close()
            gzip_proc.wait(timeout=600)

        dump_proc.wait(timeout=600)

        if dump_proc.returncode != 0:
            stderr = dump_proc.stderr.read().decode("utf-8", errors="replace")
            if os.path.exists(filepath):
                os.remove(filepath)
            raise HTTPException(status_code=500, detail=f"pg_dump failed: {stderr[:500]}")

        file_size = os.path.getsize(filepath)
        return {
            "filename": filename,
            "size": file_size,
            "size_formatted": _format_file_size(file_size),
            "download_url": f"/api/v1/admin/backups/download/{filename}",
            "message": "Backup created successfully",
        }

    except subprocess.TimeoutExpired:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(status_code=500, detail="Backup timed out")
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


@router.get("/backups")
def list_backups(current_user: dict = Depends(get_current_admin)):
    """List all local backup files."""
    settings = get_settings()
    backup_dir = settings.backup_dir

    if not os.path.exists(backup_dir):
        return {"backups": [], "total": 0}

    backups = []
    for fname in sorted(os.listdir(backup_dir), reverse=True):
        if not _validate_backup_filename(fname):
            continue
        fpath = os.path.join(backup_dir, fname)
        stat = os.stat(fpath)
        backups.append({
            "filename": fname,
            "size": stat.st_size,
            "size_formatted": _format_file_size(stat.st_size),
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            "download_url": f"/api/v1/admin/backups/download/{fname}",
        })

    return {"backups": backups, "total": len(backups)}


@router.get("/backups/download/{filename}")
def download_backup(filename: str, current_user: dict = Depends(get_current_admin)):
    """Download a backup file."""
    if not _validate_backup_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    settings = get_settings()
    filepath = os.path.join(settings.backup_dir, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Backup file not found")

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/gzip",
    )


@router.delete("/backups/{filename}")
def delete_backup(filename: str, current_user: dict = Depends(get_current_admin)):
    """Delete a local backup file."""
    if not _validate_backup_filename(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")

    settings = get_settings()
    filepath = os.path.join(settings.backup_dir, filename)

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Backup file not found")

    os.remove(filepath)
    return {"filename": filename, "message": "Backup deleted"}


# ---------- Site Settings ----------

SITE_SETTINGS_FILE = "/opt/marine-fishing/api/site_settings.json"

def _read_site_settings() -> dict:
    if os.path.exists(SITE_SETTINGS_FILE):
        with open(SITE_SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def _write_site_settings(data: dict):
    with open(SITE_SETTINGS_FILE, "w") as f:
        json.dump(data, f)


@router.get("/settings")
def get_site_settings(current_user: dict = Depends(get_current_admin)):
    """Get all site settings (admin only)."""
    return _read_site_settings()


@router.put("/settings")
def update_site_settings(body: dict, current_user: dict = Depends(get_current_admin)):
    """Update site settings (admin only)."""
    data = _read_site_settings()
    data.update(body)
    _write_site_settings(data)
    return data


# ---------- Scheduled Backup ----------

def _read_schedule_file() -> dict:
    """Read the backup schedule config from disk."""
    settings = get_settings()
    path = settings.backup_schedule_file
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"daily_enabled": False}


def _write_schedule_file(data: dict):
    """Write the backup schedule config to disk."""
    settings = get_settings()
    os.makedirs(os.path.dirname(settings.backup_schedule_file), exist_ok=True)
    with open(settings.backup_schedule_file, "w") as f:
        json.dump(data, f)


def run_scheduled_backup():
    """Execute a local backup (called by APScheduler at midnight)."""
    settings = get_settings()
    db_info = _parse_database_url(settings.database_url)

    os.makedirs(settings.backup_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"marine_fishing_{timestamp}.sql.gz"
    filepath = os.path.join(settings.backup_dir, filename)

    env = os.environ.copy()
    env["PGPASSWORD"] = db_info["password"]

    try:
        pg_dump_bin = _find_executable("pg_dump")
        gzip_bin = _find_executable("gzip")

        pg_dump_cmd = [
            pg_dump_bin,
            "-h", db_info["host"],
            "-p", db_info["port"],
            "-U", db_info["user"],
            "-d", db_info["dbname"],
            "--no-password",
        ]
        dump_proc = subprocess.Popen(
            pg_dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        with open(filepath, "wb") as f:
            gzip_proc = subprocess.Popen(
                [gzip_bin],
                stdin=dump_proc.stdout,
                stdout=f,
                stderr=subprocess.PIPE,
            )
            dump_proc.stdout.close()
            gzip_proc.wait(timeout=600)

        dump_proc.wait(timeout=600)

        if dump_proc.returncode != 0:
            stderr = dump_proc.stderr.read().decode("utf-8", errors="replace")
            if os.path.exists(filepath):
                os.remove(filepath)
            print(f"[scheduled-backup] pg_dump failed: {stderr[:500]}")
            return

        file_size = os.path.getsize(filepath)
        print(f"[scheduled-backup] Created {filename} ({_format_file_size(file_size)})")

    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        print(f"[scheduled-backup] Failed: {e}")


@router.get("/backups/schedule")
def get_backup_schedule(current_user: dict = Depends(get_current_admin)):
    """Get the current daily backup schedule status."""
    data = _read_schedule_file()
    return {"daily_enabled": data.get("daily_enabled", False)}


@router.put("/backups/schedule")
def set_backup_schedule(body: ScheduledBackupUpdate, current_user: dict = Depends(get_current_admin)):
    """Enable or disable the daily midnight backup."""
    from app.scheduler import set_daily_backup

    data = _read_schedule_file()
    data["daily_enabled"] = body.enabled
    _write_schedule_file(data)

    set_daily_backup(body.enabled)

    return {
        "daily_enabled": body.enabled,
        "message": "Daily backup enabled" if body.enabled else "Daily backup disabled",
    }


# ---------- AIS Data Purge ----------

def run_daily_ais_purge():
    """Backup database then purge AIS position and event data (called by APScheduler at 23:55)."""
    from sqlalchemy import create_engine
    from app.config import get_settings

    settings = get_settings()
    db_info = _parse_database_url(settings.database_url)

    # Step 1: Create backup first
    os.makedirs(settings.backup_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"marine_fishing_{timestamp}.sql.gz"
    backup_filepath = os.path.join(settings.backup_dir, backup_filename)

    env = os.environ.copy()
    env["PGPASSWORD"] = db_info["password"]

    try:
        pg_dump_bin = _find_executable("pg_dump")
        gzip_bin = _find_executable("gzip")

        pg_dump_cmd = [
            pg_dump_bin,
            "-h", db_info["host"],
            "-p", db_info["port"],
            "-U", db_info["user"],
            "-d", db_info["dbname"],
            "--no-password",
        ]
        dump_proc = subprocess.Popen(
            pg_dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        with open(backup_filepath, "wb") as f:
            gzip_proc = subprocess.Popen(
                [gzip_bin],
                stdin=dump_proc.stdout,
                stdout=f,
                stderr=subprocess.PIPE,
            )
            dump_proc.stdout.close()
            gzip_proc.wait(timeout=600)

        dump_proc.wait(timeout=600)

        if dump_proc.returncode != 0:
            stderr = dump_proc.stderr.read().decode("utf-8", errors="replace")
            if os.path.exists(backup_filepath):
                os.remove(backup_filepath)
            print(f"[ais-purge] Backup failed, aborting purge: {stderr[:500]}")
            return

        file_size = os.path.getsize(backup_filepath)
        print(f"[ais-purge] Pre-purge backup created: {backup_filename} ({_format_file_size(file_size)})")

    except Exception as e:
        if os.path.exists(backup_filepath):
            os.remove(backup_filepath)
        print(f"[ais-purge] Backup failed, aborting purge: {e}")
        return

    # Step 2: Purge AIS data
    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            # Delete in order to respect foreign key constraints if any
            result_loitering = conn.execute(text("DELETE FROM detected_loitering_events"))
            result_fishing = conn.execute(text("DELETE FROM detected_fishing_events"))
            result_positions = conn.execute(text("DELETE FROM vessel_positions"))
            conn.commit()

            print(f"[ais-purge] Purged: {result_positions.rowcount} positions, "
                  f"{result_fishing.rowcount} fishing events, {result_loitering.rowcount} loitering events")

    except Exception as e:
        print(f"[ais-purge] Purge failed: {e}")


@router.get("/ais-purge/schedule")
def get_ais_purge_schedule(current_user: dict = Depends(get_current_admin)):
    """Get the current daily AIS purge schedule status."""
    data = _read_schedule_file()
    return {"ais_purge_enabled": data.get("ais_purge_enabled", False)}


@router.put("/ais-purge/schedule")
def set_ais_purge_schedule(body: AisPurgeScheduleUpdate, current_user: dict = Depends(get_current_admin)):
    """Enable or disable the daily AIS data purge (runs at 23:55)."""
    from app.scheduler import set_daily_ais_purge

    data = _read_schedule_file()
    data["ais_purge_enabled"] = body.enabled
    _write_schedule_file(data)

    set_daily_ais_purge(body.enabled)

    return {
        "ais_purge_enabled": body.enabled,
        "message": "Daily AIS purge enabled (runs at 23:55 UTC)" if body.enabled else "Daily AIS purge disabled",
    }


@router.post("/ais-purge/run")
def run_ais_purge_now(current_user: dict = Depends(get_current_admin)):
    """Manually trigger the AIS data purge (with backup)."""
    run_daily_ais_purge()
    return {"message": "AIS purge completed. Check server logs for details."}


# ---------- AIS Rolling Purge (6-hour retention) ----------

def run_rolling_ais_purge():
    """Delete AIS data older than 6 hours (called by APScheduler every hour)."""
    from sqlalchemy import create_engine
    from app.config import get_settings

    settings = get_settings()

    try:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            result_positions = conn.execute(text(
                "DELETE FROM vessel_positions WHERE received_at < NOW() - INTERVAL '6 hours'"
            ))
            result_fishing = conn.execute(text(
                "DELETE FROM detected_fishing_events WHERE start_time < NOW() - INTERVAL '6 hours'"
            ))
            result_loitering = conn.execute(text(
                "DELETE FROM detected_loitering_events WHERE start_time < NOW() - INTERVAL '6 hours'"
            ))
            conn.commit()

            print(f"[ais-rolling-purge] Purged: {result_positions.rowcount} positions, "
                  f"{result_fishing.rowcount} fishing events, {result_loitering.rowcount} loitering events")

    except Exception as e:
        print(f"[ais-rolling-purge] Purge failed: {e}")


@router.get("/ais-rolling-purge/schedule")
def get_ais_rolling_purge_schedule(current_user: dict = Depends(get_current_admin)):
    """Get the current hourly AIS rolling purge schedule status."""
    data = _read_schedule_file()
    return {"ais_rolling_purge_enabled": data.get("ais_rolling_purge_enabled", False)}


@router.put("/ais-rolling-purge/schedule")
def set_ais_rolling_purge_schedule(body: AisRollingPurgeScheduleUpdate, current_user: dict = Depends(get_current_admin)):
    """Enable or disable the hourly AIS rolling purge (keeps only last 6 hours of data)."""
    from app.scheduler import set_rolling_ais_purge

    data = _read_schedule_file()
    data["ais_rolling_purge_enabled"] = body.enabled
    _write_schedule_file(data)

    set_rolling_ais_purge(body.enabled)

    return {
        "ais_rolling_purge_enabled": body.enabled,
        "message": "Hourly AIS rolling purge enabled (keeps last 6 hours)" if body.enabled else "Hourly AIS rolling purge disabled",
    }


@router.post("/ais-rolling-purge/run")
def run_ais_rolling_purge_now(current_user: dict = Depends(get_current_admin)):
    """Manually trigger the AIS rolling purge (deletes data older than 6 hours)."""
    run_rolling_ais_purge()
    return {"message": "AIS rolling purge completed. Check server logs for details."}


# ---------- SSH Key Management ----------

@router.post("/backups/ssh-keygen")
def generate_ssh_key(current_user: dict = Depends(get_current_admin)):
    """Generate an SSH keypair for remote backups."""
    settings = get_settings()
    ssh_dir = settings.ssh_key_dir
    key_path = os.path.join(ssh_dir, "backup_key")
    pub_path = key_path + ".pub"

    os.makedirs(ssh_dir, exist_ok=True)

    if os.path.exists(key_path):
        # Key already exists, return the public key
        with open(pub_path, "r") as f:
            pub_key = f.read().strip()
        return {"public_key": pub_key, "message": "SSH key already exists", "exists": True}

    try:
        result = subprocess.run(
            [
                "ssh-keygen",
                "-t", "ed25519",
                "-f", key_path,
                "-N", "",  # no passphrase
                "-C", "marine-fishing-backup",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"ssh-keygen failed: {result.stderr[:500]}")

        # Set correct permissions
        os.chmod(key_path, 0o600)
        os.chmod(pub_path, 0o644)

        with open(pub_path, "r") as f:
            pub_key = f.read().strip()

        return {"public_key": pub_key, "message": "SSH key generated", "exists": False}

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="ssh-keygen timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key generation failed: {str(e)}")


@router.get("/backups/ssh-pubkey")
def get_ssh_pubkey(current_user: dict = Depends(get_current_admin)):
    """Get the current SSH public key."""
    settings = get_settings()
    pub_path = os.path.join(settings.ssh_key_dir, "backup_key.pub")

    if not os.path.exists(pub_path):
        raise HTTPException(status_code=404, detail="No SSH key generated yet")

    with open(pub_path, "r") as f:
        pub_key = f.read().strip()

    return {"public_key": pub_key}


# ---------- Remote Backups ----------

class RemoteBackupRequest(BaseModel):
    host: str
    port: int = 22
    remote_path: str


class RemoteTestRequest(BaseModel):
    host: str
    port: int = 22


@router.post("/backups/remote/test")
def test_remote_connection(req: RemoteTestRequest, current_user: dict = Depends(get_current_admin)):
    """Test SSH connectivity to a remote host."""
    settings = get_settings()
    key_path = os.path.join(settings.ssh_key_dir, "backup_key")

    if not os.path.exists(key_path):
        raise HTTPException(status_code=400, detail="No SSH key generated. Generate one first.")

    # Validate host - basic check to prevent injection
    if not re.match(r'^[a-zA-Z0-9._\-]+$', req.host):
        raise HTTPException(status_code=400, detail="Invalid hostname")
    if not (1 <= req.port <= 65535):
        raise HTTPException(status_code=400, detail="Invalid port number")

    try:
        result = subprocess.run(
            [
                "ssh",
                "-i", key_path,
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=10",
                "-o", "BatchMode=yes",
                "-p", str(req.port),
                f"root@{req.host}",
                "echo", "connection_ok",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        if result.returncode == 0 and "connection_ok" in result.stdout:
            return {"status": "ok", "message": "Connection successful"}
        else:
            detail = result.stderr.strip()[:500] if result.stderr else "Connection failed"
            return {"status": "failed", "message": detail}

    except subprocess.TimeoutExpired:
        return {"status": "failed", "message": "Connection timed out"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


@router.post("/backups/remote")
def create_remote_backup(req: RemoteBackupRequest, current_user: dict = Depends(get_current_admin)):
    """Create a database backup and send it to a remote server via SCP."""
    settings = get_settings()
    key_path = os.path.join(settings.ssh_key_dir, "backup_key")
    db_info = _parse_database_url(settings.database_url)

    if not os.path.exists(key_path):
        raise HTTPException(status_code=400, detail="No SSH key generated. Generate one first.")

    # Validate inputs
    if not re.match(r'^[a-zA-Z0-9._\-]+$', req.host):
        raise HTTPException(status_code=400, detail="Invalid hostname")
    if not (1 <= req.port <= 65535):
        raise HTTPException(status_code=400, detail="Invalid port number")
    if not req.remote_path or ".." in req.remote_path:
        raise HTTPException(status_code=400, detail="Invalid remote path")

    os.makedirs(settings.backup_dir, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"marine_fishing_{timestamp}.sql.gz"
    filepath = os.path.join(settings.backup_dir, filename)

    env = os.environ.copy()
    env["PGPASSWORD"] = db_info["password"]

    try:
        # Step 1: Create local backup
        pg_dump_bin = _find_executable("pg_dump")
        gzip_bin = _find_executable("gzip")

        pg_dump_cmd = [
            pg_dump_bin,
            "-h", db_info["host"],
            "-p", db_info["port"],
            "-U", db_info["user"],
            "-d", db_info["dbname"],
            "--no-password",
        ]
        dump_proc = subprocess.Popen(
            pg_dump_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        with open(filepath, "wb") as f:
            gzip_proc = subprocess.Popen(
                [gzip_bin],
                stdin=dump_proc.stdout,
                stdout=f,
                stderr=subprocess.PIPE,
            )
            dump_proc.stdout.close()
            gzip_proc.wait(timeout=600)

        dump_proc.wait(timeout=600)

        if dump_proc.returncode != 0:
            stderr = dump_proc.stderr.read().decode("utf-8", errors="replace")
            if os.path.exists(filepath):
                os.remove(filepath)
            raise HTTPException(status_code=500, detail=f"pg_dump failed: {stderr[:500]}")

        file_size = os.path.getsize(filepath)

        # Step 2: SCP to remote
        remote_dest = req.remote_path.rstrip("/") + "/" + filename
        scp_result = subprocess.run(
            [
                "scp",
                "-i", key_path,
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=15",
                "-o", "BatchMode=yes",
                "-P", str(req.port),
                filepath,
                f"root@{req.host}:{remote_dest}",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        if scp_result.returncode != 0:
            detail = scp_result.stderr.strip()[:500] if scp_result.stderr else "SCP transfer failed"
            raise HTTPException(status_code=500, detail=f"SCP failed: {detail}")

        return {
            "filename": filename,
            "size": file_size,
            "size_formatted": _format_file_size(file_size),
            "remote_host": req.host,
            "remote_path": remote_dest,
            "message": "Backup sent to remote server successfully",
        }

    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Operation timed out")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Remote backup failed: {str(e)}")


# ---------- Public Registration ----------

@router.post("/register")
def register_user(reg: RegistrationCreate, db: Session = Depends(get_db)):
    """Public endpoint: submit a registration request (pending admin approval)."""
    _ensure_registered_users_table(db)

    # Validate email format
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', reg.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Validate required fields
    if not reg.first_name.strip() or not reg.last_name.strip():
        raise HTTPException(status_code=400, detail="First name and last name are required")
    if len(reg.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    # Check duplicate email
    existing = db.execute(
        text("SELECT id FROM registered_users WHERE email = :email"),
        {"email": reg.email.strip().lower()}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    salt = secrets.token_hex(32)
    password_hash = _hash_password(reg.password, salt)

    result = db.execute(text("""
        INSERT INTO registered_users (first_name, last_name, email, password_hash, salt, status, role)
        VALUES (:first_name, :last_name, :email, :password_hash, :salt, 'pending', 'user')
        RETURNING id
    """), {
        "first_name": reg.first_name.strip(),
        "last_name": reg.last_name.strip(),
        "email": reg.email.strip().lower(),
        "password_hash": password_hash,
        "salt": salt,
    })
    db.commit()
    new_id = result.fetchone().id

    return {"id": new_id, "message": "Registration submitted. Awaiting admin approval."}


# ---------- User Login/Logout/Me ----------

@router.post("/user-login")
def user_login(creds: UserLoginRequest, db: Session = Depends(get_db)):
    """Authenticate a registered user with email and password."""
    _ensure_registered_users_table(db)

    row = db.execute(
        text("SELECT id, email, first_name, last_name, password_hash, salt, status, expires_at, role FROM registered_users WHERE email = :email"),
        {"email": creds.email.strip().lower()},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    expected_hash = hashlib.sha256((row.salt + creds.password).encode()).hexdigest()
    if expected_hash != row.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if row.status == "pending":
        raise HTTPException(status_code=403, detail="Your account is pending admin approval")
    if row.status == "denied":
        raise HTTPException(status_code=403, detail="Your account registration was denied")
    if row.status != "approved":
        raise HTTPException(status_code=403, detail="Account is not active")

    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Your account has expired. Please contact an administrator.")

    token = _create_token(row.id, row.email)
    settings = get_settings()
    response = JSONResponse(content={
        "message": "Login successful",
        "user": {"id": row.id, "email": row.email, "first_name": row.first_name, "last_name": row.last_name, "role": row.role or "user"},
    })
    response.set_cookie(
        key="user_token",
        value=token,
        httponly=True,
        path="/",
        samesite="strict",
        max_age=settings.admin_token_expiry_hours * 3600,
    )
    return response


@router.post("/user-logout")
def user_logout():
    """Clear the user_token cookie."""
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie(key="user_token", path="/", samesite="strict")
    return response


@router.get("/user-me")
def get_user_me(request: Request, db: Session = Depends(get_db)):
    """Return current authenticated registered user info."""
    _ensure_registered_users_table(db)

    token = request.cookies.get("user_token")
    payload = _verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = db.execute(
        text("SELECT id, email, first_name, last_name, status, expires_at, role FROM registered_users WHERE id = :id"),
        {"id": payload["user_id"]},
    ).fetchone()

    if not row or row.status != "approved":
        raise HTTPException(status_code=401, detail="Not authenticated")

    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Account expired")

    return {
        "id": row.id,
        "email": row.email,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "role": row.role or "user",
    }


@router.put("/user-me")
def update_user_me(update: ProfileUpdate, request: Request, db: Session = Depends(get_db)):
    """Self-service profile update for the authenticated user."""
    _ensure_registered_users_table(db)

    token = request.cookies.get("user_token")
    payload = _verify_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    row = db.execute(
        text("SELECT id, email, first_name, last_name, password_hash, salt, status, expires_at, role FROM registered_users WHERE id = :id"),
        {"id": payload["user_id"]},
    ).fetchone()

    if not row or row.status != "approved":
        raise HTTPException(status_code=401, detail="Not authenticated")

    if row.expires_at and row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=403, detail="Account expired")

    fields = []
    params = {"id": row.id}

    if update.first_name is not None:
        if not update.first_name.strip():
            raise HTTPException(status_code=400, detail="First name cannot be empty")
        fields.append("first_name = :first_name")
        params["first_name"] = update.first_name.strip()

    if update.last_name is not None:
        if not update.last_name.strip():
            raise HTTPException(status_code=400, detail="Last name cannot be empty")
        fields.append("last_name = :last_name")
        params["last_name"] = update.last_name.strip()

    if update.email is not None:
        email = update.email.strip().lower()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            raise HTTPException(status_code=400, detail="Invalid email format")
        dup = db.execute(
            text("SELECT id FROM registered_users WHERE email = :email AND id != :id"),
            {"email": email, "id": row.id}
        ).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        fields.append("email = :email")
        params["email"] = email

    if update.new_password is not None:
        if not update.current_password:
            raise HTTPException(status_code=400, detail="Current password is required to set a new password")
        expected_hash = _hash_password(update.current_password, row.salt)
        if expected_hash != row.password_hash:
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        if len(update.new_password) < 6:
            raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
        salt = secrets.token_hex(32)
        password_hash = _hash_password(update.new_password, salt)
        fields.append("password_hash = :password_hash")
        fields.append("salt = :salt")
        params["password_hash"] = password_hash
        params["salt"] = salt

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    query = f"UPDATE registered_users SET {', '.join(fields)} WHERE id = :id"
    db.execute(text(query), params)
    db.commit()

    updated = db.execute(
        text("SELECT id, email, first_name, last_name, role FROM registered_users WHERE id = :id"),
        {"id": row.id},
    ).fetchone()

    return {
        "id": updated.id,
        "email": updated.email,
        "first_name": updated.first_name,
        "last_name": updated.last_name,
        "role": updated.role or "user",
    }


# ---------- Admin Registration Management ----------

@router.get("/registrations")
def list_registrations(
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, denied"),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """List all registered users, optionally filtered by status."""
    _ensure_registered_users_table(db)

    query = """
        SELECT r.id, r.first_name, r.last_name, r.email, r.status, r.role,
               r.created_at, r.reviewed_at, r.expires_at, r.reviewed_by,
               rev.first_name as rev_first, rev.last_name as rev_last
        FROM registered_users r
        LEFT JOIN registered_users rev ON r.reviewed_by = rev.id
    """
    params = {}
    if status and status in ("pending", "approved", "denied"):
        query += " WHERE r.status = :status"
        params["status"] = status
    query += " ORDER BY r.created_at DESC"

    rows = db.execute(text(query), params).fetchall()

    registrations = []
    for row in rows:
        reviewed_by_name = None
        if row.rev_first or row.rev_last:
            reviewed_by_name = ((row.rev_first or "") + " " + (row.rev_last or "")).strip()
        registrations.append({
            "id": row.id,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "email": row.email,
            "status": row.status,
            "role": row.role or "user",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "reviewed_by": reviewed_by_name,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        })

    return {"registrations": registrations, "total": len(registrations)}


@router.put("/registrations/{reg_id}/approve")
def approve_registration(reg_id: int, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Approve a pending registration."""
    _ensure_registered_users_table(db)

    row = db.execute(
        text("SELECT id, status FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registration not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail=f"Registration is already {row.status}")

    db.execute(text("""
        UPDATE registered_users
        SET status = 'approved', reviewed_by = :admin_id, reviewed_at = NOW()
        WHERE id = :id
    """), {"id": reg_id, "admin_id": current_user["user_id"]})
    db.commit()

    return {"id": reg_id, "status": "approved", "message": "Registration approved"}


@router.put("/registrations/{reg_id}/deny")
def deny_registration(reg_id: int, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Deny a pending registration."""
    _ensure_registered_users_table(db)

    row = db.execute(
        text("SELECT id, status FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registration not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail=f"Registration is already {row.status}")

    db.execute(text("""
        UPDATE registered_users
        SET status = 'denied', reviewed_by = :admin_id, reviewed_at = NOW()
        WHERE id = :id
    """), {"id": reg_id, "admin_id": current_user["user_id"]})
    db.commit()

    return {"id": reg_id, "status": "denied", "message": "Registration denied"}


@router.put("/registrations/{reg_id}/expiration")
def update_expiration(reg_id: int, body: ExpirationUpdate, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Set or clear the expiration date for a registered user."""
    _ensure_registered_users_table(db)

    row = db.execute(
        text("SELECT id FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Registration not found")

    expires_at = None
    if body.expires_at:
        try:
            expires_at = datetime.strptime(body.expires_at, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    db.execute(text("""
        UPDATE registered_users SET expires_at = :expires_at WHERE id = :id
    """), {"id": reg_id, "expires_at": expires_at})
    db.commit()

    return {"id": reg_id, "expires_at": body.expires_at, "message": "Expiration updated"}


@router.put("/registrations/{reg_id}")
def update_registration(reg_id: int, update: RegistrationUpdate, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Update a registered user's details."""
    _ensure_registered_users_table(db)

    existing = db.execute(
        text("SELECT id FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Registration not found")

    fields = []
    params = {"id": reg_id}

    for field_name, value in update.dict(exclude_unset=True).items():
        if field_name == "password":
            if value and len(value) < 6:
                raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
            salt = secrets.token_hex(32)
            password_hash = _hash_password(value, salt)
            fields.append("password_hash = :password_hash")
            fields.append("salt = :salt")
            params["password_hash"] = password_hash
            params["salt"] = salt
        elif field_name == "email":
            email = value.strip().lower()
            dup = db.execute(
                text("SELECT id FROM registered_users WHERE email = :email AND id != :id"),
                {"email": email, "id": reg_id}
            ).fetchone()
            if dup:
                raise HTTPException(status_code=409, detail="An account with this email already exists")
            fields.append("email = :email")
            params["email"] = email
        elif field_name == "status":
            if value not in ("pending", "approved", "denied"):
                raise HTTPException(status_code=400, detail="Invalid status")
            fields.append("status = :status")
            params["status"] = value
        elif field_name == "role":
            if value not in ("user", "admin"):
                raise HTTPException(status_code=400, detail="Invalid role. Must be 'user' or 'admin'")
            fields.append("role = :role")
            params["role"] = value
        else:
            fields.append(f"{field_name} = :{field_name}")
            params[field_name] = value.strip() if isinstance(value, str) else value

    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    query = f"UPDATE registered_users SET {', '.join(fields)} WHERE id = :id"
    db.execute(text(query), params)
    db.commit()

    return {"id": reg_id, "message": "Registration updated"}


@router.delete("/registrations/{reg_id}")
def delete_registration(reg_id: int, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Permanently delete a registered user."""
    _ensure_registered_users_table(db)

    existing = db.execute(
        text("SELECT id FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Registration not found")

    db.execute(
        text("DELETE FROM registered_users WHERE id = :id"),
        {"id": reg_id}
    )
    db.commit()

    return {"id": reg_id, "message": "Registration deleted"}


# ---------- API Key Management ----------

@router.get("/api-keys")
def list_api_keys(current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """List all API keys (prefix, label, dates, stats). Never returns the full key."""
    _ensure_api_keys_table(db)

    rows = db.execute(text("""
        SELECT
            ak.id, ak.key_prefix, ak.label, ak.created_at, ak.expires_at,
            ak.last_used_at, ak.is_active, ak.request_count,
            ru.first_name, ru.last_name
        FROM api_keys ak
        LEFT JOIN registered_users ru ON ak.created_by = ru.id
        ORDER BY ak.created_at DESC
    """)).fetchall()

    keys = []
    for row in rows:
        created_by_name = None
        if row.first_name or row.last_name:
            created_by_name = ((row.first_name or "") + " " + (row.last_name or "")).strip()
        keys.append({
            "id": row.id,
            "key_prefix": row.key_prefix,
            "label": row.label,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "is_active": row.is_active,
            "request_count": row.request_count or 0,
            "created_by": created_by_name,
        })

    return {"api_keys": keys, "total": len(keys)}


@router.post("/api-keys")
def create_api_key(body: ApiKeyCreate, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Create a new API key. Returns the full key ONCE - it cannot be retrieved again."""
    _ensure_api_keys_table(db)

    if not body.label or not body.label.strip():
        raise HTTPException(status_code=400, detail="Label is required")

    # Calculate expiration
    duration_map = {
        "1_week": 7,
        "1_month": 30,
        "3_months": 90,
        "6_months": 180,
        "12_months": 365,
        "never": None,
    }
    if body.duration not in duration_map:
        raise HTTPException(status_code=400, detail="Invalid duration")

    days = duration_map[body.duration]
    expires_at = None
    if days:
        from datetime import timedelta
        expires_at = datetime.utcnow() + timedelta(days=days)

    # Generate the key
    full_key, key_hash, key_prefix = generate_api_key()

    # Store in database
    result = db.execute(text("""
        INSERT INTO api_keys (key_hash, key_prefix, label, created_by, expires_at)
        VALUES (:key_hash, :key_prefix, :label, :created_by, :expires_at)
        RETURNING id
    """), {
        "key_hash": key_hash,
        "key_prefix": key_prefix,
        "label": body.label.strip(),
        "created_by": current_user["user_id"],
        "expires_at": expires_at,
    })
    db.commit()
    new_id = result.fetchone().id

    return {
        "id": new_id,
        "key": full_key,  # Only returned once!
        "key_prefix": key_prefix,
        "label": body.label.strip(),
        "expires_at": expires_at.isoformat() if expires_at else None,
        "message": "API key created. Save this key now - it will not be shown again.",
    }


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Revoke an API key (soft delete by setting is_active=false)."""
    _ensure_api_keys_table(db)

    existing = db.execute(
        text("SELECT id, is_active FROM api_keys WHERE id = :id"),
        {"id": key_id}
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="API key not found")

    if not existing.is_active:
        raise HTTPException(status_code=400, detail="API key is already revoked")

    db.execute(
        text("UPDATE api_keys SET is_active = false WHERE id = :id"),
        {"id": key_id}
    )
    db.commit()

    return {"id": key_id, "message": "API key revoked"}


