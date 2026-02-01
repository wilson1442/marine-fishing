"""
AIS Vessel Tracking API Routes
Exposes live vessel positions, tracks, fishing activity detection,
loitering detection, AIS presence, and fishing effort heatmap.
Powered by aisstream.io AIS data.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import date, datetime

from app.api.deps import get_db

router = APIRouter()


# ------------------------------------------------------------------
# Live Vessel Positions
# ------------------------------------------------------------------

@router.get("/live")
def get_live_vessels(
    bbox: Optional[str] = Query(None, description="SW_lng,SW_lat,NE_lng,NE_lat"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db)
):
    """Get latest position per vessel as GeoJSON for map display."""
    query = """
        SELECT DISTINCT ON (v.mmsi)
            v.mmsi, v.vessel_name, v.flag_country, v.vessel_type, v.gear_type,
            vp.speed_knots, vp.course, vp.heading, vp.nav_status,
            vp.received_at,
            ST_Y(vp.location) as latitude,
            ST_X(vp.location) as longitude,
            ST_AsGeoJSON(vp.location)::json as geojson
        FROM vessel_positions vp
        JOIN vessels v ON v.mmsi = vp.mmsi
        WHERE vp.received_at > NOW() - INTERVAL '24 hours'
    """
    params = {}

    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(vp.location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY v.mmsi, vp.received_at DESC LIMIT :limit"
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.longitude or 0), float(row.latitude or 0)]},
            "properties": {
                "mmsi": row.mmsi,
                "vessel_name": row.vessel_name,
                "flag_country": row.flag_country,
                "vessel_type": row.vessel_type,
                "gear_type": row.gear_type,
                "speed_knots": float(row.speed_knots) if row.speed_knots else None,
                "course": float(row.course) if row.course else None,
                "heading": float(row.heading) if row.heading else None,
                "nav_status": row.nav_status,
                "received_at": row.received_at.isoformat() if row.received_at else None,
                "layer": "live_vessels",
                "color": "#ff6b35",
            }
        })

    return {
        "type": "FeatureCollection",
        "metadata": {"total": len(features), "source": "AIS Stream", "layer": "live_vessels"},
        "features": features
    }


# ------------------------------------------------------------------
# Vessel Tracks
# ------------------------------------------------------------------

@router.get("/tracks/{mmsi}")
def get_vessel_tracks(
    mmsi: str,
    hours: int = Query(24, ge=1, le=168, description="Hours of track history"),
    db: Session = Depends(get_db)
):
    """Get position history for a vessel as GeoJSON LineString."""
    result = db.execute(text("""
        SELECT
            ST_Y(location) as latitude,
            ST_X(location) as longitude,
            speed_knots, course, heading, nav_status, received_at
        FROM vessel_positions
        WHERE mmsi = :mmsi
          AND received_at > NOW() - MAKE_INTERVAL(hours => :hours)
        ORDER BY received_at ASC
    """), {"mmsi": mmsi, "hours": hours})
    rows = result.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No track data found for this vessel")

    coordinates = []
    timestamps = []
    for row in rows:
        coordinates.append([float(row.longitude), float(row.latitude)])
        timestamps.append(row.received_at.isoformat() if row.received_at else None)

    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coordinates
        },
        "properties": {
            "mmsi": mmsi,
            "point_count": len(coordinates),
            "timestamps": timestamps,
            "hours": hours,
        }
    }


# ------------------------------------------------------------------
# Vessel Search
# ------------------------------------------------------------------

@router.get("/search")
def search_vessels(
    query_str: Optional[str] = Query(None, alias="q", description="Search by name, MMSI, or flag"),
    flag: Optional[str] = Query(None),
    gear_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Search vessels in the database."""
    query = """
        SELECT
            id, mmsi, imo, vessel_name, flag_country, vessel_type,
            length_meters, gross_tonnage, gear_type, source,
            ST_Y(last_position) as latitude,
            ST_X(last_position) as longitude,
            last_seen,
            ST_AsGeoJSON(last_position)::json as geojson
        FROM vessels
        WHERE 1=1
    """
    params = {}

    if query_str:
        query += " AND (vessel_name ILIKE :q OR mmsi ILIKE :q OR imo ILIKE :q)"
        params["q"] = f"%{query_str}%"
    if flag:
        query += " AND flag_country = :flag"
        params["flag"] = flag.upper()
    if gear_type:
        query += " AND gear_type ILIKE :gear"
        params["gear"] = f"%{gear_type}%"
    if source:
        query += " AND source = :source"
        params["source"] = source

    query += " ORDER BY last_seen DESC NULLS LAST LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = db.execute(text(query), params)
    rows = result.fetchall()

    vessels = []
    for row in rows:
        vessels.append({
            "id": row.id,
            "mmsi": row.mmsi,
            "imo": row.imo,
            "vessel_name": row.vessel_name,
            "flag_country": row.flag_country,
            "vessel_type": row.vessel_type,
            "length_meters": float(row.length_meters) if row.length_meters else None,
            "gross_tonnage": row.gross_tonnage,
            "gear_type": row.gear_type,
            "source": row.source,
            "latitude": float(row.latitude) if row.latitude else None,
            "longitude": float(row.longitude) if row.longitude else None,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
            "geojson": row.geojson,
        })

    total = db.execute(text("SELECT COUNT(*) FROM vessels")).scalar() or 0

    return {
        "vessels": vessels,
        "metadata": {"total": total, "source": "AIS Stream"}
    }


