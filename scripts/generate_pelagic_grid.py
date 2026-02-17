#!/usr/bin/env python3
"""
Generate pelagic grid cells for the Pelagic Intelligence System.

- ~0.01° cells (~1km) nearshore (lat > 40.2)
- ~0.04° cells (~4km) offshore (lat <= 40.2)
- Coverage: lat 38.5-41.0, lon -74.5 to -70.0
- Filters out obvious land cells
- Links cells to regions via ST_Within
"""

import sys
import os
sys.path.insert(0, '/opt/marine-fishing')

from dotenv import load_dotenv
load_dotenv('/opt/marine-fishing/api/.env')

import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.getenv('DATABASE_URL', 'postgresql://marine_user:marine_fishing_2026@localhost:5432/marine_fishing')

# Simple land mask: points that are clearly on land (rough polygon vertices)
# If a cell center is north of these lat thresholds at given longitudes, skip it
LAND_BOUNDARIES = [
    # (lon_min, lon_max, max_lat_for_water)
    # Long Island / Connecticut coast
    (-74.5, -74.0, 40.50),
    (-74.0, -73.8, 40.58),
    (-73.8, -73.5, 40.60),
    (-73.5, -73.0, 40.62),
    (-73.0, -72.5, 40.65),
    (-72.5, -72.0, 40.70),
    (-72.0, -71.5, 40.80),
    (-71.5, -71.0, 40.90),
    (-71.0, -70.5, 41.00),
    (-70.5, -70.0, 41.00),
    # NJ coast
    (-74.5, -74.0, 39.50),
    (-74.3, -74.0, 40.00),
    (-74.2, -74.0, 40.20),
]


def is_water(lat, lon):
    """Return True if (lat, lon) is likely ocean (not land)."""
    for lon_min, lon_max, max_lat in LAND_BOUNDARIES:
        if lon_min <= lon < lon_max and lat > max_lat:
            return False
    return True


def parse_db_url(url):
    url = url.replace('postgresql://', '')
    user_pass, host_db = url.split('@')
    user, password = user_pass.split(':')
    host_port, dbname = host_db.split('/')
    if ':' in host_port:
        host, port = host_port.split(':')
    else:
        host, port = host_port, 5432
    return dict(host=host, port=int(port), database=dbname, user=user, password=password)


def main():
    conn = psycopg2.connect(**parse_db_url(DB_URL))
    cur = conn.cursor()

    # Check if grid already populated
    cur.execute("SELECT COUNT(*) FROM pelagic_grid_cells")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"Grid already has {existing} cells. Truncating and regenerating...")
        cur.execute("DELETE FROM cell_species_scores")
        cur.execute("DELETE FROM ocean_cell_features")
        cur.execute("DELETE FROM cell_fleet_pressure")
        cur.execute("DELETE FROM inlet_species_index")
        cur.execute("DELETE FROM region_bite_windows")
        cur.execute("DELETE FROM pelagic_grid_cells")
        conn.commit()

    # Generate cells
    cells = []

    # Nearshore: lat > 40.2, fine grid (~1km = 0.01°)
    NEAR_STEP = 0.01
    lat = 40.20
    while lat <= 41.0:
        lon = -74.50
        while lon <= -70.0:
            clat = round(lat + NEAR_STEP / 2, 5)
            clon = round(lon + NEAR_STEP / 2, 5)
            if is_water(clat, clon):
                cells.append((clat, clon, NEAR_STEP, 1.1))  # ~1.1 km
            lon = round(lon + NEAR_STEP, 5)
        lat = round(lat + NEAR_STEP, 5)

    # Offshore: lat 38.5 to 40.2, coarser grid (~4km = 0.04°)
    OFF_STEP = 0.04
    lat = 38.50
    while lat < 40.20:
        lon = -74.50
        while lon <= -70.0:
            clat = round(lat + OFF_STEP / 2, 5)
            clon = round(lon + OFF_STEP / 2, 5)
            if is_water(clat, clon):
                cells.append((clat, clon, OFF_STEP, 4.4))  # ~4.4 km
            lon = round(lon + OFF_STEP, 5)
        lat = round(lat + OFF_STEP, 5)

    print(f"Generated {len(cells)} water cells")

    # Batch insert
    BATCH = 5000
    total_inserted = 0
    for i in range(0, len(cells), BATCH):
        batch = cells[i:i + BATCH]
        values = []
        for clat, clon, step, km in batch:
            half = step / 2
            west = round(clon - half, 6)
            east = round(clon + half, 6)
            south = round(clat - half, 6)
            north = round(clat + half, 6)
            values.append((
                f'SRID=4326;POLYGON(({west} {south},{east} {south},{east} {north},{west} {north},{west} {south}))',
                f'SRID=4326;POINT({clon} {clat})',
                km,
                clat,
                clon,
            ))
        execute_values(cur,
            """INSERT INTO pelagic_grid_cells (geom, center, cell_size_km, lat, lon)
               VALUES %s""",
            values,
            template="(ST_GeomFromEWKT(%s), ST_GeomFromEWKT(%s), %s, %s, %s)",
            page_size=1000,
        )
        total_inserted += len(batch)
        print(f"  Inserted {total_inserted}/{len(cells)} cells...")
    conn.commit()

    # Link cells to regions
    print("Linking cells to regions...")
    cur.execute("""
        UPDATE pelagic_grid_cells gc
        SET region_id = r.id
        FROM pelagic_regions r
        WHERE ST_Within(gc.center, r.geom)
          AND r.region_type IN ('canyon', 'inlet_zone')
    """)
    linked = cur.rowcount
    conn.commit()
    print(f"Linked {linked} cells to canyon/inlet regions")

    # For cells not linked to specific regions, assign to shelf break or distance bands
    cur.execute("""
        UPDATE pelagic_grid_cells gc
        SET region_id = r.id
        FROM pelagic_regions r
        WHERE gc.region_id IS NULL
          AND ST_Within(gc.center, r.geom)
          AND r.region_type = 'shelf_break'
    """)
    linked2 = cur.rowcount
    conn.commit()
    print(f"Linked {linked2} cells to shelf break")

    # Final count
    cur.execute("SELECT COUNT(*) FROM pelagic_grid_cells")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pelagic_grid_cells WHERE region_id IS NOT NULL")
    with_region = cur.fetchone()[0]
    print(f"\nDone! Total cells: {total}, with region: {with_region}")

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
