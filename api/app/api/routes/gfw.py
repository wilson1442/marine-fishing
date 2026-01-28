"""
Global Fishing Watch API Routes
Exposes GFW data: fishing events, loitering, vessel search/identity,
vessel insights, SAR detections, offshore infrastructure, AIS presence,
and fishing effort heatmap.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional
from datetime import date, datetime

from app.api.deps import get_db

router = APIRouter()


# ------------------------------------------------------------------
# GFW Fishing Events
# ------------------------------------------------------------------

@router.get("/fishing-events")
def get_fishing_events(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    vessel_mmsi: Optional[str] = Query(None),
    gear_type: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None, description="SW_lng,SW_lat,NE_lng,NE_lat"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get GFW fishing events as GeoJSON for map display."""
    query = """
        SELECT
            event_id, event_type, vessel_name, vessel_mmsi, vessel_flag,
            vessel_gear_type, start_time, end_time, duration_hours,
            latitude, longitude, fishing_hours,
            distance_from_shore_km, distance_from_port_km,
            ST_AsGeoJSON(location)::json as geojson
        FROM gfw_fishing_events
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND start_time >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND start_time <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if vessel_mmsi:
        query += " AND vessel_mmsi = :mmsi"
        params["mmsi"] = vessel_mmsi
    if gear_type:
        query += " AND vessel_gear_type ILIKE :gear"
        params["gear"] = f"%{gear_type}%"
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY start_time DESC LIMIT :limit OFFSET :offset"
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
                "event_id": row.event_id,
                "event_type": row.event_type,
                "vessel_name": row.vessel_name,
                "vessel_mmsi": row.vessel_mmsi,
                "vessel_flag": row.vessel_flag,
                "gear_type": row.vessel_gear_type,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "duration_hours": float(row.duration_hours) if row.duration_hours else None,
                "fishing_hours": float(row.fishing_hours) if row.fishing_hours else None,
                "distance_from_shore_km": float(row.distance_from_shore_km) if row.distance_from_shore_km else None,
                "distance_from_port_km": float(row.distance_from_port_km) if row.distance_from_port_km else None,
                "layer": "fishing_events",
                "color": "#ff6b35",
            }
        })

    # Get count
    count_query = "SELECT COUNT(*) as total FROM gfw_fishing_events WHERE 1=1"
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    if date_from:
        count_query += " AND start_time >= :date_from"
    if date_to:
        count_query += " AND start_time <= :date_to"
    if vessel_mmsi:
        count_query += " AND vessel_mmsi = :mmsi"
    if gear_type:
        count_query += " AND vessel_gear_type ILIKE :gear"
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                count_query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
        except ValueError:
            pass

    total = db.execute(text(count_query), count_params).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch", "layer": "fishing_events"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW Loitering Events
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
    """Get GFW loitering events as GeoJSON."""
    query = """
        SELECT
            event_id, vessel_name, vessel_mmsi, vessel_flag, vessel_type,
            start_time, end_time, duration_hours,
            latitude, longitude,
            total_distance_km, avg_speed_knots, avg_distance_from_shore_km,
            ST_AsGeoJSON(location)::json as geojson
        FROM gfw_loitering_events
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND start_time >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND start_time <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if vessel_mmsi:
        query += " AND vessel_mmsi = :mmsi"
        params["mmsi"] = vessel_mmsi
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY start_time DESC LIMIT :limit OFFSET :offset"
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
                "event_id": row.event_id,
                "vessel_name": row.vessel_name,
                "vessel_mmsi": row.vessel_mmsi,
                "vessel_flag": row.vessel_flag,
                "vessel_type": row.vessel_type,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "duration_hours": float(row.duration_hours) if row.duration_hours else None,
                "total_distance_km": float(row.total_distance_km) if row.total_distance_km else None,
                "avg_speed_knots": float(row.avg_speed_knots) if row.avg_speed_knots else None,
                "layer": "loitering",
                "color": "#ffd166",
            }
        })

    total = db.execute(text(
        "SELECT COUNT(*) FROM gfw_loitering_events"
    )).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch", "layer": "loitering"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW Vessel Search & Identity
