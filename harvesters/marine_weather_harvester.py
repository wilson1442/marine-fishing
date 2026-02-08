"""
Open-Meteo Marine Weather Grid Harvester
Fetches wave, swell, current, and SST data for a grid covering the US East Coast.
https://open-meteo.com/en/docs/marine-weather-api
"""

import httpx
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from harvesters.base import BaseHarvester


# Grid covering US East Coast fishing grounds (Maine to Florida, out to Gulf Stream)
GRID_BOUNDS = {
    'north': 45.0,
    'south': 25.0,
    'east': -65.0,
    'west': -82.0,
}

# Grid resolution in degrees (~1 degree spacing = ~60 nm)
GRID_STEP = 1.0

OPEN_METEO_MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
OPEN_METEO_PARAMS = "wave_height,wave_direction,wave_period,swell_wave_height,ocean_current_velocity,ocean_current_direction,sea_surface_temperature"


class MarineWeatherHarvester(BaseHarvester):
    """Harvester for Open-Meteo marine weather grid data"""

    def __init__(self):
        super().__init__('open_meteo_marine')

    def _build_grid(self) -> List[Tuple[float, float]]:
        """Build a grid of lat/lon points covering the fishing area."""
        points = []
        lat = GRID_BOUNDS['south']
        while lat <= GRID_BOUNDS['north']:
            lon = GRID_BOUNDS['west']
            while lon <= GRID_BOUNDS['east']:
                points.append((round(lat, 1), round(lon, 1)))
                lon += GRID_STEP
            lat += GRID_STEP
        return points

    def _fetch_point(self, client: httpx.Client, lat: float, lon: float) -> Optional[Dict]:
        """Fetch marine weather for a single grid point."""
        try:
            resp = client.get(OPEN_METEO_MARINE_URL, params={
                "latitude": lat,
                "longitude": lon,
                "current": OPEN_METEO_PARAMS,
            }, timeout=15.0)

            if resp.status_code != 200:
                return None

            data = resp.json()
            current = data.get("current", {})

            # Land filter: Open-Meteo returns wave_height=null for land cells
            if current.get("wave_height") is None:
                return None

            sst_c = current.get("sea_surface_temperature")
            sst_f = round(sst_c * 9 / 5 + 32, 1) if sst_c is not None else None

            return {
                "lat": lat,
                "lon": lon,
                "wave_height_m": current.get("wave_height"),
                "wave_direction": current.get("wave_direction"),
                "wave_period_s": current.get("wave_period"),
                "swell_height_m": current.get("swell_wave_height"),
                "current_velocity_ms": current.get("ocean_current_velocity"),
                "current_direction": current.get("ocean_current_direction"),
                "sst_c": sst_c,
                "sst_f": sst_f,
            }
        except Exception as e:
            self.logger.warning(f"Error fetching ({lat}, {lon}): {e}")
            return None

    def sync(self, **kwargs) -> Dict:
        """Fetch marine weather grid from Open-Meteo and store in database."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        grid_points = self._build_grid()
        self.logger.info(f"Grid has {len(grid_points)} points ({GRID_BOUNDS})")

        now = datetime.utcnow()

        # Purge data older than 6 hours to keep the table lean
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM marine_weather_grid WHERE fetched_at < NOW() - INTERVAL '6 hours'")
            purged = cur.rowcount
            self.conn.commit()
            if purged > 0:
                self.logger.info(f"Purged {purged} stale grid rows")

        # Fetch from Open-Meteo with rate-limit-friendly batching
        results = []
        with httpx.Client() as client:
            for i, (lat, lon) in enumerate(grid_points):
                stats['processed'] += 1
                point = self._fetch_point(client, lat, lon)
                if point:
                    results.append(point)
                else:
                    stats['skipped'] += 1

                # Rate limit: Open-Meteo free tier allows ~600 req/min
                # Small sleep every 10 requests to stay well under
                if (i + 1) % 10 == 0:
                    time.sleep(0.5)

        if not results:
            self.logger.warning("No marine weather data returned from Open-Meteo")
            return stats

        self.logger.info(f"Fetched {len(results)} ocean grid points (skipped {stats['skipped']} land points)")

        # Bulk insert
        with self.conn.cursor() as cur:
            for pt in results:
                cur.execute("""
                    INSERT INTO marine_weather_grid
                        (lat, lon, wave_height_m, wave_direction, wave_period_s,
                         swell_height_m, current_velocity_ms, current_direction,
                         sst_c, sst_f, fetched_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    pt['lat'], pt['lon'],
                    pt.get('wave_height_m'), pt.get('wave_direction'),
                    pt.get('wave_period_s'), pt.get('swell_height_m'),
                    pt.get('current_velocity_ms'), pt.get('current_direction'),
                    pt.get('sst_c'), pt.get('sst_f'),
                    now,
                ))
                stats['inserted'] += 1

            self.conn.commit()

        self.logger.info(f"Inserted {stats['inserted']} grid points into marine_weather_grid")
        return stats


def main():
    """Run marine weather harvester"""
    harvester = MarineWeatherHarvester()
    stats = harvester.run(sync_type='incremental')
    print(f"Marine weather sync completed: {stats}")


if __name__ == "__main__":
    main()