# ------------------------------------------------------------------
# Vessel Detail
# ------------------------------------------------------------------

@router.get("/{mmsi}")
def get_vessel_detail(mmsi: str, db: Session = Depends(get_db)):
    """Get detailed vessel info by MMSI with activity stats."""
    result = db.execute(text("""
        SELECT
            v.id, v.mmsi, v.imo, v.vessel_name, v.flag_country, v.vessel_type,
            v.length_meters, v.gross_tonnage, v.gear_type, v.source, v.metadata,
            ST_Y(v.last_position) as latitude,
            ST_X(v.last_position) as longitude,
            v.last_seen,
            (SELECT COUNT(*) FROM detected_fishing_events fe WHERE fe.mmsi = v.mmsi) as fishing_event_count,
            (SELECT COUNT(*) FROM detected_loitering_events le WHERE le.mmsi = v.mmsi) as loitering_event_count,
            (SELECT COALESCE(SUM(fe.duration_hours), 0) FROM detected_fishing_events fe WHERE fe.mmsi = v.mmsi) as total_fishing_hours
        FROM vessels v
        WHERE v.mmsi = :mmsi
    """), {"mmsi": mmsi}).fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Vessel not found")

    return {
        "id": result.id,
        "mmsi": result.mmsi,
        "imo": result.imo,
        "vessel_name": result.vessel_name,
        "flag_country": result.flag_country,
        "vessel_type": result.vessel_type,
        "length_meters": float(result.length_meters) if result.length_meters else None,
        "gross_tonnage": result.gross_tonnage,
        "gear_type": result.gear_type,
        "source": result.source,
        "latitude": float(result.latitude) if result.latitude else None,
        "longitude": float(result.longitude) if result.longitude else None,
        "last_seen": result.last_seen.isoformat() if result.last_seen else None,
        "fishing_event_count": result.fishing_event_count or 0,
        "loitering_event_count": result.loitering_event_count or 0,
        "total_fishing_hours": float(result.total_fishing_hours) if result.total_fishing_hours else 0,
    }


# ------------------------------------------------------------------
# Detected Fishing Activity
# ------------------------------------------------------------------

