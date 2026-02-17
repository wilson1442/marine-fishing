"""Pelagic heatmap tile renderer - species probability tiles.
Follows the exact same pattern as weather.py tile rendering.
"""

import math

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.deps import get_db, require_api_access

router = APIRouter()

# Color ramp: blue(0%) -> cyan(40%) -> green(55%) -> yellow(70%) -> orange(85%) -> red(100%)
_PELAGIC_RAMP = [
    (0,   (30,  70, 200)),   # dark blue
    (20,  (50, 130, 220)),   # blue
    (40,  (30, 200, 220)),   # cyan
    (55,  (50, 200,  80)),   # green
    (70,  (240, 220, 40)),   # yellow
    (85,  (240, 150, 30)),   # orange
    (100, (220,  30, 30)),   # red
]

_EMPTY_TILE = None


def _get_empty_tile():
    global _EMPTY_TILE
    if _EMPTY_TILE is None:
        from PIL import Image
        import io
        img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG", compress_level=1)
        _EMPTY_TILE = buf.getvalue()
    return _EMPTY_TILE


def _tile_bounds(z, x, y):
    """Convert tile coords to (west, south, east, north) in EPSG:4326."""
    n = 2 ** z
    west = x / n * 360.0 - 180.0
    east = (x + 1) / n * 360.0 - 180.0
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return west, south, east, north


@router.get("/{species_code}/{z}/{x}/{y}.png")
def get_pelagic_tile(
    species_code: str, z: int, x: int, y: int,
    db: Session = Depends(get_db),
    _auth: dict = Depends(require_api_access),
):
    """Render a 256x256 PNG tile of species probability heatmap."""
    from PIL import Image
    import io
    import numpy as np

    TILE_SIZE = 256
    GRID_STEP = 0.5  # weather grid spacing for margin calc

    west, south, east, north = _tile_bounds(z, x, y)

    # Fetch species scores within tile bounds (with margin for interpolation)
    margin = GRID_STEP * 3
    rows = db.execute(text("""
        SELECT gc.lat, gc.lon, css.probability
        FROM cell_species_scores css
        JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
        JOIN species s ON s.id = css.species_id
        WHERE s.species_code = :code
          AND gc.lat BETWEEN :south AND :north
          AND gc.lon BETWEEN :west AND :east
          AND css.computed_at = (
              SELECT MAX(computed_at) FROM cell_species_scores
          )
          AND css.probability > 0
    """), {
        "code": species_code.upper(),
        "south": south - margin, "north": north + margin,
        "west": west - margin, "east": east + margin,
    }).fetchall()

    if not rows:
        return Response(content=_get_empty_tile(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=900"})

    pts_lat = []
    pts_lon = []
    pts_val = []
    for r in rows:
        pts_lat.append(float(r.lat))
        pts_lon.append(float(r.lon))
        pts_val.append(float(r.probability))

    if not pts_val:
        return Response(content=_get_empty_tile(), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=900"})

    pts_lat = np.array(pts_lat)
    pts_lon = np.array(pts_lon)
    pts_val = np.array(pts_val)

    # Build pixel coordinate grids
    py = np.arange(TILE_SIZE)
    px = np.arange(TILE_SIZE)
    lats = north - (north - south) * py / TILE_SIZE
    lons = west + (east - west) * px / TILE_SIZE
    grid_lat, grid_lon = np.meshgrid(lats, lons, indexing='ij')

    # RBF interpolation
    from scipy.interpolate import RBFInterpolator
    from scipy.spatial import cKDTree, Delaunay

    points = np.column_stack([pts_lat, pts_lon])
    grid_points = np.column_stack([grid_lat.ravel(), grid_lon.ravel()])

    if len(pts_val) >= 4:
        rbf = RBFInterpolator(points, pts_val, kernel='thin_plate_spline', smoothing=0.5)
        result = rbf(grid_points)
    else:
        from scipy.interpolate import griddata as scipy_griddata
        result = scipy_griddata(points, pts_val, grid_points, method='nearest')

    result = result.reshape(TILE_SIZE, TILE_SIZE)

    # Alpha mask: full inside convex hull, fade outside
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import connected_components as cc
    from collections import Counter

    BASE_ALPHA = 160
    FADE_DIST = GRID_STEP * 3.0

    tree = cKDTree(points)

    # Cluster points
    pairs = tree.query_pairs(r=GRID_STEP * 1.5)
    n_pts = len(pts_val)
    if pairs:
        rows_idx, cols_idx = zip(*pairs)
        data = np.ones(len(rows_idx))
        adj = csr_matrix((data, (rows_idx, cols_idx)), shape=(n_pts, n_pts))
        adj = adj + adj.T
    else:
        adj = csr_matrix((n_pts, n_pts))
    n_comp, labels = cc(adj, directed=False)

    largest = Counter(labels).most_common(1)[0][0]
    main_pts = points[labels == largest]

    main_tree = cKDTree(main_pts)
    main_dist, _ = main_tree.query(grid_points)
    main_dist = main_dist.reshape(TILE_SIZE, TILE_SIZE)

    try:
        hull = Delaunay(main_pts)
        inside = (hull.find_simplex(grid_points) >= 0).reshape(TILE_SIZE, TILE_SIZE)
        fade = np.clip((1.0 - main_dist / FADE_DIST) * BASE_ALPHA, 0, BASE_ALPHA)
        alpha_map = np.where(inside, BASE_ALPHA, fade).astype(np.uint8)
    except Exception:
        alpha_map = np.clip((1.0 - main_dist / FADE_DIST) * BASE_ALPHA, 0, BASE_ALPHA).astype(np.uint8)

    result[alpha_map == 0] = np.nan
    result = np.clip(result, 0, 100)

    # Build RGBA image
    img_data = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)

    for i in range(len(_PELAGIC_RAMP) - 1):
        lo_val, lo_rgb = _PELAGIC_RAMP[i]
        hi_val, hi_rgb = _PELAGIC_RAMP[i + 1]
        band = (result >= lo_val) & (result < hi_val) & ~np.isnan(result)
        if not np.any(band):
            continue
        t = (result[band] - lo_val) / (hi_val - lo_val)
        img_data[band, 0] = (lo_rgb[0] + (hi_rgb[0] - lo_rgb[0]) * t).astype(np.uint8)
        img_data[band, 1] = (lo_rgb[1] + (hi_rgb[1] - lo_rgb[1]) * t).astype(np.uint8)
        img_data[band, 2] = (lo_rgb[2] + (hi_rgb[2] - lo_rgb[2]) * t).astype(np.uint8)
        img_data[band, 3] = alpha_map[band]

    # Values at top ramp stop
    top_band = (result >= _PELAGIC_RAMP[-1][0]) & ~np.isnan(result)
    if np.any(top_band):
        c = _PELAGIC_RAMP[-1][1]
        img_data[top_band, 0] = c[0]
        img_data[top_band, 1] = c[1]
        img_data[top_band, 2] = c[2]
        img_data[top_band, 3] = alpha_map[top_band]

    img = Image.fromarray(img_data, "RGBA")

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=900"})
