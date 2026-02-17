"""Inlet bite index API - per-inlet bite indices for Jones, Fire Island, Debs."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import Optional

from app.api.deps import get_db, require_api_access

router = APIRouter()


@router.get("/bite-index")
def get_inlet_bite_index(
    species_code: Optional[str] = Query(None, description="Filter by species code"),
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Per-inlet bite indices with trend tracking."""
    params = {}
    species_filter = ""
    if species_code:
        species_filter = "AND s.species_code = :code"
        params["code"] = species_code.upper()

    rows = db.execute(text(f"""
        SELECT pr.name as inlet_name,
               s.species_code, s.common_name, s.color_hex,
               isi.bite_index, isi.trend, isi.prev_bite_index,
               isi.top_reason, isi.computed_at
        FROM inlet_species_index isi
        JOIN pelagic_regions pr ON pr.id = isi.region_id
        JOIN species s ON s.id = isi.species_id
        WHERE pr.region_type = 'inlet_zone'
          AND isi.computed_at = (
              SELECT MAX(computed_at) FROM inlet_species_index
          )
          {species_filter}
        ORDER BY pr.name, isi.bite_index DESC
    """), params).fetchall()

    # Group by inlet
    inlets = {}
    for r in rows:
        inlet = r.inlet_name
        if inlet not in inlets:
            inlets[inlet] = []
        inlets[inlet].append({
            "species_code": r.species_code,
            "species_name": r.common_name,
            "color_hex": r.color_hex,
            "bite_index": round(float(r.bite_index), 1) if r.bite_index else 0,
            "trend": r.trend,
            "prev_bite_index": round(float(r.prev_bite_index), 1) if r.prev_bite_index else None,
            "top_reason": r.top_reason,
        })

    return {
        "inlets": inlets,
        "computed_at": str(rows[0].computed_at) if rows else None,
    }
