"""
Fleet Pressure Harvester
Aggregates vessel_positions into cell_fleet_pressure per 15-min bucket.
"""

import sys
sys.path.insert(0, '/opt/marine-fishing')

from datetime import datetime, timedelta, timezone
from typing import Dict
from harvesters.base import BaseHarvester


class FleetPressureHarvester(BaseHarvester):
    """Compute per-cell fleet pressure from AIS vessel positions."""

    def __init__(self):
        super().__init__('fleet_pressure')

    def sync(self, **kwargs) -> Dict:
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}
        cur = self.conn.cursor()

        # Determine time window: last 30 minutes in 15-min buckets
        now = datetime.now(timezone.utc)
        # Round down to nearest 15 minutes
        bucket_end = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
        bucket_start = bucket_end - timedelta(minutes=15)

        self.logger.info(f"Processing bucket {bucket_start} -> {bucket_end}")

        # Spatial join: assign vessel positions to grid cells and compute metrics
        cur.execute("""
            INSERT INTO cell_fleet_pressure (cell_id, bucket_start, bucket_end,
                vessel_count, fishing_vessel_count, avg_speed_knots,
                dwell_minutes, fishing_intensity_score)
            SELECT
                gc.id AS cell_id,
                %(bucket_start)s AS bucket_start,
                %(bucket_end)s AS bucket_end,
                COUNT(DISTINCT vp.mmsi) AS vessel_count,
                COUNT(DISTINCT CASE WHEN vp.speed_knots < 5 THEN vp.mmsi END) AS fishing_vessel_count,
                AVG(vp.speed_knots) AS avg_speed_knots,
                COUNT(*) * 0.5 AS dwell_minutes,  -- ~30s per position report
                LEAST(100, (
                    COUNT(DISTINCT vp.mmsi) * 15.0 +
                    COUNT(DISTINCT CASE WHEN vp.speed_knots < 5 THEN vp.mmsi END) * 25.0 +
                    CASE WHEN AVG(vp.speed_knots) < 3 THEN 20 ELSE 0 END
                )) AS fishing_intensity_score
            FROM pelagic_grid_cells gc
            JOIN vessel_positions vp
                ON ST_Within(vp.location, gc.geom)
            WHERE vp.received_at >= %(bucket_start)s
              AND vp.received_at < %(bucket_end)s
            GROUP BY gc.id
            ON CONFLICT (cell_id, bucket_start) DO UPDATE SET
                vessel_count = EXCLUDED.vessel_count,
                fishing_vessel_count = EXCLUDED.fishing_vessel_count,
                avg_speed_knots = EXCLUDED.avg_speed_knots,
                dwell_minutes = EXCLUDED.dwell_minutes,
                fishing_intensity_score = EXCLUDED.fishing_intensity_score,
                bucket_end = EXCLUDED.bucket_end
        """, {
            'bucket_start': bucket_start,
            'bucket_end': bucket_end,
        })

        stats['inserted'] = cur.rowcount
        stats['processed'] = stats['inserted']
        self.conn.commit()

        self.logger.info(f"Updated {stats['inserted']} cell fleet pressure records")

        # Purge data older than 48 hours
        cur.execute("""
            DELETE FROM cell_fleet_pressure
            WHERE bucket_start < NOW() - INTERVAL '48 hours'
        """)
        purged = cur.rowcount
        if purged:
            self.logger.info(f"Purged {purged} old fleet pressure records")
        self.conn.commit()

        cur.close()
        return stats


if __name__ == '__main__':
    harvester = FleetPressureHarvester()
    harvester.run(sync_type='incremental')
