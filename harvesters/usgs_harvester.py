"""
USGS NWIS Stream Discharge Harvester
Pulls instantaneous values (discharge, water temp, gage height) from USGS Water Services API
https://waterservices.usgs.gov/
"""

import httpx
from datetime import datetime, timezone
from typing import Dict, List
from harvesters.base import BaseHarvester


# South Shore Long Island USGS stream stations
USGS_STATIONS = [
    '01310740',  # Reynolds Channel at Point Lookout
    '01309225',  # Great South Bay at Lindenhurst
    '01305575',  # Carmans River at Shirley
    '01304920',  # Moriches Bay at East Moriches
    '01304746',  # Shinnecock Bay at Ponquogue
    '01305000',  # Carmans River at Yaphank
    '01305500',  # Swan River at East Patchogue
    '01310521',  # Hudson Creek at Freeport
    '01311143',  # Hog Island Channel at Island Park
    '01311145',  # East Rockaway Inlet at Atlantic Beach
]

# USGS parameter codes
PARAM_DISCHARGE = '00060'   # Discharge (cfs)
PARAM_WATER_TEMP = '00010'  # Water temperature (°C)
PARAM_GAGE_HEIGHT = '00065' # Gage height (ft)


class USGSHarvester(BaseHarvester):
    """Harvester for USGS NWIS instantaneous stream data"""

    NWIS_BASE_URL = "https://waterservices.usgs.gov/nwis/iv/"

    def __init__(self):
        super().__init__('usgs_streams')

    def _get_active_stations(self) -> List[str]:
        """Get station IDs from the database"""
        with self.conn.cursor() as cur:
            cur.execute("SELECT station_id FROM usgs_stream_stations WHERE is_active = true ORDER BY station_id")
            db_stations = [row[0] for row in cur.fetchall()]
        if db_stations:
            self.logger.info(f"Found {len(db_stations)} active USGS stations in database")
            return db_stations
        return USGS_STATIONS

    def sync(self, **kwargs) -> Dict:
        """Fetch instantaneous values from USGS NWIS for all stations"""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        stations = self._get_active_stations()
        sites_param = ','.join(stations)

        params = {
            'format': 'json',
            'sites': sites_param,
            'parameterCd': f'{PARAM_DISCHARGE},{PARAM_WATER_TEMP},{PARAM_GAGE_HEIGHT}',
            'period': 'PT2H',
            'siteStatus': 'active',
        }

        try:
            self.logger.info(f"Fetching USGS data for {len(stations)} stations")
            response = httpx.get(
                self.NWIS_BASE_URL,
                params=params,
                timeout=30.0,
                headers={'Accept': 'application/json'}
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error fetching USGS data: {e}")
            return stats
        except Exception as e:
            self.logger.error(f"Error fetching USGS data: {e}")
            return stats

        time_series = data.get('value', {}).get('timeSeries', [])
        self.logger.info(f"Got {len(time_series)} time series from USGS")

        # Organize readings by station + timestamp
        # Key: (station_id, recorded_at) -> {discharge_cfs, water_temp_c, water_temp_f, gage_height_ft, qualifier}
        readings = {}

        for ts in time_series:
            try:
                site_code = ts['sourceInfo']['siteCode'][0]['value']
                variable_code = ts['variable']['variableCode'][0]['value']
                values = ts.get('values', [{}])[0].get('value', [])

                for val in values:
                    raw_value = val.get('value')
                    if raw_value is None or raw_value == '' or raw_value == '-999999':
                        continue

                    numeric_val = float(raw_value)
                    dt_str = val.get('dateTime', '')
                    qualifier = val.get('qualifiers', ['P'])[0] if val.get('qualifiers') else 'P'

                    # Parse ISO datetime
                    recorded_at = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                    if recorded_at.tzinfo is None:
                        recorded_at = recorded_at.replace(tzinfo=timezone.utc)

                    key = (site_code, recorded_at)
                    if key not in readings:
                        readings[key] = {
                            'station_id': site_code,
                            'recorded_at': recorded_at,
                            'discharge_cfs': None,
                            'water_temp_c': None,
                            'water_temp_f': None,
                            'gage_height_ft': None,
                            'qualifier': qualifier,
                        }

                    if variable_code == PARAM_DISCHARGE:
                        readings[key]['discharge_cfs'] = numeric_val
                    elif variable_code == PARAM_WATER_TEMP:
                        readings[key]['water_temp_c'] = numeric_val
                        readings[key]['water_temp_f'] = round(numeric_val * 9.0 / 5.0 + 32.0, 2)
                    elif variable_code == PARAM_GAGE_HEIGHT:
                        readings[key]['gage_height_ft'] = numeric_val

                    stats['processed'] += 1

            except (KeyError, IndexError, ValueError) as e:
                self.logger.debug(f"Skipping time series entry: {e}")
                stats['skipped'] += 1

        # Upsert all readings
        with self.conn.cursor() as cur:
            for reading in readings.values():
                try:
                    cur.execute("""
                        INSERT INTO usgs_discharge_readings
                            (station_id, recorded_at, discharge_cfs, water_temp_c, water_temp_f, gage_height_ft, qualifier)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (station_id, recorded_at) DO UPDATE SET
                            discharge_cfs = COALESCE(EXCLUDED.discharge_cfs, usgs_discharge_readings.discharge_cfs),
                            water_temp_c = COALESCE(EXCLUDED.water_temp_c, usgs_discharge_readings.water_temp_c),
                            water_temp_f = COALESCE(EXCLUDED.water_temp_f, usgs_discharge_readings.water_temp_f),
                            gage_height_ft = COALESCE(EXCLUDED.gage_height_ft, usgs_discharge_readings.gage_height_ft),
                            qualifier = EXCLUDED.qualifier
                    """, (
                        reading['station_id'],
                        reading['recorded_at'],
                        reading['discharge_cfs'],
                        reading['water_temp_c'],
                        reading['water_temp_f'],
                        reading['gage_height_ft'],
                        reading['qualifier'],
                    ))
                    stats['inserted'] += 1
                except Exception as e:
                    self.logger.debug(f"Skipping reading: {e}")
                    stats['skipped'] += 1

            self.conn.commit()

        self.logger.info(f"Upserted {stats['inserted']} readings for {len(stations)} stations")
        return stats


def main():
    """Run USGS harvester"""
    harvester = USGSHarvester()
    stats = harvester.run(sync_type='incremental')
    print(f"USGS sync completed: {stats}")


if __name__ == "__main__":
    main()
