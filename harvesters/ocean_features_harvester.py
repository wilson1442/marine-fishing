"""
Ocean Features Harvester
Reads latest marine_weather_grid snapshot, interpolates per grid cell,
computes SST gradient, current shear, and front_score.
"""

import sys
sys.path.insert(0, '/opt/marine-fishing')

import math
from datetime import datetime, timezone
from typing import Dict
from harvesters.base import BaseHarvester


class OceanFeaturesHarvester(BaseHarvester):
    """Compute per-cell ocean features from marine weather grid."""

    def __init__(self):
        super().__init__('ocean_features')

    def sync(self, **kwargs) -> Dict:
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}
        cur = self.conn.cursor()

        # Get the latest weather grid snapshot
        cur.execute("SELECT MAX(fetched_at) FROM marine_weather_grid")
        latest = cur.fetchone()[0]
        if not latest:
            self.logger.warning("No marine weather grid data found")
            return stats

        self.logger.info(f"Using weather grid snapshot from {latest}")

        # Load all weather grid points
        cur.execute("""
            SELECT lat, lon, sst_c, sst_f, wave_height_m, wave_period_s,
                   current_velocity_ms, current_direction
            FROM marine_weather_grid
            WHERE fetched_at = %s
              AND sst_c IS NOT NULL
        """, (latest,))
        wx_rows = cur.fetchall()

        if not wx_rows:
            self.logger.warning("No valid weather grid rows")
            return stats

        self.logger.info(f"Loaded {len(wx_rows)} weather grid points")

        # Build lookup: round lat/lon to nearest 0.5° for quick spatial match
        wx_by_pos = {}
        for row in wx_rows:
            lat, lon = float(row[0]), float(row[1])
            key = (round(lat, 1), round(lon, 1))
            wx_by_pos[key] = {
                'sst_c': float(row[2]) if row[2] else None,
                'sst_f': float(row[3]) if row[3] else None,
                'wave_height_m': float(row[4]) if row[4] else None,
                'wave_period_s': float(row[5]) if row[5] else None,
                'current_speed': float(row[6]) if row[6] else None,
                'current_dir': int(row[7]) if row[7] else None,
            }

        # Get all grid cells
        cur.execute("SELECT id, lat, lon FROM pelagic_grid_cells")
        cells = cur.fetchall()
        self.logger.info(f"Processing {len(cells)} grid cells")

        now = datetime.now(timezone.utc)

        # Delete previous run's features (we replace rather than accumulate)
        cur.execute("DELETE FROM ocean_cell_features WHERE computed_at < %s - INTERVAL '2 hours'", (now,))

        batch = []
        for cell_id, cell_lat, cell_lon in cells:
            clat, clon = float(cell_lat), float(cell_lon)

            # Find nearest weather grid point
            wx = self._find_nearest(wx_by_pos, clat, clon)
            if not wx or wx['sst_c'] is None:
                stats['skipped'] += 1
                continue

            # Compute SST gradient: max SST difference with nearby grid points
            sst_gradient = self._compute_sst_gradient(wx_by_pos, clat, clon, wx['sst_c'])

            # Compute current shear
            current_shear = self._compute_current_shear(wx_by_pos, clat, clon, wx)

            # Front score = normalized combination
            front_score = min(1.0, (sst_gradient / 3.0 + current_shear / 0.5) / 2.0)

            batch.append((
                cell_id, now,
                wx['sst_c'], wx['sst_f'],
                sst_gradient,
                wx['current_speed'], wx['current_dir'],
                current_shear,
                wx['wave_height_m'], wx['wave_period_s'],
                front_score,
            ))
            stats['processed'] += 1

            if len(batch) >= 2000:
                self._insert_batch(cur, batch)
                stats['inserted'] += len(batch)
                batch = []

        if batch:
            self._insert_batch(cur, batch)
            stats['inserted'] += len(batch)

        self.conn.commit()
        self.logger.info(f"Inserted {stats['inserted']} ocean feature records")

        # Purge old data
        cur.execute("""
            DELETE FROM ocean_cell_features
            WHERE computed_at < NOW() - INTERVAL '48 hours'
        """)
        purged = cur.rowcount
        if purged:
            self.logger.info(f"Purged {purged} old ocean feature records")
        self.conn.commit()

        cur.close()
        return stats

    def _find_nearest(self, wx_by_pos, lat, lon):
        """Find nearest weather grid point within search radius."""
        best = None
        best_dist = float('inf')
        for delta_lat in [-0.5, 0.0, 0.5]:
            for delta_lon in [-0.5, 0.0, 0.5]:
                key = (round(lat + delta_lat, 1), round(lon + delta_lon, 1))
                if key in wx_by_pos:
                    dist = abs(delta_lat) + abs(delta_lon)
                    if dist < best_dist:
                        best_dist = dist
                        best = wx_by_pos[key]
        return best

    def _compute_sst_gradient(self, wx_by_pos, lat, lon, center_sst):
        """Max SST difference with neighboring grid points in C/degree."""
        max_grad = 0.0
        for dlat in [-0.5, 0.0, 0.5]:
            for dlon in [-0.5, 0.0, 0.5]:
                if dlat == 0 and dlon == 0:
                    continue
                key = (round(lat + dlat, 1), round(lon + dlon, 1))
                if key in wx_by_pos and wx_by_pos[key]['sst_c'] is not None:
                    diff = abs(center_sst - wx_by_pos[key]['sst_c'])
                    dist = math.sqrt(dlat**2 + dlon**2) * 111  # approx km
                    grad = diff / max(dist, 0.1)  # C/km
                    max_grad = max(max_grad, grad)
        return max_grad

    def _compute_current_shear(self, wx_by_pos, lat, lon, center_wx):
        """Vector difference of current with neighbors."""
        if center_wx['current_speed'] is None:
            return 0.0

        cx = center_wx['current_speed'] * math.cos(math.radians(center_wx['current_dir'] or 0))
        cy = center_wx['current_speed'] * math.sin(math.radians(center_wx['current_dir'] or 0))

        max_shear = 0.0
        for dlat in [-0.5, 0.0, 0.5]:
            for dlon in [-0.5, 0.0, 0.5]:
                if dlat == 0 and dlon == 0:
                    continue
                key = (round(lat + dlat, 1), round(lon + dlon, 1))
                if key in wx_by_pos:
                    nb = wx_by_pos[key]
                    if nb['current_speed'] is not None:
                        nx = nb['current_speed'] * math.cos(math.radians(nb['current_dir'] or 0))
                        ny = nb['current_speed'] * math.sin(math.radians(nb['current_dir'] or 0))
                        shear = math.sqrt((cx - nx)**2 + (cy - ny)**2)
                        max_shear = max(max_shear, shear)
        return max_shear

    def _insert_batch(self, cur, batch):
        from psycopg2.extras import execute_values
        execute_values(cur,
            """INSERT INTO ocean_cell_features
               (cell_id, computed_at, sst_c, sst_f, sst_gradient,
                current_speed, current_dir, current_shear,
                wave_height_m, wave_period_s, front_score)
               VALUES %s""",
            batch,
            page_size=1000,
        )


if __name__ == '__main__':
    harvester = OceanFeaturesHarvester()
    harvester.run(sync_type='incremental')