# ------------------------------------------------------------------

@router.get("/vessels")
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
        "metadata": {"total": total, "source": "Global Fishing Watch + Marine Cadastre"}
    }


@router.get("/vessels/{mmsi}")
def get_vessel_identity(mmsi: str, db: Session = Depends(get_db)):
    """Get detailed vessel identity by MMSI."""
    result = db.execute(text("""
        SELECT
            v.id, v.mmsi, v.imo, v.vessel_name, v.flag_country, v.vessel_type,
            v.length_meters, v.gross_tonnage, v.gear_type, v.source, v.metadata,
            ST_Y(v.last_position) as latitude,
            ST_X(v.last_position) as longitude,
            v.last_seen,
            (SELECT COUNT(*) FROM gfw_fishing_events fe WHERE fe.vessel_mmsi = v.mmsi) as fishing_event_count,
            (SELECT COUNT(*) FROM gfw_loitering_events le WHERE le.vessel_mmsi = v.mmsi) as loitering_event_count,
            (SELECT SUM(fe.fishing_hours) FROM gfw_fishing_events fe WHERE fe.vessel_mmsi = v.mmsi) as total_fishing_hours
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
# GFW Vessel Insights
# ------------------------------------------------------------------

@router.get("/insights")
def get_vessel_insights(
    vessel_mmsi: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    """Get vessel insights (fused analysis data)."""
    query = """
        SELECT
            vessel_id, vessel_mmsi, vessel_name, vessel_flag,
            vessel_gear_type, vessel_type,
            apparent_fishing_hours, active_hours,
            fishing_events_count, loitering_events_count,
            encounter_events_count, port_visit_count,
            coverage_percentage, gaps_count,
            analysis_period_start, analysis_period_end
        FROM gfw_vessel_insights
        WHERE 1=1
    """
    params = {}

    if vessel_mmsi:
        query += " AND vessel_mmsi = :mmsi"
        params["mmsi"] = vessel_mmsi

    query += " ORDER BY apparent_fishing_hours DESC NULLS LAST LIMIT :limit"
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    insights = []
    for row in rows:
        insights.append({
            "vessel_id": row.vessel_id,
            "vessel_mmsi": row.vessel_mmsi,
            "vessel_name": row.vessel_name,
            "vessel_flag": row.vessel_flag,
            "gear_type": row.vessel_gear_type,
            "vessel_type": row.vessel_type,
            "apparent_fishing_hours": float(row.apparent_fishing_hours) if row.apparent_fishing_hours else 0,
            "active_hours": float(row.active_hours) if row.active_hours else 0,
            "fishing_events_count": row.fishing_events_count or 0,
            "loitering_events_count": row.loitering_events_count or 0,
            "encounter_events_count": row.encounter_events_count or 0,
            "port_visit_count": row.port_visit_count or 0,
            "coverage_percentage": float(row.coverage_percentage) if row.coverage_percentage else 0,
            "gaps_count": row.gaps_count or 0,
            "analysis_period": {
                "start": row.analysis_period_start.isoformat() if row.analysis_period_start else None,
                "end": row.analysis_period_end.isoformat() if row.analysis_period_end else None,
            }
        })

    return {
        "insights": insights,
        "metadata": {"total": len(insights), "source": "Global Fishing Watch"}
    }


# ------------------------------------------------------------------
# GFW SAR Vessel Detections
# ------------------------------------------------------------------

@router.get("/sar-detections")
def get_sar_detections(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    bbox: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db)
):
    """Get SAR (Synthetic Aperture Radar) vessel detections as GeoJSON."""
    query = """
        SELECT
            detection_id, detection_time,
            latitude, longitude,
            matched_vessel_mmsi, matched_vessel_name, matched_vessel_flag,
            confidence, source_satellite, is_matched,
            distance_from_shore_km,
            ST_AsGeoJSON(location)::json as geojson
        FROM gfw_sar_detections
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND detection_time >= :date_from"
        params["date_from"] = datetime.combine(date_from, datetime.min.time())
    if date_to:
        query += " AND detection_time <= :date_to"
        params["date_to"] = datetime.combine(date_to, datetime.max.time())
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY detection_time DESC LIMIT :limit OFFSET :offset"
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
                "detection_id": row.detection_id,
                "detection_time": row.detection_time.isoformat() if row.detection_time else None,
                "matched_vessel_mmsi": row.matched_vessel_mmsi,
                "matched_vessel_name": row.matched_vessel_name,
                "matched_vessel_flag": row.matched_vessel_flag,
                "confidence": float(row.confidence) if row.confidence else None,
                "source_satellite": row.source_satellite,
                "is_matched": row.is_matched,
                "distance_from_shore_km": float(row.distance_from_shore_km) if row.distance_from_shore_km else None,
                "layer": "sar_detections",
                "color": "#ef476f",
            }
        })

    total = db.execute(text("SELECT COUNT(*) FROM gfw_sar_detections")).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch SAR", "layer": "sar_detections"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW Offshore Fixed Infrastructure
