"""Bite windows API - regional aggregated scores with HOT/WARM/COOL/COLD labels."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("")
def get_bite_windows(
    species_code: Optional[str] = Query(None, description="Filter by species code"),
    region: Optional[str] = Query(None, description="Filter by region name"),
    label: Optional[str] = Query(None, description="Filter by label (HOT/WARM/COOL/COLD)"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Regional bite windows with species-by-species HOT/WARM/COOL/COLD labels."""
    params = {}
    filters = []

    if species_code:
        filters.append("s.species_code = :code")
        params["code"] = species_code.upper()
    if region:
        filters.append("pr.name ILIKE :region")
        params["region"] = f"%{region}%"
    if label:
        filters.append("rbw.label = :label")
        params["label"] = label.upper()

    where = ""
    if filters:
        where = "AND " + " AND ".join(filters)

    rows = db.execute(text(f"""
        SELECT pr.name as region_name, pr.region_type,
               s.species_code, s.common_name, s.color_hex,
               rbw.avg_probability, rbw.max_probability,
               rbw.cell_count, rbw.label, rbw.reason_summary,
               rbw.computed_at
        FROM region_bite_windows rbw
        JOIN pelagic_regions pr ON pr.id = rbw.region_id
        JOIN species s ON s.id = rbw.species_id
        WHERE rbw.computed_at = (
            SELECT MAX(computed_at) FROM region_bite_windows
        )
        {where}
        ORDER BY rbw.avg_probability DESC
    """), params).fetchall()

    return {
        "bite_windows": [
            {
                "region": r.region_name,
                "region_type": r.region_type,
                "species_code": r.species_code,
                "species_name": r.common_name,
                "color_hex": r.color_hex,
                "avg_probability": round(float(r.avg_probability), 1) if r.avg_probability else 0,
                "max_probability": round(float(r.max_probability), 1) if r.max_probability else 0,
                "cell_count": r.cell_count,
                "label": r.label,
                "reason_summary": r.reason_summary,
                "computed_at": str(r.computed_at),
            }
            for r in rows
        ],
        "count": len(rows),
    }