@router.get("/fishing-activity")
def get_fishing_activity(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    vessel_mmsi: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None, description="SW_lng,SW_lat,NE_lng,NE_lat"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get detected fishing activity as GeoJSON."""
    query = """
        SELECT
            fe.id, fe.mmsi, v.vessel_name, v.flag_country, v.gear_type,
            fe.start_time, fe.end_time, fe.duration_hours,
            fe.avg_speed_knots, fe.detection_method,
            ST_Y(fe.location) as latitude,
            ST_X(fe.location) as longitude,
            ST_AsGeoJSON(fe.location)::json as geojson
        FROM detected_fishing_events fe
        LEFT JOIN vessels v ON v.mmsi = fe.mmsi
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND fe.start_time >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND fe.start_time <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if vessel_mmsi:
        query += " AND fe.mmsi = :mmsi"
        params["mmsi"] = vessel_mmsi
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(fe.location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY fe.start_time DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.longitude or 0), float(row.latitude or 0)]},
            "properties": {
                "id": row.id,
                "mmsi": row.mmsi,
                "vessel_name": row.vessel_name,
                "flag_country": row.flag_country,
                "gear_type": row.gear_type,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "duration_hours": float(row.duration_hours) if row.duration_hours else None,
                "avg_speed_knots": float(row.avg_speed_knots) if row.avg_speed_knots else None,
                "detection_method": row.detection_method,
                "layer": "fishing_activity",
                "color": "#ff6b35",
            }
        })

    count_query = "SELECT COUNT(*) FROM detected_fishing_events"
    total = db.execute(text(count_query)).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "AIS Stream", "layer": "fishing_activity"},
        "features": features
    }


# ------------------------------------------------------------------
# Detected Loitering
# ------------------------------------------------------------------

@router.get("/loitering")
def get_loitering_events(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    vessel_mmsi: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get detected loitering events as GeoJSON."""
    query = """
        SELECT
            le.id, le.mmsi, v.vessel_name, v.flag_country, v.vessel_type,
            le.start_time, le.end_time, le.duration_hours,
            le.avg_speed_knots,
            ST_Y(le.location) as latitude,
            ST_X(le.location) as longitude,
            ST_AsGeoJSON(le.location)::json as geojson
        FROM detected_loitering_events le
        LEFT JOIN vessels v ON v.mmsi = le.mmsi
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND le.start_time >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND le.start_time <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if vessel_mmsi:
        query += " AND le.mmsi = :mmsi"
        params["mmsi"] = vessel_mmsi
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(le.location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY le.start_time DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.longitude or 0), float(row.latitude or 0)]},
            "properties": {
                "id": row.id,
                "mmsi": row.mmsi,
                "vessel_name": row.vessel_name,
                "flag_country": row.flag_country,
                "vessel_type": row.vessel_type,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "duration_hours": float(row.duration_hours) if row.duration_hours else None,
                "avg_speed_knots": float(row.avg_speed_knots) if row.avg_speed_knots else None,
                "layer": "loitering",
                "color": "#ffd166",
            }
        })

    total = db.execute(text("SELECT COUNT(*) FROM detected_loitering_events")).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "AIS Stream", "layer": "loitering"},
        "features": features
    }


# ------------------------------------------------------------------
# AIS Presence (aggregated from vessel_positions)
# ------------------------------------------------------------------

