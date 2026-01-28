"""
NOAA NDBC Weather Buoy Harvester
Pulls real-time weather observations from NDBC buoys
https://www.ndbc.noaa.gov/
"""

import httpx
from datetime import datetime
from typing import Dict, List, Optional
import re
from harvesters.base import BaseHarvester


# Key offshore buoys for Mid-Atlantic fishing areas
BUOY_STATIONS = {
    '44025': {'name': 'Long Island', 'lat': 40.251, 'lon': -73.164},
    '44017': {'name': 'Montauk Point', 'lat': 40.694, 'lon': -72.048},
    '44009': {'name': 'Delaware Bay', 'lat': 38.461, 'lon': -74.703},
    '44066': {'name': 'Texas Tower #4', 'lat': 39.618, 'lon': -72.644},
    '44065': {'name': 'New York Harbor Entrance', 'lat': 40.369, 'lon': -73.703},
    '44027': {'name': 'Jonesport, ME', 'lat': 44.283, 'lon': -67.307},
    '44013': {'name': 'Boston', 'lat': 42.346, 'lon': -70.651},
    '44008': {'name': 'Nantucket', 'lat': 40.503, 'lon': -69.247},
    '41048': {'name': 'West Bermuda', 'lat': 31.978, 'lon': -69.649},
    '41046': {'name': 'East Hatteras', 'lat': 35.781, 'lon': -74.927},
    '41025': {'name': 'Diamond Shoals', 'lat': 35.006, 'lon': -75.402},
    '41002': {'name': 'South Hatteras', 'lat': 31.759, 'lon': -74.936},
    '44014': {'name': 'Virginia Beach', 'lat': 36.611, 'lon': -74.842},
}