# ------------------------------------------------------------------

@router.get("/infrastructure")
def get_offshore_infrastructure(
    bbox: Optional[str] = Query(None),
    structure_type: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db)
):
    """Get offshore fixed infrastructure (oil rigs, platforms, wind farms) as GeoJSON."""
    query = """
        SELECT
            structure_id, structure_type,
            latitude, longitude,
            first_detected, last_detected, detection_count,
            confidence, distance_from_shore_km, region,
            ST_AsGeoJSON(location)::json as geojson
        FROM gfw_offshore_infrastructure
        WHERE 1=1
    """
    params = {}

    if structure_type:
        query += " AND structure_type ILIKE :stype"
        params["stype"] = f"%{structure_type}%"
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY last_detected DESC NULLS LAST LIMIT :limit"
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.longitude or 0), float(row.latitude or 0)]},
            "properties": {
                "structure_id": row.structure_id,
                "structure_type": row.structure_type,
                "first_detected": row.first_detected.isoformat() if row.first_detected else None,
                "last_detected": row.last_detected.isoformat() if row.last_detected else None,
                "detection_count": row.detection_count,
                "confidence": float(row.confidence) if row.confidence else None,
                "distance_from_shore_km": float(row.distance_from_shore_km) if row.distance_from_shore_km else None,
                "region": row.region,
                "layer": "infrastructure",
                "color": "#06d6a0",
            }
        })

    total = db.execute(text("SELECT COUNT(*) FROM gfw_offshore_infrastructure")).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch", "layer": "infrastructure"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW AIS Vessel Presence (Heatmap data)
# ------------------------------------------------------------------