@router.get("/presence")
def get_ais_presence(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    bbox: Optional[str] = Query(None),
    resolution: float = Query(0.1, description="Grid cell size in degrees"),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db)
):
    """Get AIS vessel presence data aggregated from position history."""
    query = """
        SELECT
            ROUND(CAST(ST_Y(location) / :res AS NUMERIC), 0) * :res as lat_bin,
            ROUND(CAST(ST_X(location) / :res AS NUMERIC), 0) * :res as lon_bin,
            COUNT(DISTINCT mmsi) as vessel_count,
            COUNT(*) as position_count,
            EXTRACT(EPOCH FROM (MAX(received_at) - MIN(received_at))) / 3600.0 as hours_total
        FROM vessel_positions
        WHERE 1=1
    """
    params = {"res": resolution}

    if date_from:
        query += " AND received_at >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND received_at <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += """
        GROUP BY lat_bin, lon_bin
        ORDER BY hours_total DESC
        LIMIT :limit
    """
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        hours = float(row.hours_total) if row.hours_total else 0
        intensity = min(1.0, hours / 100.0)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [float(row.lon_bin), float(row.lat_bin)]},
            "properties": {
                "vessel_count": row.vessel_count or 0,
                "position_count": row.position_count or 0,
                "hours_total": round(hours, 1),
                "intensity": round(intensity, 3),
                "layer": "ais_presence",
            }
        })

    return {
        "type": "FeatureCollection",
        "metadata": {"total": len(features), "source": "AIS Stream", "layer": "ais_presence"},
        "features": features
    }


# ------------------------------------------------------------------
# Fishing Effort Heatmap
# ------------------------------------------------------------------

@router.get("/effort-heatmap")
def get_effort_heatmap(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    gear_type: Optional[str] = Query(None),
    flag_country: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db)
):
    """Get fishing effort heatmap data."""
    query = """
        SELECT
            cell_id, date, lat_bin, lon_bin,
            fishing_hours, vessel_count, gear_type, flag_country,
            ST_AsGeoJSON(location)::json as geojson
        FROM fishing_effort
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND date >= :date_from"
        params["date_from"] = date_from
    if date_to:
        query += " AND date <= :date_to"
        params["date_to"] = date_to
    if gear_type:
        query += " AND gear_type ILIKE :gear"
        params["gear"] = f"%{gear_type}%"
    if flag_country:
        query += " AND flag_country = :flag"
        params["flag"] = flag_country.upper()
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY fishing_hours DESC LIMIT :limit"
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        intensity = min(1.0, (float(row.fishing_hours or 0)) / 50.0)
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.lon_bin or 0), float(row.lat_bin or 0)]},
            "properties": {
                "cell_id": row.cell_id,
                "date": row.date.isoformat() if row.date else None,
                "fishing_hours": float(row.fishing_hours) if row.fishing_hours else 0,
                "vessel_count": row.vessel_count or 0,
                "gear_type": row.gear_type,
                "flag_country": row.flag_country,
                "intensity": round(intensity, 3),
                "layer": "effort_heatmap",
            }
        })

    total = db.execute(text("SELECT COUNT(*) FROM fishing_effort")).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "AIS Stream", "layer": "effort_heatmap"},
        "features": features
    }


# ------------------------------------------------------------------
# Summary Stats
# ------------------------------------------------------------------

@router.get("/summary")
def get_vessels_summary(db: Session = Depends(get_db)):
    """Get summary statistics for all AIS vessel data."""
    stats = {}

    queries = {
        "live_vessels": "SELECT COUNT(DISTINCT mmsi) FROM vessel_positions WHERE received_at > NOW() - INTERVAL '24 hours'",
        "fishing_events": "SELECT COUNT(*) FROM detected_fishing_events",
        "loitering_events": "SELECT COUNT(*) FROM detected_loitering_events",
        "vessels": "SELECT COUNT(*) FROM vessels WHERE source = 'aisstream'",
        "total_positions": "SELECT COUNT(*) FROM vessel_positions",
        "fishing_effort_cells": "SELECT COUNT(*) FROM fishing_effort",
    }

    for key, q in queries.items():
        try:
            stats[key] = db.execute(text(q)).scalar() or 0
        except Exception:
            stats[key] = 0

    try:
        effort_stats = db.execute(text("""
            SELECT
                COALESCE(SUM(fishing_hours), 0) as total_fishing_hours,
                COALESCE(SUM(vessel_count), 0) as total_vessel_observations,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM fishing_effort
        """)).fetchone()
        stats["total_fishing_hours"] = float(effort_stats.total_fishing_hours)
        stats["total_vessel_observations"] = int(effort_stats.total_vessel_observations)
        stats["date_range"] = {
            "start": effort_stats.earliest_date.isoformat() if effort_stats.earliest_date else None,
            "end": effort_stats.latest_date.isoformat() if effort_stats.latest_date else None,
        }
    except Exception:
        stats["total_fishing_hours"] = 0
        stats["total_vessel_observations"] = 0
        stats["date_range"] = {"start": None, "end": None}

    return {
        "source": "AIS Stream",
        "stats": stats,
    }
