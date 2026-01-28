from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from pydantic import BaseModel
import hashlib
import json
import secrets

from app.api.deps import get_db, get_current_admin, _create_token, _verify_token
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


class AdminUserCreate(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


# ---------- Auth Endpoints ----------

@router.get("/setup-status")
def get_setup_status(db: Session = Depends(get_db)):
    """Check if any admin users exist (for first-time setup detection)."""
    row = db.execute(text("SELECT COUNT(*) as cnt FROM admin_users")).fetchone()
    return {"has_users": row.cnt > 0}


@router.post("/login")
def login(creds: LoginRequest, db: Session = Depends(get_db)):
    """Verify credentials, set HttpOnly cookie, update last_login."""
    row = db.execute(
        text("SELECT id, username, password_hash, salt, display_name, is_active FROM admin_users WHERE username = :u"),
        {"u": creds.username},
    ).fetchone()
    if not row or not row.is_active:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    expected_hash = hashlib.sha256((row.salt + creds.password).encode()).hexdigest()
    if expected_hash != row.password_hash:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Update last_login
    db.execute(text("UPDATE admin_users SET last_login = NOW() WHERE id = :id"), {"id": row.id})
    db.commit()

    token = _create_token(row.id, row.username)
    settings = get_settings()
    response = JSONResponse(content={
        "message": "Login successful",
        "user": {"user_id": row.id, "username": row.username, "display_name": row.display_name},
    })
    response.set_cookie(
        key="admin_token",
        value=token,
        httponly=True,
        path="/api/v1/admin",
        samesite="strict",
        max_age=settings.admin_token_expiry_hours * 3600,
    )
    return response


@router.post("/logout")
def logout():
    """Clear the admin_token cookie."""
    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie(key="admin_token", path="/api/v1/admin", samesite="strict")
    return response


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_admin)):
    """Return current authenticated user info."""
    return current_user


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
               status, error_message
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
            "error_message": row.error_message
        })

    return {"entries": entries, "total": len(entries)}


# ---------- Admin Users ----------

def _hash_password(password: str, salt: str) -> str:
    """Hash password with SHA-256 + salt."""
    return hashlib.sha256((salt + password).encode()).hexdigest()


@router.get("/users")
def get_admin_users(current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """List all admin users (no passwords returned)."""

    query = """
        SELECT id, username, display_name, role, is_active, last_login, created_at
        FROM admin_users
        ORDER BY created_at
    """
    rows = db.execute(text(query)).fetchall()

    users = []
    for row in rows:
        users.append({
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "role": row.role,
            "is_active": row.is_active,
            "last_login": row.last_login.isoformat() if row.last_login else None,
            "created_at": row.created_at.isoformat() if row.created_at else None
        })

    return {"users": users, "total": len(users)}


@router.post("/users")
def create_admin_user(user: AdminUserCreate, request: Request, db: Session = Depends(get_db)):
    """Create a new admin user. No auth required if zero users exist (bootstrap), otherwise requires auth."""

    # Check if any users exist
    count_row = db.execute(text("SELECT COUNT(*) as cnt FROM admin_users")).fetchone()
    has_users = count_row.cnt > 0

    if has_users:
        # Require auth — manually verify token since we can't conditionally use Depends
        token = request.cookies.get("admin_token")
        payload = _verify_token(token)
        if payload is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        caller = db.execute(
            text("SELECT id, is_active FROM admin_users WHERE id = :id"),
            {"id": payload["user_id"]},
        ).fetchone()
        if not caller or not caller.is_active:
            raise HTTPException(status_code=401, detail="Not authenticated")

    # Check for duplicate username
    existing = db.execute(
        text("SELECT id FROM admin_users WHERE username = :username"),
        {"username": user.username}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"Username '{user.username}' already exists")

    salt = secrets.token_hex(32)
    password_hash = _hash_password(user.password, salt)

    query = """
        INSERT INTO admin_users (username, password_hash, salt, display_name, role)
        VALUES (:username, :password_hash, :salt, :display_name, 'admin')
        RETURNING id
    """
    result = db.execute(text(query), {
        "username": user.username,
        "password_hash": password_hash,
        "salt": salt,
        "display_name": user.display_name or user.username
    })
    db.commit()
    new_id = result.fetchone().id

    return {"id": new_id, "username": user.username, "message": "Admin user created"}


@router.delete("/users/{user_id}")
def delete_admin_user(user_id: int, current_user: dict = Depends(get_current_admin), db: Session = Depends(get_db)):
    """Deactivate an admin user (soft delete)."""

    result = db.execute(
        text("UPDATE admin_users SET is_active = false WHERE id = :id RETURNING id"),
        {"id": user_id}
    )
    db.commit()
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"User ID {user_id} not found")

    return {"id": user_id, "message": "Admin user deactivated"}