class WeatherHarvester(BaseHarvester):
    """Harvester for NOAA NDBC buoy weather data"""

    NDBC_BASE_URL = "https://www.ndbc.noaa.gov/data/realtime2"

    def __init__(self):
        super().__init__('ndbc')

    def _get_active_stations(self) -> List[str]:
        """Get station IDs that are marked active in the database"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT station_id FROM buoy_stations WHERE is_active = true ORDER BY station_id")
            db_stations = [row[0] for row in cur.fetchall()]
        if db_stations:
            self.logger.info(f"Found {len(db_stations)} active stations in database")
            return db_stations
        # Fallback to all known stations if DB has none
        return list(BUOY_STATIONS.keys())

    def sync(self, stations: List[str] = None, **kwargs) -> Dict:
        """
        Sync weather observations from NDBC buoys

        Args:
            stations: List of station IDs to sync. If None, syncs active stations only.
        """
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if stations is None:
            stations = self._get_active_stations()

        # First, ensure all buoy stations exist in the database
        self._sync_buoy_stations(stations)

        # Then fetch current observations
        for station_id in stations:
            try:
                self.logger.info(f"Fetching data for station {station_id}")
                obs = self._fetch_station_data(station_id)

                if obs:
                    stats['processed'] += 1
                    inserted = self._insert_observation(station_id, obs)
                    if inserted:
                        stats['inserted'] += 1
                    else:
                        stats['skipped'] += 1
                else:
                    stats['skipped'] += 1

            except Exception as e:
                self.logger.warning(f"Error fetching station {station_id}: {e}")
                stats['skipped'] += 1

        return stats

    def _sync_buoy_stations(self, stations: List[str]):
        """Ensure buoy stations exist in the database"""
        with self.conn.cursor() as cur:
            for station_id in stations:
                if station_id in BUOY_STATIONS:
                    info = BUOY_STATIONS[station_id]
                    cur.execute("""
                        INSERT INTO buoy_stations (station_id, station_name, latitude, longitude, location, station_type, is_active)
                        VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), 'buoy', true)
                        ON CONFLICT (station_id) DO UPDATE SET
                            station_name = EXCLUDED.station_name,
                            is_active = true
                    """, (station_id, info['name'], info['lat'], info['lon'], info['lon'], info['lat']))

            self.conn.commit()
            self.logger.info(f"Synced {len(stations)} buoy stations")

    def _fetch_station_data(self, station_id: str) -> Optional[Dict]:
        """Fetch current observation from NDBC station"""
        url = f"{self.NDBC_BASE_URL}/{station_id}.txt"

        try:
            response = httpx.get(url, timeout=30.0)
            response.raise_for_status()

            lines = response.text.strip().split('\n')
            if len(lines) < 3:
                return None

            # Parse header and first data line
            # Header format: #YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE
            header = lines[0].replace('#', '').split()
            # Skip units line (line 1)
            data_line = lines[2].split()

            if len(data_line) < 10:
                return None

            obs = {}

            # Parse timestamp
            try:
                year = int(data_line[0])
                month = int(data_line[1])
                day = int(data_line[2])
                hour = int(data_line[3])
                minute = int(data_line[4])
                obs['recorded_at'] = datetime(year, month, day, hour, minute)
            except (ValueError, IndexError):
                return None

            # Parse weather values (MM = missing)
            def parse_val(idx, convert_func=float):
                try:
                    val = data_line[idx]
                    if val == 'MM' or val == 'N/A':
                        return None
                    return convert_func(val)
                except (IndexError, ValueError):
                    return None

            # Wind direction (degrees)
            obs['wind_direction'] = parse_val(5, int)

            # Wind speed (m/s -> knots)
            wspd = parse_val(6)
            obs['wind_speed_kts'] = round(wspd * 1.944, 1) if wspd else None

            # Wind gust (m/s -> knots)
            gust = parse_val(7)
            obs['wind_gust_kts'] = round(gust * 1.944, 1) if gust else None

            # Wave height (m -> ft)
            wvht = parse_val(8)
            obs['wave_height_ft'] = round(wvht * 3.281, 1) if wvht else None

            # Dominant wave period (seconds)
            obs['wave_period_sec'] = parse_val(9)

            # Average wave period
            obs['avg_wave_period_sec'] = parse_val(10)

            # Mean wave direction
            obs['wave_direction'] = parse_val(11, int)

            # Pressure (hPa -> mb, same units)
            obs['pressure_mb'] = parse_val(12)

            # Air temp (C -> F)
            atmp = parse_val(13)
            obs['air_temp_f'] = round(atmp * 9/5 + 32, 1) if atmp else None

            # Water temp (C -> F)
            wtmp = parse_val(14)
            obs['water_temp_f'] = round(wtmp * 9/5 + 32, 1) if wtmp else None

            # Dew point (C -> F)
            dewp = parse_val(15)
            obs['dewpoint_f'] = round(dewp * 9/5 + 32, 1) if dewp else None

            # Visibility (nautical miles)
            obs['visibility_nm'] = parse_val(16)

            # Pressure tendency
            ptdy = parse_val(17)
            if ptdy is not None:
                if ptdy > 0.5:
                    obs['pressure_tendency'] = 'rising'
                elif ptdy < -0.5:
                    obs['pressure_tendency'] = 'falling'
                else:
                    obs['pressure_tendency'] = 'steady'

            # Tide (ft)
            obs['tide_height_ft'] = parse_val(18)

            # Calculate fishing score
            obs['fishing_score'] = self._calculate_fishing_score(obs)

            return obs

        except httpx.HTTPError as e:
            self.logger.warning(f"HTTP error fetching {station_id}: {e}")
            return None

    def _calculate_fishing_score(self, obs: Dict) -> int:
        """Calculate fishing conditions score (0-100)"""
        score = 50  # Base score

        # Water temp scoring (optimal: 68-78F for offshore)
        water_temp = obs.get('water_temp_f')
        if water_temp:
            if 68 <= water_temp <= 78:
                score += 20
            elif 60 <= water_temp <= 85:
                score += 10
            else:
                score -= 10

        # Wind scoring (optimal: < 15 kts)
        wind = obs.get('wind_speed_kts')
        if wind is not None:
            if wind < 10:
                score += 15
            elif wind < 15:
                score += 10
            elif wind < 20:
                score += 0
            else:
                score -= 15

        # Wave scoring (optimal: < 3 ft)
        waves = obs.get('wave_height_ft')
        if waves is not None:
            if waves < 2:
                score += 15
            elif waves < 4:
                score += 5
            else:
                score -= 10

        return max(0, min(100, score))

    def _insert_observation(self, station_id: str, obs: Dict) -> bool:
        """Insert weather observation into database"""
        station_info = BUOY_STATIONS.get(station_id, {})
        lat = station_info.get('lat')
        lon = station_info.get('lon')

        with self.conn.cursor() as cur:
            # Check if we already have this observation (same station + time)
            cur.execute("""
                SELECT id FROM weather_observations
                WHERE buoy_id = %s AND recorded_at = %s
            """, (station_id, obs['recorded_at']))

            if cur.fetchone():
                return False  # Already exists

            cur.execute("""
                INSERT INTO weather_observations (
                    recorded_at, location, buoy_id, station_name,
                    air_temp_f, water_temp_f, wind_speed_kts, wind_gust_kts,
                    wind_direction, pressure_mb, pressure_tendency,
                    wave_height_ft, wave_period_sec, wave_direction,
                    visibility_nm, tide_height_ft, fishing_score, source
                ) VALUES (
                    %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ndbc'
                )
            """, (
                obs['recorded_at'], lon, lat, station_id, station_info.get('name'),
                obs.get('air_temp_f'), obs.get('water_temp_f'),
                obs.get('wind_speed_kts'), obs.get('wind_gust_kts'),
                obs.get('wind_direction'), obs.get('pressure_mb'),
                obs.get('pressure_tendency'), obs.get('wave_height_ft'),
                obs.get('wave_period_sec'), obs.get('wave_direction'),
                obs.get('visibility_nm'), obs.get('tide_height_ft'),
                obs.get('fishing_score')
            ))

            self.conn.commit()
            return True


def main():
    """Run weather harvester"""
    harvester = WeatherHarvester()
    stats = harvester.run(sync_type='incremental')
    print(f"Weather sync completed: {stats}")


if __name__ == "__main__":
    main()
