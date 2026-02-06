from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from typing import Optional, List
from datetime import date

from app.api.deps import get_db, require_api_access
from app.models.catch import Catch
from app.models.species import Species
from app.models.fishing_conditions import FishingConditions

router = APIRouter()


@router.get("/geojson")
def get_catches_geojson(
    date_from: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    date_to: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    year: Optional[int] = Query(None, description="Filter by year"),
    species: Optional[str] = Query(None, description="Species codes (comma-separated)"),
    conditions: Optional[str] = Query(None, description="Condition names (comma-separated)"),
    bbox: Optional[str] = Query(None, description="Bounding box: SW_lng,SW_lat,NE_lng,NE_lat"),
    source: Optional[str] = Query(None, description="Data sources (comma-separated)"),
    limit: int = Query(500, ge=1, le=5000, description="Max records"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """
    Get catches as GeoJSON FeatureCollection for map display.
    Supports filtering by date range, year, species, conditions, bounding box, and source.
    """
    # Build the query using the v_map_catches view
    query = """
        SELECT
            c.id,
            c.catch_date,
            c.catch_time,
            s.common_name as species_name,
            s.species_code,
            s.color_hex,
            c.latitude,
            c.longitude,
            c.weight_lbs,
            c.quantity,
            c.depth_fathoms,
            c.fishing_method,
            c.water_temp_f,
            fc.name as conditions_name,
            c.source,
            c.source_id,
            ST_AsGeoJSON(c.location)::json as geojson
        FROM catches c
        LEFT JOIN species s ON c.species_id = s.id
        LEFT JOIN fishing_conditions fc ON c.conditions_id = fc.id
        WHERE 1=1
    """
    params = {}

    # Apply filters
    if date_from:
        query += " AND c.catch_date >= :date_from"
        params["date_from"] = date_from

    if date_to:
        query += " AND c.catch_date <= :date_to"
        params["date_to"] = date_to

    if year:
        query += " AND EXTRACT(YEAR FROM c.catch_date) = :year"
        params["year"] = year

    if species:
        species_list = [s.strip().upper() for s in species.split(",")]
        query += " AND s.species_code = ANY(:species_codes)"
        params["species_codes"] = species_list

    if conditions:
        conditions_list = [c.strip().lower() for c in conditions.split(",")]
        query += " AND LOWER(fc.name) = ANY(:conditions)"
        params["conditions"] = conditions_list

    if source:
        source_list = [s.strip().lower() for s in source.split(",")]
        query += " AND LOWER(c.source) = ANY(:sources)"
        params["sources"] = source_list

    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                sw_lng, sw_lat, ne_lng, ne_lat = coords
                query += """
                    AND ST_Within(
                        c.location,
                        ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326)
                    )
                """
                params["sw_lng"] = sw_lng
                params["sw_lat"] = sw_lat
                params["ne_lng"] = ne_lng
                params["ne_lat"] = ne_lat
        except ValueError:
            pass

    # Add ordering and pagination
    query += " ORDER BY c.catch_date DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    # Execute query
    result = db.execute(text(query), params)
    rows = result.fetchall()

    # Build GeoJSON features
    features = []
    for row in rows:
        feature = {
            "type": "Feature",
            "geometry": row.geojson if row.geojson else {"type": "Point", "coordinates": [float(row.longitude or 0), float(row.latitude or 0)]},
            "properties": {
                "id": row.id,
                "catch_date": row.catch_date.isoformat() if row.catch_date else None,
                "species_name": row.species_name,
                "species_code": row.species_code,
                "color_hex": row.color_hex or "#808080",
                "weight_lbs": float(row.weight_lbs) if row.weight_lbs else None,
                "quantity": row.quantity or 1,
                "depth_fathoms": row.depth_fathoms,
                "water_temp_f": float(row.water_temp_f) if row.water_temp_f else None,
                "fishing_method": row.fishing_method,
                "conditions": row.conditions_name,
                "source": row.source,
                "source_id": row.source_id
            }
        }
        features.append(feature)

    # Get metadata (counts)
    count_query = """
        SELECT
            COUNT(*) as total_catches,
            COUNT(DISTINCT c.catch_date) as fishing_days,
            COUNT(DISTINCT c.species_id) as species_count,
            MIN(c.catch_date) as min_date,
            MAX(c.catch_date) as max_date
        FROM catches c
        LEFT JOIN species s ON c.species_id = s.id
        LEFT JOIN fishing_conditions fc ON c.conditions_id = fc.id
        WHERE 1=1
    """
    # Apply same filters for count (excluding limit/offset)
    count_params = {k: v for k, v in params.items() if k not in ["limit", "offset"]}

    if date_from:
        count_query += " AND c.catch_date >= :date_from"
    if date_to:
        count_query += " AND c.catch_date <= :date_to"
    if year:
        count_query += " AND EXTRACT(YEAR FROM c.catch_date) = :year"
    if species:
        count_query += " AND s.species_code = ANY(:species_codes)"
    if conditions:
        count_query += " AND LOWER(fc.name) = ANY(:conditions)"
    if source:
        count_query += " AND LOWER(c.source) = ANY(:sources)"
    if bbox and len(coords) == 4:
        count_query += """
            AND ST_Within(
                c.location,
                ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326)
            )
        """

    count_result = db.execute(text(count_query), count_params).fetchone()

    metadata = {
        "total_catches": count_result.total_catches or 0,
        "fishing_days": count_result.fishing_days or 0,
        "species_count": count_result.species_count or 0,
        "date_range": {
            "start": count_result.min_date.isoformat() if count_result.min_date else None,
            "end": count_result.max_date.isoformat() if count_result.max_date else None
        }
    }

    return {
        "type": "FeatureCollection",
        "metadata": metadata,
        "features": features
    }


@router.get("/stats")
def get_catch_stats(db: Session = Depends(get_db), _auth: dict = Depends(require_api_access)):
    """Get aggregated catch statistics by species"""
    query = """
        SELECT
            s.common_name as species_name,
            s.species_code,
            s.color_hex,
            COUNT(*) as total_catches,
            COUNT(DISTINCT c.catch_date) as fishing_days,
            COALESCE(SUM(c.weight_lbs), 0) as total_weight_lbs,
            COALESCE(AVG(c.weight_lbs), 0) as avg_weight_lbs,
            MIN(c.catch_date) as first_catch,
            MAX(c.catch_date) as last_catch
        FROM catches c
        JOIN species s ON c.species_id = s.id
        GROUP BY s.id, s.common_name, s.species_code, s.color_hex
        ORDER BY total_catches DESC
    """
    result = db.execute(text(query))
    rows = result.fetchall()

    stats = []
    for row in rows:
        stats.append({
            "species_name": row.species_name,
            "species_code": row.species_code,
            "color_hex": row.color_hex,
            "total_catches": row.total_catches,
            "fishing_days": row.fishing_days,
            "total_weight_lbs": float(row.total_weight_lbs),
            "avg_weight_lbs": float(row.avg_weight_lbs),
            "first_catch": row.first_catch.isoformat() if row.first_catch else None,
            "last_catch": row.last_catch.isoformat() if row.last_catch else None
        })

    return {"stats": stats}
