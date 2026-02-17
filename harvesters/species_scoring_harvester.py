"""
Species Scoring Harvester
Loads model weights, ocean features, and fleet pressure per cell.
Computes per-cell per-species probability scores, bite windows, and inlet indices.
"""

import sys
sys.path.insert(0, '/opt/marine-fishing')

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
from harvesters.base import BaseHarvester


def sigmoid(x):
    """Standard sigmoid function, clamped to avoid overflow."""
    x = max(-10, min(10, x))
    return 1.0 / (1.0 + math.exp(-x))


class SpeciesScoringHarvester(BaseHarvester):
    """Compute per-cell per-species catch probability scores."""

    def __init__(self):
        super().__init__('species_scoring')

    def sync(self, **kwargs) -> Dict:
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}
        cur = self.conn.cursor()

        now = datetime.now(timezone.utc)
        current_month = now.month  # 1-12 -> index 0-11

        # Load model weights for all species
        cur.execute("""
            SELECT s.id, s.species_code, smw.env_weight, smw.edge_weight,
                   smw.fleet_weight, smw.season_weight,
                   smw.optimal_sst_min_f, smw.optimal_sst_max_f,
                   smw.monthly_season
            FROM species_model_weights smw
            JOIN species s ON s.id = smw.species_id
        """)
        models = {}
        for row in cur.fetchall():
            monthly = row[8]  # already a list from PostgreSQL array
            models[row[0]] = {
                'species_id': row[0],
                'code': row[1],
                'env_w': float(row[2]),
                'edge_w': float(row[3]),
                'fleet_w': float(row[4]),
                'season_w': float(row[5]),
                'sst_min_f': float(row[6]) if row[6] else 60,
                'sst_max_f': float(row[7]) if row[7] else 80,
                'season_prior': float(monthly[current_month - 1]) if monthly else 0.5,
            }

        if not models:
            self.logger.error("No species model weights found. Run schema_pelagic.sql first.")
            return stats

        self.logger.info(f"Loaded models for {len(models)} species")

        # Load latest ocean features per cell (most recent per cell)
        cur.execute("""
            SELECT DISTINCT ON (cell_id)
                cell_id, sst_f, sst_gradient, current_speed, current_shear,
                wave_height_m, front_score, computed_at
            FROM ocean_cell_features
            ORDER BY cell_id, computed_at DESC
        """)
        ocean = {}
        for row in cur.fetchall():
            ocean[row[0]] = {
                'sst_f': float(row[1]) if row[1] else None,
                'sst_gradient': float(row[2]) if row[2] else 0,
                'current_speed': float(row[3]) if row[3] else 0,
                'current_shear': float(row[4]) if row[4] else 0,
                'wave_height_m': float(row[5]) if row[5] else None,
                'front_score': float(row[6]) if row[6] else 0,
                'age_hours': (now - row[7].replace(tzinfo=timezone.utc)).total_seconds() / 3600 if row[7] else 999,
            }

        self.logger.info(f"Loaded ocean features for {len(ocean)} cells")

        # Load latest fleet pressure per cell (last hour)
        cur.execute("""
            SELECT cell_id, SUM(fishing_intensity_score) / COUNT(*) as avg_intensity
            FROM cell_fleet_pressure
            WHERE bucket_start > NOW() - INTERVAL '1 hour'
            GROUP BY cell_id
        """)
        fleet = {}
        for row in cur.fetchall():
            fleet[row[0]] = float(row[1]) if row[1] else 0

        self.logger.info(f"Loaded fleet pressure for {len(fleet)} cells")

        # Get all cells with their region
        cur.execute("SELECT id, region_id FROM pelagic_grid_cells")
        cells = cur.fetchall()

        # Delete previous scores
        cur.execute("DELETE FROM cell_species_scores WHERE computed_at < %s - INTERVAL '2 hours'", (now,))
        self.conn.commit()

        # Score each cell x species
        score_batch = []
        for cell_id, region_id in cells:
            ocn = ocean.get(cell_id)
            if not ocn or ocn['sst_f'] is None:
                stats['skipped'] += 1
                continue

            flt = fleet.get(cell_id, 0)

            for sp_id, model in models.items():
                score_data = self._compute_score(model, ocn, flt)

                score_batch.append((
                    cell_id, sp_id, now,
                    score_data['probability'],
                    score_data['confidence'],
                    score_data['env_suitability'],
                    score_data['edge_strength'],
                    score_data['fleet_signal'],
                    score_data['season_prior'],
                    score_data['sea_state_pen'],
                    score_data['reason_codes'],
                ))
                stats['processed'] += 1

                if len(score_batch) >= 5000:
                    self._insert_scores(cur, score_batch)
                    stats['inserted'] += len(score_batch)
                    score_batch = []

        if score_batch:
            self._insert_scores(cur, score_batch)
            stats['inserted'] += len(score_batch)

        self.conn.commit()
        self.logger.info(f"Inserted {stats['inserted']} species scores")

        # Aggregate bite windows per region x species
        self._compute_bite_windows(cur, now, models)

        # Aggregate inlet indices
        self._compute_inlet_indices(cur, now, models)

        # Purge old data from all pelagic tables
        self._purge_old_data(cur)

        self.conn.commit()
        cur.close()
        return stats

    def _compute_score(self, model, ocn, fleet_intensity):
        """Compute probability and components for one cell x species."""
        sst_f = ocn['sst_f']
        reasons = []

        # 1. Environment suitability: Gaussian around optimal SST range
        sst_mid = (model['sst_min_f'] + model['sst_max_f']) / 2
        sst_range = (model['sst_max_f'] - model['sst_min_f']) / 2
        sst_diff = abs(sst_f - sst_mid)
        if sst_diff <= sst_range:
            env_suit = 1.0
            reasons.append('optimal_sst')
        else:
            env_suit = max(0, 1.0 - (sst_diff - sst_range) / 10.0)
        if env_suit < 0.2:
            reasons.append('cold_water' if sst_f < model['sst_min_f'] else 'warm_water')

        # 2. Edge strength: SST gradient + front score
        edge = min(1.0, ocn['sst_gradient'] / 2.0 * 0.6 + ocn['front_score'] * 0.4)
        if edge > 0.5:
            reasons.append('strong_front')
        if ocn['sst_gradient'] > 1.0:
            reasons.append('sst_break')

        # 3. Fleet signal
        fleet_sig = min(1.0, fleet_intensity / 100.0)
        if fleet_sig > 0.3:
            reasons.append('fleet_active')

        # 4. Season prior
        season = model['season_prior']
        if season > 0.7:
            reasons.append('peak_season')
        elif season < 0.2:
            reasons.append('off_season')

        # 5. Sea state penalty
        wave_m = ocn['wave_height_m']
        wave_ft = wave_m * 3.281 if wave_m else 0
        if wave_ft > 10:
            sea_pen = 0.3
            reasons.append('rough_seas')
        elif wave_ft > 6:
            sea_pen = 0.7
            reasons.append('moderate_seas')
        else:
            sea_pen = 1.0

        # Weighted sum
        weighted = (
            model['env_w'] * env_suit +
            model['edge_w'] * edge +
            model['fleet_w'] * fleet_sig +
            model['season_w'] * season
        )

        probability = max(0, min(100, 100 * sigmoid(weighted * 4 - 2) * sea_pen))

        # Confidence based on data freshness and availability
        age_penalty = max(0, 1.0 - ocn['age_hours'] / 6.0)
        has_fleet = 1.0 if fleet_intensity > 0 else 0.5
        confidence = min(1.0, age_penalty * 0.6 + has_fleet * 0.2 + (1.0 if wave_m is not None else 0) * 0.2)

        return {
            'probability': round(probability, 1),
            'confidence': round(confidence, 3),
            'env_suitability': round(env_suit, 3),
            'edge_strength': round(edge, 3),
            'fleet_signal': round(fleet_sig, 3),
            'season_prior': round(season, 3),
            'sea_state_pen': round(sea_pen, 3),
            'reason_codes': reasons[:5],  # cap at 5
        }

    def _insert_scores(self, cur, batch):
        from psycopg2.extras import execute_values
        execute_values(cur,
            """INSERT INTO cell_species_scores
               (cell_id, species_id, computed_at, probability, confidence,
                env_suitability, edge_strength, fleet_signal, season_prior,
                sea_state_pen, reason_codes)
               VALUES %s""",
            batch,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            page_size=2000,
        )

    def _compute_bite_windows(self, cur, now, models):
        """Aggregate cell scores into region bite windows."""
        self.logger.info("Computing bite windows...")

        cur.execute("DELETE FROM region_bite_windows WHERE computed_at < %s - INTERVAL '2 hours'", (now,))

        cur.execute("""
            INSERT INTO region_bite_windows
                (region_id, species_id, computed_at, avg_probability, max_probability, cell_count, label, reason_summary)
            SELECT
                gc.region_id,
                css.species_id,
                %(now)s,
                AVG(css.probability),
                MAX(css.probability),
                COUNT(*),
                CASE
                    WHEN AVG(css.probability) >= 70 THEN 'HOT'
                    WHEN AVG(css.probability) >= 45 THEN 'WARM'
                    WHEN AVG(css.probability) >= 20 THEN 'COOL'
                    ELSE 'COLD'
                END,
                (SELECT array_to_string(
                    (SELECT ARRAY(
                        SELECT DISTINCT unnest(reason_codes)
                        FROM cell_species_scores css2
                        WHERE css2.species_id = css.species_id
                          AND css2.cell_id IN (
                              SELECT id FROM pelagic_grid_cells WHERE region_id = gc.region_id
                          )
                          AND css2.computed_at = %(now)s
                        LIMIT 3
                    )), ', '))
            FROM cell_species_scores css
            JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
            WHERE gc.region_id IS NOT NULL
              AND css.computed_at = %(now)s
            GROUP BY gc.region_id, css.species_id
        """, {'now': now})

        self.logger.info(f"Inserted {cur.rowcount} bite window records")
        self.conn.commit()

    def _compute_inlet_indices(self, cur, now, models):
        """Compute per-inlet bite indices."""
        self.logger.info("Computing inlet indices...")

        cur.execute("DELETE FROM inlet_species_index WHERE computed_at < %s - INTERVAL '2 hours'", (now,))

        # Get inlet regions
        cur.execute("""
            SELECT id, name FROM pelagic_regions WHERE region_type = 'inlet_zone'
        """)
        inlets = cur.fetchall()

        for inlet_id, inlet_name in inlets:
            for sp_id, model in models.items():
                # Current bite index = avg probability in this inlet zone
                cur.execute("""
                    SELECT AVG(css.probability)
                    FROM cell_species_scores css
                    JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
                    WHERE gc.region_id = %s AND css.species_id = %s
                      AND css.computed_at = %s
                """, (inlet_id, sp_id, now))
                avg_prob = cur.fetchone()[0]
                if avg_prob is None:
                    continue

                bite_index = round(float(avg_prob), 1)

                # Previous run's bite index
                cur.execute("""
                    SELECT bite_index FROM inlet_species_index
                    WHERE region_id = %s AND species_id = %s
                    ORDER BY computed_at DESC LIMIT 1
                """, (inlet_id, sp_id))
                prev = cur.fetchone()
                prev_index = float(prev[0]) if prev else None

                if prev_index is not None:
                    if bite_index > prev_index + 5:
                        trend = 'UP'
                    elif bite_index < prev_index - 5:
                        trend = 'DOWN'
                    else:
                        trend = 'STABLE'
                else:
                    trend = 'STABLE'

                # Top reason
                cur.execute("""
                    SELECT unnest(reason_codes) as rc, COUNT(*) as cnt
                    FROM cell_species_scores css
                    JOIN pelagic_grid_cells gc ON gc.id = css.cell_id
                    WHERE gc.region_id = %s AND css.species_id = %s
                      AND css.computed_at = %s
                    GROUP BY rc ORDER BY cnt DESC LIMIT 1
                """, (inlet_id, sp_id, now))
                top_reason_row = cur.fetchone()
                top_reason = top_reason_row[0] if top_reason_row else None

                cur.execute("""
                    INSERT INTO inlet_species_index
                        (region_id, species_id, computed_at, bite_index, trend, prev_bite_index, top_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (inlet_id, sp_id, now, bite_index, trend, prev_index, top_reason))

        self.conn.commit()
        self.logger.info("Inlet indices computed")

    def _purge_old_data(self, cur):
        """Purge data older than 48 hours from all pelagic tables."""
        tables = [
            ('cell_species_scores', 'computed_at'),
            ('ocean_cell_features', 'computed_at'),
            ('cell_fleet_pressure', 'bucket_start'),
            ('region_bite_windows', 'computed_at'),
            ('inlet_species_index', 'computed_at'),
        ]
        for table, col in tables:
            cur.execute(f"DELETE FROM {table} WHERE {col} < NOW() - INTERVAL '48 hours'")
            if cur.rowcount:
                self.logger.info(f"Purged {cur.rowcount} old rows from {table}")
        self.conn.commit()


if __name__ == '__main__':
    harvester = SpeciesScoringHarvester()
    harvester.run(sync_type='incremental')