@router.get("/ais-presence")
def get_ais_presence(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    vessel_type: Optional[str] = Query(None),
    bbox: Optional[str] = Query(None),
    limit: int = Query(2000, ge=1, le=10000),
    db: Session = Depends(get_db)
):
    """Get AIS vessel presence data for heatmap display."""
    query = """
        SELECT
            cell_id, date, lat_bin, lon_bin,
            vessel_count, fishing_vessel_count,
            hours_total, fishing_hours,
            vessel_type, gear_type,
            ST_AsGeoJSON(location)::json as geojson
        FROM gfw_ais_presence
        WHERE 1=1
    """
    params = {}

    if date_from:
        query += " AND date >= :date_from"
        params["date_from"] = date_from
    if date_to:
        query += " AND date <= :date_to"
        params["date_to"] = date_to
    if vessel_type:
        query += " AND vessel_type ILIKE :vtype"
        params["vtype"] = f"%{vessel_type}%"
    if bbox:
        try:
            coords = [float(x.strip()) for x in bbox.split(",")]
            if len(coords) == 4:
                query += " AND ST_Within(location, ST_MakeEnvelope(:sw_lng, :sw_lat, :ne_lng, :ne_lat, 4326))"
                params["sw_lng"], params["sw_lat"], params["ne_lng"], params["ne_lat"] = coords
        except ValueError:
            pass

    query += " ORDER BY hours_total DESC LIMIT :limit"
    params["limit"] = limit

    result = db.execute(text(query), params)
    rows = result.fetchall()

    features = []
    for row in rows:
        intensity = min(1.0, (float(row.hours_total or 0)) / 100.0)
        features.append({
            "type": "Feature",
            "geometry": row.geojson or {"type": "Point", "coordinates": [float(row.lon_bin or 0), float(row.lat_bin or 0)]},
            "properties": {
                "cell_id": row.cell_id,
                "date": row.date.isoformat() if row.date else None,
                "vessel_count": row.vessel_count or 0,
                "fishing_vessel_count": row.fishing_vessel_count or 0,
                "hours_total": float(row.hours_total) if row.hours_total else 0,
                "fishing_hours": float(row.fishing_hours) if row.fishing_hours else 0,
                "vessel_type": row.vessel_type,
                "gear_type": row.gear_type,
                "intensity": round(intensity, 3),
                "layer": "ais_presence",
            }
        })

    total = db.execute(text("SELECT COUNT(*) FROM gfw_ais_presence")).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch AIS", "layer": "ais_presence"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW Fishing Effort Heatmap
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
    """Get fishing effort heatmap data from GFW 4Wings."""
    query = """
        SELECT
            cell_id, date, lat_bin, lon_bin,
            fishing_hours, vessel_count, gear_type, flag_country,
            ST_AsGeoJSON(location)::json as geojson
        FROM fishing_effort
        WHERE source = 'gfw'
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

    total = db.execute(text(
        "SELECT COUNT(*) FROM fishing_effort WHERE source = 'gfw'"
    )).scalar() or 0

    return {
        "type": "FeatureCollection",
        "metadata": {"total": total, "source": "Global Fishing Watch 4Wings", "layer": "effort_heatmap"},
        "features": features
    }


# ------------------------------------------------------------------
# GFW Summary Dashboard Stats
# ------------------------------------------------------------------

@router.get("/summary")
def get_gfw_summary(db: Session = Depends(get_db)):
    """Get summary statistics for all GFW data."""
    stats = {}

    queries = {
        "fishing_events": "SELECT COUNT(*) FROM gfw_fishing_events",
        "loitering_events": "SELECT COUNT(*) FROM gfw_loitering_events",
        "vessels": "SELECT COUNT(*) FROM vessels WHERE source = 'gfw'",
        "sar_detections": "SELECT COUNT(*) FROM gfw_sar_detections",
        "infrastructure": "SELECT COUNT(*) FROM gfw_offshore_infrastructure",
        "ais_presence_cells": "SELECT COUNT(*) FROM gfw_ais_presence",
        "fishing_effort_cells": "SELECT COUNT(*) FROM fishing_effort WHERE source = 'gfw'",
        "vessel_insights": "SELECT COUNT(*) FROM gfw_vessel_insights",
    }

    for key, q in queries.items():
        try:
            stats[key] = db.execute(text(q)).scalar() or 0
        except Exception:
            stats[key] = 0

    # Additional aggregations
    try:
        effort_stats = db.execute(text("""
            SELECT
                COALESCE(SUM(fishing_hours), 0) as total_fishing_hours,
                COALESCE(SUM(vessel_count), 0) as total_vessel_observations,
                MIN(date) as earliest_date,
                MAX(date) as latest_date
            FROM fishing_effort WHERE source = 'gfw'
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
        "source": "Global Fishing Watch",
        "api_version": "v3",
        "stats": stats,
    }
