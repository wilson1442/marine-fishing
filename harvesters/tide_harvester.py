"""
NOAA CO-OPS Tide Data Harvester
Pulls tide predictions and real-time water levels from NOAA CO-OPS API
https://tidesandcurrents.noaa.gov/api/
"""

import httpx
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from harvesters.base import BaseHarvester


# Key inlet/tide stations along US East Coast
TIDE_STATIONS = {
    '8419317': {'name': 'Wells', 'state': 'ME', 'lat': 43.3200, 'lon': -70.5633, 'type': 'inlet'},
    '8443970': {'name': 'Boston', 'state': 'MA', 'lat': 42.3539, 'lon': -71.0503, 'type': 'harbor'},
    '8447930': {'name': 'Woods Hole', 'state': 'MA', 'lat': 41.5236, 'lon': -70.6711, 'type': 'inlet'},
    '8449130': {'name': 'Nantucket Island', 'state': 'MA', 'lat': 41.2853, 'lon': -70.0964, 'type': 'harbor'},
    '8461490': {'name': 'New London', 'state': 'CT', 'lat': 41.3550, 'lon': -72.0900, 'type': 'harbor'},
    '8510560': {'name': 'Montauk', 'state': 'NY', 'lat': 41.0486, 'lon': -71.9597, 'type': 'inlet'},
    '8512354': {'name': 'Shinnecock Inlet', 'state': 'NY', 'lat': 40.8433, 'lon': -72.4767, 'type': 'inlet'},
    '8513398': {'name': 'Moriches Inlet', 'state': 'NY', 'lat': 40.7650, 'lon': -72.7550, 'type': 'inlet'},
    '8515228': {'name': 'Fire Island', 'state': 'NY', 'lat': 40.6317, 'lon': -73.2567, 'type': 'inlet'},
    '8516385': {'name': 'Jones Inlet (Point Lookout)', 'state': 'NY', 'lat': 40.5917, 'lon': -73.5800, 'type': 'inlet'},
    '8516881': {'name': 'East Rockaway Inlet', 'state': 'NY', 'lat': 40.5850, 'lon': -73.7550, 'type': 'inlet'},
    '8516945': {'name': 'Kings Point', 'state': 'NY', 'lat': 40.8103, 'lon': -73.7649, 'type': 'harbor'},
    '8518750': {'name': 'The Battery', 'state': 'NY', 'lat': 40.7006, 'lon': -74.0142, 'type': 'harbor'},
    '8531680': {'name': 'Sandy Hook', 'state': 'NJ', 'lat': 40.4669, 'lon': -74.0094, 'type': 'inlet'},
    '8534720': {'name': 'Atlantic City', 'state': 'NJ', 'lat': 39.3550, 'lon': -74.4183, 'type': 'harbor'},
    '8536110': {'name': 'Cape May', 'state': 'NJ', 'lat': 38.9683, 'lon': -74.9600, 'type': 'inlet'},
    '8545240': {'name': 'Philadelphia', 'state': 'PA', 'lat': 39.9333, 'lon': -75.1417, 'type': 'harbor'},
    '8557380': {'name': 'Lewes', 'state': 'DE', 'lat': 38.7828, 'lon': -75.1192, 'type': 'bay'},
    '8570283': {'name': 'Ocean City Inlet', 'state': 'MD', 'lat': 38.3283, 'lon': -75.0911, 'type': 'inlet'},
    '8638610': {'name': 'Sewells Point', 'state': 'VA', 'lat': 36.9467, 'lon': -76.3300, 'type': 'harbor'},
    '8638863': {'name': 'Virginia Beach', 'state': 'VA', 'lat': 36.8314, 'lon': -75.9694, 'type': 'inlet'},
    '8651370': {'name': 'Duck', 'state': 'NC', 'lat': 36.1833, 'lon': -75.7467, 'type': 'inlet'},
    '8656483': {'name': 'Beaufort', 'state': 'NC', 'lat': 34.7200, 'lon': -76.6700, 'type': 'inlet'},
    '8658120': {'name': 'Wilmington', 'state': 'NC', 'lat': 34.2267, 'lon': -77.9533, 'type': 'harbor'},
    '8661070': {'name': 'Myrtle Beach', 'state': 'SC', 'lat': 33.6550, 'lon': -78.9183, 'type': 'inlet'},
    '8665530': {'name': 'Charleston', 'state': 'SC', 'lat': 32.7817, 'lon': -79.9250, 'type': 'harbor'},
    '8720218': {'name': 'Mayport', 'state': 'FL', 'lat': 30.3967, 'lon': -81.4300, 'type': 'inlet'},
}


