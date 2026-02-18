"""
Marine Alerts API Routes
Serves NWS marine weather alerts for inshore fishing intelligence
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/marine")
def get_marine_alerts(
    request: Request,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access)
):
    """Get active marine alerts for monitored zones."""
    rows = db.execute(text("""
        SELECT
            alert_id, zone_id, zone_name, event, severity,
            headline, description, instruction, onset, expires
        FROM marine_alerts
        WHERE is_active = true
          AND (expires IS NULL OR expires > NOW())
        ORDER BY
            CASE severity
                WHEN 'extreme' THEN 1
                WHEN 'severe' THEN 2
                WHEN 'moderate' THEN 3
                WHEN 'minor' THEN 4
                ELSE 5
            END,
            onset DESC
    """)).fetchall()

    alerts = []
    for row in rows:
        alerts.append({
            "alert_id": row.alert_id,
            "zone_id": row.zone_id,
            "zone_name": row.zone_name,
            "event": row.event,
            "severity": row.severity,
            "headline": row.headline,
            "description": row.description,
            "instruction": row.instruction,
            "onset": row.onset.isoformat() if row.onset else None,
            "expires": row.expires.isoformat() if row.expires else None,
        })

    return {"alerts": alerts, "count": len(alerts)}
