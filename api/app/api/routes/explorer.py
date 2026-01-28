from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import date

from app.api.deps import get_db, get_current_admin

router = APIRouter()

SORT_WHITELIST = {"catch_date", "weight_lbs", "species_name"}


@router.get("/filters")
def get_explorer_filters(
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Return available filter options for the data explorer."""

    species = db.execute(
        text("SELECT species_code, common_name FROM species ORDER BY common_name")
    ).fetchall()

    vessels = db.execute(
        text("""
            SELECT id, vessel_name, mmsi
            FROM vessels
            WHERE vessel_name IS NOT NULL
            ORDER BY vessel_name
        """)
    ).fetchall()

    sources = db.execute(
        text("SELECT DISTINCT source FROM catches WHERE source IS NOT NULL ORDER BY source")
    ).fetchall()

    methods = db.execute(
        text("SELECT DISTINCT fishing_method FROM catches WHERE fishing_method IS NOT NULL ORDER BY fishing_method")
    ).fetchall()

    date_range = db.execute(
        text("SELECT MIN(catch_date) AS min_date, MAX(catch_date) AS max_date FROM catches")
    ).fetchone()

    return {
        "species": [
            {"species_code": r.species_code, "common_name": r.common_name}
            for r in species
        ],
        "vessels": [
            {"id": r.id, "vessel_name": r.vessel_name, "mmsi": r.mmsi}
            for r in vessels
        ],
        "sources": [r.source for r in sources],
        "fishing_methods": [r.fishing_method for r in methods],
        "date_range": {
            "min": date_range.min_date.isoformat() if date_range.min_date else None,
            "max": date_range.max_date.isoformat() if date_range.max_date else None,
        },
    }


@router.get("/catches")
def get_explorer_catches(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    species: Optional[str] = Query(None, description="Comma-separated species codes"),
    vessel_id: Optional[int] = Query(None),
    source: Optional[str] = Query(None),
    fishing_method: Optional[str] = Query(None),
    sort_by: str = Query("catch_date"),
    sort_dir: str = Query("desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Query catches with filters, sorting, and pagination."""

    if sort_by not in SORT_WHITELIST:
        sort_by = "catch_date"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    where_clauses = []
    params: dict = {}

    if date_from:
        where_clauses.append("c.catch_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        where_clauses.append("c.catch_date <= :date_to")
        params["date_to"] = date_to
    if species:
        codes = [s.strip().upper() for s in species.split(",") if s.strip()]
        if codes:
            where_clauses.append("s.species_code = ANY(:species_codes)")
            params["species_codes"] = codes
    if vessel_id is not None:
        where_clauses.append("c.vessel_id = :vessel_id")
        params["vessel_id"] = vessel_id
    if source:
        where_clauses.append("c.source = :source")
        params["source"] = source
    if fishing_method:
        where_clauses.append("c.fishing_method = :fishing_method")
        params["fishing_method"] = fishing_method

    where_sql = (" AND ".join(where_clauses)) if where_clauses else "1=1"

    # Sort column mapping (species_name comes from joined table)
    sort_col = {
        "catch_date": "c.catch_date",
        "weight_lbs": "c.weight_lbs",
        "species_name": "s.common_name",
    }[sort_by]

    # Count query
    count_sql = f"""
        SELECT COUNT(*) AS total
        FROM catches c
        LEFT JOIN species s ON c.species_id = s.id
        WHERE {where_sql}
    """
    total = db.execute(text(count_sql), params).fetchone().total

    # Data query
    data_sql = f"""
        SELECT
            c.id,
            c.catch_date,
            s.common_name AS species_name,
            s.species_code,
            c.weight_lbs,
            c.quantity,
            v.vessel_name,
            c.latitude,
            c.longitude,
            c.fishing_method,
            c.source,
            c.depth_fathoms,
            c.water_temp_f
        FROM catches c
        LEFT JOIN species s ON c.species_id = s.id
        LEFT JOIN vessels v ON c.vessel_id = v.id
        WHERE {where_sql}
        ORDER BY {sort_col} {sort_dir} NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset

    rows = db.execute(text(data_sql), params).fetchall()

    catches = []
    for r in rows:
        catches.append({
            "id": r.id,
            "catch_date": r.catch_date.isoformat() if r.catch_date else None,
            "species_name": r.species_name,
            "species_code": r.species_code,
            "weight_lbs": float(r.weight_lbs) if r.weight_lbs else None,
            "quantity": r.quantity,
            "vessel_name": r.vessel_name,
            "latitude": float(r.latitude) if r.latitude else None,
            "longitude": float(r.longitude) if r.longitude else None,
            "fishing_method": r.fishing_method,
            "source": r.source,
            "depth_fathoms": r.depth_fathoms,
            "water_temp_f": float(r.water_temp_f) if r.water_temp_f else None,
        })

    return {
        "catches": catches,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