class TideHarvester(BaseHarvester):
    """Harvester for NOAA CO-OPS tide data"""

    COOPS_BASE_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

    def __init__(self):
        super().__init__('noaa_coops')

    def _get_active_stations(self) -> List[str]:
        """Get station IDs that are marked active in the database"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT station_id FROM tide_stations WHERE is_active = true ORDER BY station_id")
            db_stations = [row[0] for row in cur.fetchall()]
        if db_stations:
            self.logger.info(f"Found {len(db_stations)} active tide stations in database")
            return db_stations
        # Fallback to all known stations if DB has none
        return list(TIDE_STATIONS.keys())

    def sync(self, stations: List[str] = None, days_ahead: int = 7, **kwargs) -> Dict:
        """
        Sync tide data from NOAA CO-OPS

        Args:
            stations: List of station IDs to sync. If None, syncs active stations only.
            days_ahead: Number of days ahead to fetch predictions (default 7)
        """
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if stations is None:
            stations = self._get_active_stations()

        # First, ensure all tide stations exist in the database
        self._sync_tide_stations(stations)

        # Then fetch predictions and water levels for each station
        for station_id in stations:
            try:
                self.logger.info(f"Fetching tide data for station {station_id}")

                # Fetch predictions (7 days ahead)
                pred_stats = self._fetch_predictions(station_id, days_ahead)
                stats['processed'] += pred_stats.get('processed', 0)
                stats['inserted'] += pred_stats.get('inserted', 0)
                stats['skipped'] += pred_stats.get('skipped', 0)

                # Fetch recent water levels (last 24 hours)
                level_stats = self._fetch_water_levels(station_id)
                stats['processed'] += level_stats.get('processed', 0)
                stats['inserted'] += level_stats.get('inserted', 0)
                stats['skipped'] += level_stats.get('skipped', 0)

            except Exception as e:
                self.logger.warning(f"Error fetching tide data for station {station_id}: {e}")
                stats['skipped'] += 1

        return stats

    def _sync_tide_stations(self, stations: List[str]):
        """Ensure tide stations exist in the database"""
        with self.conn.cursor() as cur:
            for station_id in stations:
                if station_id in TIDE_STATIONS:
                    info = TIDE_STATIONS[station_id]
                    cur.execute("""
                        INSERT INTO tide_stations (station_id, station_name, latitude, longitude, location, state, station_type, is_active)
                        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, true)
                        ON CONFLICT (station_id) DO UPDATE SET
                            station_name = EXCLUDED.station_name,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            location = EXCLUDED.location,
                            state = EXCLUDED.state,
                            station_type = EXCLUDED.station_type,
                            is_active = true
                    """, (
                        station_id,
                        info['name'],
                        info['lat'],
                        info['lon'],
                        info['lon'],
                        info['lat'],
                        info['state'],
                        info.get('type', 'tide')
                    ))

            self.conn.commit()
            self.logger.info(f"Synced {len(stations)} tide stations")

    def _fetch_predictions(self, station_id: str, days_ahead: int = 7) -> Dict:
        """Fetch tide predictions (high/low) from NOAA CO-OPS"""
        stats = {'processed': 0, 'inserted': 0, 'skipped': 0}

        now = datetime.now(timezone.utc)
        begin_date = now.strftime("%Y%m%d")
        end_date = (now + timedelta(days=days_ahead)).strftime("%Y%m%d")

        params = {
            'station': station_id,
            'product': 'predictions',
            'datum': 'MLLW',
            'units': 'english',
            'time_zone': 'gmt',
            'format': 'json',
            'begin_date': begin_date,
            'end_date': end_date,
            'interval': 'hilo',
            'application': 'marine_fishing_platform',
        }

        try:
            response = httpx.get(self.COOPS_BASE_URL, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            if 'error' in data:
                self.logger.warning(f"NOAA API error for {station_id}: {data['error'].get('message', 'Unknown error')}")
                return stats

            predictions = data.get('predictions', [])
            stats['processed'] = len(predictions)

            with self.conn.cursor() as cur:
                for pred in predictions:
                    try:
                        # Parse prediction time (format: "2026-02-05 14:30")
                        pred_time = datetime.strptime(pred['t'], "%Y-%m-%d %H:%M")
                        pred_time = pred_time.replace(tzinfo=timezone.utc)

                        height = float(pred['v']) if pred.get('v') else None
                        tide_type = pred.get('type', '')  # 'H' or 'L'

                        cur.execute("""
                            INSERT INTO tide_predictions (station_id, prediction_time, height_ft, tide_type, source)
                            VALUES (%s, %s, %s, %s, 'noaa_coops')
                            ON CONFLICT (station_id, prediction_time) DO UPDATE SET
                                height_ft = EXCLUDED.height_ft,
                                tide_type = EXCLUDED.tide_type
                        """, (station_id, pred_time, height, tide_type))
                        stats['inserted'] += 1
                    except (ValueError, KeyError) as e:
                        self.logger.debug(f"Skipping prediction: {e}")
                        stats['skipped'] += 1

                self.conn.commit()

            self.logger.info(f"Station {station_id}: {stats['inserted']} predictions inserted")

        except httpx.HTTPError as e:
            self.logger.warning(f"HTTP error fetching predictions for {station_id}: {e}")
        except Exception as e:
            self.logger.warning(f"Error processing predictions for {station_id}: {e}")

        return stats

    def _fetch_water_levels(self, station_id: str, hours_back: int = 24) -> Dict:
        """Fetch real-time water level observations from NOAA CO-OPS"""
        stats = {'processed': 0, 'inserted': 0, 'skipped': 0}

        now = datetime.now(timezone.utc)
        begin_date = (now - timedelta(hours=hours_back)).strftime("%Y%m%d %H:%M")
        end_date = now.strftime("%Y%m%d %H:%M")

        params = {
            'station': station_id,
            'product': 'water_level',
            'datum': 'MLLW',
            'units': 'english',
            'time_zone': 'gmt',
            'format': 'json',
            'begin_date': begin_date,
            'end_date': end_date,
            'application': 'marine_fishing_platform',
        }

        try:
            response = httpx.get(self.COOPS_BASE_URL, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()

            if 'error' in data:
                self.logger.debug(f"NOAA API error for water levels {station_id}: {data['error'].get('message', 'Unknown error')}")
                return stats

            readings = data.get('data', [])
            stats['processed'] = len(readings)

            with self.conn.cursor() as cur:
                for reading in readings:
                    try:
                        # Parse time (format: "2026-02-05 14:30")
                        recorded_at = datetime.strptime(reading['t'], "%Y-%m-%d %H:%M")
                        recorded_at = recorded_at.replace(tzinfo=timezone.utc)

                        height = float(reading['v']) if reading.get('v') else None
                        sigma = float(reading['s']) if reading.get('s') else None
                        flags = reading.get('f', '')

                        cur.execute("""
                            INSERT INTO tide_water_levels (station_id, recorded_at, height_ft, sigma, flags, source)
                            VALUES (%s, %s, %s, %s, %s, 'noaa_coops')
                            ON CONFLICT (station_id, recorded_at) DO UPDATE SET
                                height_ft = EXCLUDED.height_ft,
                                sigma = EXCLUDED.sigma,
                                flags = EXCLUDED.flags
                        """, (station_id, recorded_at, height, sigma, flags))
                        stats['inserted'] += 1
                    except (ValueError, KeyError) as e:
                        self.logger.debug(f"Skipping water level: {e}")
                        stats['skipped'] += 1

                self.conn.commit()

            self.logger.info(f"Station {station_id}: {stats['inserted']} water levels inserted")

        except httpx.HTTPError as e:
            self.logger.debug(f"HTTP error fetching water levels for {station_id}: {e}")
        except Exception as e:
            self.logger.debug(f"Error processing water levels for {station_id}: {e}")

        return stats


def main():
    """Run tide harvester"""
    harvester = TideHarvester()
    stats = harvester.run(sync_type='incremental')
    print(f"Tide sync completed: {stats}")


if __name__ == "__main__":
    main()
