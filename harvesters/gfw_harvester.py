"""
Global Fishing Watch API Harvester
Pulls fishing events, loitering, vessel data, effort grids, SAR detections,
offshore infrastructure, AIS presence, and vessel insights from GFW API v3.

API docs: https://globalfishingwatch.org/our-apis/documentation
"""

import hashlib
import json
import os
import random
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from harvesters.base import BaseHarvester


# Mid-Atlantic/Northeast fishing hotspots (lat, lon, radius, weight)
FISHING_HOTSPOTS = [
    {'name': 'Hudson Canyon',      'lat': 39.5, 'lon': -72.5, 'r': 0.5, 'w': 15},
    {'name': 'Block Canyon',       'lat': 40.0, 'lon': -71.5, 'r': 0.4, 'w': 10},
    {'name': 'Norfolk Canyon',     'lat': 37.0, 'lon': -74.5, 'r': 0.5, 'w': 10},
    {'name': 'Baltimore Canyon',   'lat': 38.2, 'lon': -73.8, 'r': 0.4, 'w': 8},
    {'name': 'Wilmington Canyon',  'lat': 38.5, 'lon': -73.5, 'r': 0.3, 'w': 7},
    {'name': 'Cape Hatteras',      'lat': 35.2, 'lon': -75.0, 'r': 0.6, 'w': 12},
    {'name': 'Georges Bank',       'lat': 41.3, 'lon': -68.5, 'r': 0.8, 'w': 12},
    {'name': 'Stellwagen Bank',    'lat': 42.3, 'lon': -70.3, 'r': 0.3, 'w': 6},
    {'name': 'NJ Offshore',        'lat': 39.8, 'lon': -73.2, 'r': 0.5, 'w': 8},
    {'name': 'Montauk Offshore',   'lat': 40.8, 'lon': -71.5, 'r': 0.4, 'w': 7},
    {'name': 'Long Island Shelf',  'lat': 40.2, 'lon': -72.8, 'r': 0.5, 'w': 6},
    {'name': 'Diamond Shoals',     'lat': 35.0, 'lon': -75.5, 'r': 0.4, 'w': 5},
]

GFW_GEAR_TYPES = [
    'trawlers', 'drifting_longlines', 'set_longlines', 'purse_seines',
    'trollers', 'pole_and_line', 'fixed_gear', 'squid_jigger',
]

GEAR_TO_METHOD = {
    'trawlers': 'trawl',
    'drifting_longlines': 'longline',
    'set_longlines': 'longline',
    'purse_seines': 'purse_seine',
    'trollers': 'troll',
    'pole_and_line': 'rod_reel',
    'fixed_gear': 'trap',
    'squid_jigger': 'handline',
}

VESSEL_FLAGS = ['USA', 'USA', 'USA', 'USA', 'CAN', 'MEX', 'JPN', 'KOR', 'TWN', 'ESP']

MONTHLY_ACTIVITY = [0.4, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.2, 1.0, 0.8, 0.5, 0.4]

GEAR_SPECIES_MAP = {
    'drifting_longlines': ['SWO', 'YFT', 'BET', 'BFT', 'ALB'],
    'set_longlines':      ['SWO', 'YFT', 'BET'],
    'trollers':           ['YFT', 'DOL', 'WAH', 'BFT', 'ALB'],
    'pole_and_line':      ['YFT', 'SKJ', 'ALB'],
    'purse_seines':       ['SKJ', 'YFT', 'ALB'],
    'trawlers':           [],
    'fixed_gear':         [],
    'squid_jigger':       [],
}


class GFWHarvester(BaseHarvester):
    """Harvester for Global Fishing Watch data - all endpoints"""

    BASE_URL = "https://gateway.api.globalfishingwatch.org/v3"

    # Default bounding box: Mid-Atlantic / Northeast US
    DEFAULT_BBOX = [-76.0, 34.0, -67.0, 43.0]

    def __init__(self):
        super().__init__('gfw')
        self.api_key = os.getenv('GFW_API_KEY', '')
        self._daily_requests = 0

    def _get_headers(self) -> Dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
    def _api_request(self, method: str, endpoint: str, params: Dict = None,
                     json_body: Dict = None, timeout: float = 120.0) -> Optional[Dict]:
        """Make an authenticated request to GFW API with retries."""
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = httpx.request(
                method, url,
                headers=self._get_headers(),
                params=params,
                json=json_body,
                timeout=timeout
            )
            self._daily_requests += 1
            if response.status_code == 401:
                self.logger.error("GFW authentication failed - check GFW_API_KEY")
                return None
            if response.status_code == 429:
                self.logger.warning("GFW rate limited, retrying...")
                raise Exception("Rate limited")
            if response.status_code == 524:
                self.logger.warning("GFW request timed out (524), retrying...")
                raise Exception("Timeout 524")
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            self.logger.error(f"GFW API error on {method} {endpoint}: {e}")
            raise

    def _api_get(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        return self._api_request("GET", endpoint, params=params)

    def _api_post(self, endpoint: str, json_body: Dict = None,
                  params: Dict = None) -> Optional[Dict]:
        return self._api_request("POST", endpoint, params=params, json_body=json_body)

    def _make_bbox_geojson(self, bbox: List[float]) -> str:
        min_lon, min_lat, max_lon, max_lat = bbox
        return json.dumps({
            "type": "Polygon",
            "coordinates": [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]]
        })

    # ------------------------------------------------------------------
    # Main sync entry point
    # ------------------------------------------------------------------

    def sync(self, days_back: int = 30, bbox: List[float] = None, **kwargs) -> Dict:
        """
        Sync all GFW data types.
        Falls back to deterministic sample data if no API key is configured.
        """
        if bbox is None:
            bbox = self.DEFAULT_BBOX

        total_stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if not self.api_key:
            self.logger.info("No GFW_API_KEY - generating deterministic sample data")
            return self._generate_sample_data(days_back, bbox)

        self.logger.info(f"Starting GFW API sync (days_back={days_back})")

        # Run each data type sync and accumulate stats
        syncs = [
            ("fishing_events", self._sync_fishing_events),
            ("loitering_events", self._sync_loitering_events),
            ("vessels", self._sync_vessels_search),
            ("fishing_effort", self._sync_fishing_effort),
            ("ais_presence", self._sync_ais_presence),
            ("sar_detections", self._sync_sar_detections),
        ]

        for name, sync_fn in syncs:
            try:
                self.logger.info(f"Syncing {name}...")
                stats = sync_fn(days_back, bbox)
                for k in total_stats:
                    total_stats[k] += stats.get(k, 0)
                self.logger.info(f"  {name}: {stats}")
            except Exception as e:
                self.logger.error(f"  {name} failed: {e}")

        return total_stats

    # ------------------------------------------------------------------
    # 1. Fishing Events
    # ------------------------------------------------------------------

    def _sync_fishing_events(self, days_back: int, bbox: List[float]) -> Dict:
        """Fetch fishing events from GFW Events API."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)

        events = self._fetch_events_paginated(
            "fishing", start_date, end_date, bbox
        )
        self.logger.info(f"Fetched {len(events)} fishing events")

        for event in events:
            stats['processed'] += 1
            result = self._insert_fishing_event(event)
            if result == 'inserted':
                stats['inserted'] += 1
            elif result == 'updated':
                stats['updated'] += 1
            else:
                stats['skipped'] += 1

            # Also upsert vessel and create effort/catch records
            vessel = event.get('vessel', {})
            ssvid = vessel.get('ssvid')
            if ssvid:
                self._upsert_vessel_from_event(vessel, event)
                self._insert_effort_from_event(event)

        return stats

    def _fetch_events_paginated(self, event_type: str, start_date: datetime,
                                end_date: datetime, bbox: List[float],
                                max_pages: int = 10) -> List[Dict]:
        """Fetch events with pagination from GFW Events API."""
        dataset_map = {
            "fishing": "public-global-fishing-events:latest",
            "loitering": "public-global-loitering-events:latest",
            "encounter": "public-global-encounters-events:latest",
            "port_visit": "public-global-port-visits-events:latest",
        }

        dataset = dataset_map.get(event_type, f"public-global-{event_type}-events:latest")

        params = {
            "datasets[0]": dataset,
            "start-date": start_date.strftime("%Y-%m-%d"),
            "end-date": end_date.strftime("%Y-%m-%d"),
            "limit": 500,
            "offset": 0,
        }
        # Note: geometry is NOT passed as query param for events (causes 422)
        # Events endpoint returns global results that we filter locally

        all_events = []
        for _ in range(max_pages):
            data = self._api_get("/events", params=params)
            if not data:
                break

            entries = data.get("entries", [])
            all_events.extend(entries)

            if len(entries) < params["limit"]:
                break
            params["offset"] += len(entries)

        return all_events

    def _insert_fishing_event(self, event: Dict) -> str:
        """Insert a fishing event into gfw_fishing_events."""
        event_id = event.get('id')
        if not event_id:
            return 'skipped'

        position = event.get('position', {})
        lat = position.get('lat')
        lon = position.get('lon')
        if lat is None or lon is None:
            return 'skipped'

        start_str = event.get('start', '')
        end_str = event.get('end', '')
        start_time = end_time = None
        duration_hours = 0

        try:
            start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
        try:
            end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

        if start_time and end_time:
            duration_hours = (end_time - start_time).total_seconds() / 3600

        vessel = event.get('vessel', {})
        distances = event.get('distances', {})

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM gfw_fishing_events WHERE event_id = %s",
                (event_id,)
            )
            if cur.fetchone():
                return 'skipped'

            cur.execute("""
                INSERT INTO gfw_fishing_events (
                    event_id, event_type, vessel_id, vessel_name, vessel_mmsi,
                    vessel_flag, vessel_gear_type, start_time, end_time,
                    duration_hours, location, latitude, longitude,
                    regions, fishing_hours,
                    distance_from_shore_km, distance_from_port_km, metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb
                )
            """, (
                event_id,
                event.get('type', 'fishing'),
                vessel.get('id'),
                vessel.get('name'),
                vessel.get('ssvid'),
                vessel.get('flag'),
                vessel.get('geartype'),
                start_time,
                end_time,
                round(duration_hours, 2),
                lon, lat, lat, lon,
                json.dumps(event.get('regions', {})),
                duration_hours,
                distances.get('startDistanceFromShoreKm'),
                distances.get('startDistanceFromPortKm'),
                json.dumps({k: v for k, v in event.items()
                           if k not in ('id', 'vessel', 'position', 'regions', 'distances')}),
            ))
            self.conn.commit()
            return 'inserted'

    # ------------------------------------------------------------------
    # 2. Loitering Events
    # ------------------------------------------------------------------

    def _sync_loitering_events(self, days_back: int, bbox: List[float]) -> Dict:
        """Fetch loitering events from GFW Events API."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)

        events = self._fetch_events_paginated(
            "loitering", start_date, end_date, bbox
        )
        self.logger.info(f"Fetched {len(events)} loitering events")

        for event in events:
            stats['processed'] += 1
            result = self._insert_loitering_event(event)
            if result == 'inserted':
                stats['inserted'] += 1
            else:
                stats['skipped'] += 1

        return stats

    def _insert_loitering_event(self, event: Dict) -> str:
        """Insert a loitering event into gfw_loitering_events."""
        event_id = event.get('id')
        if not event_id:
            return 'skipped'

        position = event.get('position', {})
        lat = position.get('lat')
        lon = position.get('lon')
        if lat is None or lon is None:
            return 'skipped'

        start_str = event.get('start', '')
        end_str = event.get('end', '')
        start_time = end_time = None
        duration_hours = 0

        try:
            start_time = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass
        try:
            end_time = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

        if start_time and end_time:
            duration_hours = (end_time - start_time).total_seconds() / 3600

        vessel = event.get('vessel', {})
        loitering = event.get('loitering', {})
        distances = event.get('distances', {})

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM gfw_loitering_events WHERE event_id = %s",
                (event_id,)
            )
            if cur.fetchone():
                return 'skipped'

            cur.execute("""
                INSERT INTO gfw_loitering_events (
                    event_id, vessel_id, vessel_name, vessel_mmsi,
                    vessel_flag, vessel_type, start_time, end_time,
                    duration_hours, location, latitude, longitude,
                    total_distance_km, avg_speed_knots,
                    avg_distance_from_shore_km, regions, metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                )
            """, (
                event_id,
                vessel.get('id'),
                vessel.get('name'),
                vessel.get('ssvid'),
                vessel.get('flag'),
                vessel.get('type'),
                start_time,
                end_time,
                round(duration_hours, 2),
                lon, lat, lat, lon,
                loitering.get('totalDistanceKm'),
                loitering.get('averageSpeedKnots'),
                distances.get('startDistanceFromShoreKm'),
                json.dumps(event.get('regions', {})),
                json.dumps(loitering),
            ))
            self.conn.commit()
            return 'inserted'

    # ------------------------------------------------------------------
    # 3. Vessel Search & Identity
    # ------------------------------------------------------------------

    def _sync_vessels_search(self, days_back: int, bbox: List[float]) -> Dict:
        """Search for vessels and sync their data.
        Uses cursor-based pagination (since param), NOT offset (causes 422)."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        search_terms = ['fishing', 'trawler', 'longliner', 'seiner',
                        'atlantic', 'ocean', 'cape', 'eagle']

        for term in search_terms:
            try:
                params = {
                    "datasets[0]": "public-global-vessel-identity:latest",
                    "query": term,
                    "limit": 50,
                }

                data = self._api_get("/vessels/search", params=params)
                if not data:
                    continue

                entries = data.get("entries", [])
                self.logger.info(f"  Vessel search '{term}': {len(entries)} results")

                for vessel_data in entries:
                    stats['processed'] += 1
                    result = self._upsert_vessel_from_search(vessel_data)
                    if result == 'inserted':
                        stats['inserted'] += 1
                    elif result == 'updated':
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1

                # Fetch additional pages using cursor-based pagination
                since = data.get('since')
                pages_fetched = 1
                while since and pages_fetched < 4:
                    params['since'] = since
                    data = self._api_get("/vessels/search", params=params)
                    if not data:
                        break
                    entries = data.get("entries", [])
                    if not entries:
                        break
                    for vessel_data in entries:
                        stats['processed'] += 1
                        result = self._upsert_vessel_from_search(vessel_data)
                        if result == 'inserted':
                            stats['inserted'] += 1
                        elif result == 'updated':
                            stats['updated'] += 1
                        else:
                            stats['skipped'] += 1
                    since = data.get('since')
                    pages_fetched += 1

            except Exception as e:
                self.logger.warning(f"  Vessel search '{term}' failed: {e}")

        return stats

    def _upsert_vessel_from_search(self, vessel_data: Dict) -> str:
        """Upsert a vessel from search results."""
        # GFW vessel identity has nested registryInfo, combinedSourcesInfo, selfReportedInfo
        registry_info = vessel_data.get('registryInfo', [])
        combined = vessel_data.get('combinedSourcesInfo', [])
        self_reported = vessel_data.get('selfReportedInfo', [])

        reg = registry_info[0] if registry_info and isinstance(registry_info, list) else {}
        comb = combined[0] if combined and isinstance(combined, list) else {}
        self_rep = self_reported[0] if self_reported and isinstance(self_reported, list) else {}

        # ssvid (MMSI) is primarily in selfReportedInfo
        ssvid = self_rep.get('ssvid') or comb.get('ssvid') or vessel_data.get('ssvid')
        if not ssvid:
            return 'skipped'

        vessel_name = reg.get('shipname') or self_rep.get('shipname') or comb.get('shipname')
        flag = reg.get('flag') or self_rep.get('flag') or comb.get('flag')

        # Gear types are nested as lists of objects with 'name' key
        gear_types = comb.get('geartypes', reg.get('geartypes', []))
        gear_type = gear_types[0].get('name') if gear_types and isinstance(gear_types, list) and gear_types[0] else None

        ship_types = comb.get('shiptypes', reg.get('shiptypes', []))
        vessel_type = ship_types[0].get('name') if ship_types and isinstance(ship_types, list) and ship_types[0] else None

        imo = reg.get('imo') or self_rep.get('imo')
        length = reg.get('lengthM')
        tonnage = reg.get('tonnageGt')

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vessels (mmsi, imo, vessel_name, flag_country, vessel_type,
                                    length_meters, gross_tonnage, gear_type, source, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'gfw', %s::jsonb)
                ON CONFLICT (mmsi) DO UPDATE SET
                    imo = COALESCE(EXCLUDED.imo, vessels.imo),
                    vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name),
                    flag_country = COALESCE(EXCLUDED.flag_country, vessels.flag_country),
                    vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
                    length_meters = COALESCE(EXCLUDED.length_meters, vessels.length_meters),
                    gross_tonnage = COALESCE(EXCLUDED.gross_tonnage, vessels.gross_tonnage),
                    gear_type = COALESCE(EXCLUDED.gear_type, vessels.gear_type),
                    metadata = COALESCE(EXCLUDED.metadata, vessels.metadata),
                    updated_at = NOW()
            """, (
                ssvid, imo, vessel_name, flag, vessel_type,
                length, tonnage, gear_type,
                json.dumps({
                    'gfw_id': vessel_data.get('id'),
                    'selfReportedInfo': vessel_data.get('selfReportedInfo'),
                }),
            ))
            self.conn.commit()

            if cur.statusmessage and 'UPDATE' in cur.statusmessage:
                return 'updated'
            return 'inserted'

    # ------------------------------------------------------------------
    # 4. Fishing Effort (4Wings API)
    # ------------------------------------------------------------------

    def _sync_fishing_effort(self, days_back: int, bbox: List[float]) -> Dict:
        """Fetch fishing effort data from 4Wings API (POST with geojson body)."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=min(days_back, 366))

        min_lon, min_lat, max_lon, max_lat = bbox

        params = {
            "datasets[0]": "public-global-fishing-effort:latest",
            "date-range": f"{start_date.strftime('%Y-%m-%d')},{end_date.strftime('%Y-%m-%d')}",
            "spatial-resolution": "LOW",
            "temporal-resolution": "MONTHLY",
            "group-by": "GEARTYPE",
            "format": "JSON",
        }

        geojson_body = {
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]]
            }
        }

        try:
            data = self._api_post("/4wings/report", params=params, json_body=geojson_body)
            if not data:
                self.logger.warning("No fishing effort data returned")
                return stats

            # Response format: {"entries": [{"dataset-key": [row, ...]}]}
            raw_entries = data.get('entries', []) if isinstance(data, dict) else data
            if isinstance(raw_entries, dict):
                raw_entries = [raw_entries]

            # Flatten: entries may be [{dataset_key: [rows]}]
            entries = []
            for raw in raw_entries:
                if isinstance(raw, dict):
                    for key, rows in raw.items():
                        if isinstance(rows, list):
                            entries.extend(rows)
                        else:
                            entries.append(raw)
                            break
                elif isinstance(raw, list):
                    entries.extend(raw)

            self.logger.info(f"  Fishing effort: {len(entries)} grid cells")

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                stats['processed'] += 1

                lat_val = entry.get('lat', entry.get('latitude'))
                lon_val = entry.get('lon', entry.get('longitude'))
                hours = entry.get('hours', entry.get('fishingHours', entry.get('value', 0)))
                event_date = entry.get('date', entry.get('timePeriod', start_date.strftime("%Y-%m-%d")))
                gear = entry.get('geartype', entry.get('gearType', ''))
                flag = entry.get('flag', entry.get('flagState', ''))
                vessel_count = entry.get('vesselIDs', entry.get('vesselCount', entry.get('vessels', 1)))

                if lat_val is not None and lon_val is not None:
                    cell_id = f"4w_{event_date}_{lat_val}_{lon_val}_{gear}"
                    inserted = self._insert_effort_record(
                        cell_id, event_date if isinstance(event_date, str) else event_date,
                        float(lat_val), float(lon_val), float(hours or 0),
                        gear, flag, int(vessel_count) if vessel_count else 1
                    )
                    if inserted:
                        stats['inserted'] += 1
                    else:
                        stats['skipped'] += 1

        except Exception as e:
            self.logger.warning(f"Fishing effort sync error: {e}")

        return stats

    # ------------------------------------------------------------------
    # 5. AIS Vessel Presence
    # ------------------------------------------------------------------

    def _sync_ais_presence(self, days_back: int, bbox: List[float]) -> Dict:
        """Fetch AIS vessel presence data from 4Wings API (POST with geojson body)."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=min(days_back, 366))

        min_lon, min_lat, max_lon, max_lat = bbox

        params = {
            "datasets[0]": "public-global-presence:latest",
            "date-range": f"{start_date.strftime('%Y-%m-%d')},{end_date.strftime('%Y-%m-%d')}",
            "spatial-resolution": "LOW",
            "temporal-resolution": "MONTHLY",
            "format": "JSON",
        }

        geojson_body = {
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]]
            }
        }

        try:
            data = self._api_post("/4wings/report", params=params, json_body=geojson_body)
            if not data:
                self.logger.warning("No AIS presence data returned")
                return stats

            # Response format: {"entries": [{"dataset-key": [row, ...]}]}
            raw_entries = data.get('entries', []) if isinstance(data, dict) else data
            if isinstance(raw_entries, dict):
                raw_entries = [raw_entries]

            # Flatten: entries may be [{dataset_key: [rows]}]
            entries = []
            for raw in raw_entries:
                if isinstance(raw, dict):
                    for key, rows in raw.items():
                        if isinstance(rows, list):
                            entries.extend(rows)
                        else:
                            entries.append(raw)
                            break
                elif isinstance(raw, list):
                    entries.extend(raw)

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                stats['processed'] += 1

                lat_val = entry.get('lat', entry.get('latitude'))
                lon_val = entry.get('lon', entry.get('longitude'))
                hours = entry.get('hours', entry.get('value', 0))
                event_date = entry.get('date', entry.get('timePeriod',
                                       start_date.strftime("%Y-%m-%d")))
                vessel_type = entry.get('vesselType', entry.get('vessel_type', ''))
                vessel_count = entry.get('vesselCount', entry.get('vessels', 1))

                if lat_val is not None and lon_val is not None:
                    cell_id = f"pres_{event_date}_{lat_val}_{lon_val}_{vessel_type}"

                    with self.conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM gfw_ais_presence WHERE cell_id = %s",
                            (cell_id,)
                        )
                        if cur.fetchone():
                            stats['skipped'] += 1
                            continue

                        date_val = event_date
                        if isinstance(date_val, str):
                            try:
                                date_val = datetime.strptime(
                                    date_val[:10], "%Y-%m-%d"
                                ).date()
                            except ValueError:
                                date_val = start_date.date()

                        cur.execute("""
                            INSERT INTO gfw_ais_presence (
                                cell_id, date, location, lat_bin, lon_bin,
                                vessel_count, hours_total, vessel_type, source
                            ) VALUES (
                                %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                                %s, %s, %s, %s, %s, 'gfw'
                            )
                        """, (
                            cell_id, date_val,
                            float(lon_val), float(lat_val),
                            float(lat_val), float(lon_val),
                            vessel_count, float(hours or 0),
                            vessel_type,
                        ))
                        self.conn.commit()
                        stats['inserted'] += 1

        except Exception as e:
            self.logger.warning(f"AIS presence sync error: {e}")

        return stats

    # ------------------------------------------------------------------
    # 6. SAR Vessel Detections
    # ------------------------------------------------------------------

    def _sync_sar_detections(self, days_back: int, bbox: List[float]) -> Dict:
        """Fetch SAR vessel detection data from 4Wings API (POST with geojson body)."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=min(days_back, 366))

        min_lon, min_lat, max_lon, max_lat = bbox

        params = {
            "datasets[0]": "public-global-sar-presence:latest",
            "date-range": f"{start_date.strftime('%Y-%m-%d')},{end_date.strftime('%Y-%m-%d')}",
            "spatial-resolution": "LOW",
            "temporal-resolution": "MONTHLY",
            "format": "JSON",
        }

        geojson_body = {
            "geojson": {
                "type": "Polygon",
                "coordinates": [[
                    [min_lon, min_lat],
                    [max_lon, min_lat],
                    [max_lon, max_lat],
                    [min_lon, max_lat],
                    [min_lon, min_lat],
                ]]
            }
        }

        try:
            data = self._api_post("/4wings/report", params=params, json_body=geojson_body)
            if not data:
                self.logger.warning("No SAR detection data returned")
                return stats

            # Response format: {"entries": [{"dataset-key": [row, ...]}]}
            raw_entries = data.get('entries', []) if isinstance(data, dict) else data
            if isinstance(raw_entries, dict):
                raw_entries = [raw_entries]

            # Flatten: entries may be [{dataset_key: [rows]}]
            entries = []
            for raw in raw_entries:
                if isinstance(raw, dict):
                    for key, rows in raw.items():
                        if isinstance(rows, list):
                            entries.extend(rows)
                        else:
                            entries.append(raw)
                            break
                elif isinstance(raw, list):
                    entries.extend(raw)

            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                stats['processed'] += 1

                lat_val = entry.get('lat', entry.get('latitude'))
                lon_val = entry.get('lon', entry.get('longitude'))
                if lat_val is None or lon_val is None:
                    stats['skipped'] += 1
                    continue

                det_date = entry.get('date', entry.get('timePeriod',
                                     start_date.strftime("%Y-%m-%d")))
                detection_id = f"sar_{det_date}_{lat_val}_{lon_val}"

                with self.conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM gfw_sar_detections WHERE detection_id = %s",
                        (detection_id,)
                    )
                    if cur.fetchone():
                        stats['skipped'] += 1
                        continue

                    det_time = None
                    if isinstance(det_date, str):
                        try:
                            det_time = datetime.strptime(det_date[:10], "%Y-%m-%d")
                        except ValueError:
                            det_time = start_date

                    cur.execute("""
                        INSERT INTO gfw_sar_detections (
                            detection_id, detection_time, location, latitude, longitude,
                            confidence, metadata
                        ) VALUES (
                            %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s, %s, %s, %s::jsonb
                        )
                    """, (
                        detection_id, det_time,
                        float(lon_val), float(lat_val),
                        float(lat_val), float(lon_val),
                        entry.get('confidence', entry.get('value')),
                        json.dumps({k: v for k, v in entry.items()
                                   if k not in ('lat', 'lon', 'latitude', 'longitude')}),
                    ))
                    self.conn.commit()
                    stats['inserted'] += 1

        except Exception as e:
            self.logger.warning(f"SAR detections sync error: {e}")

        return stats

    # ------------------------------------------------------------------
    # 7. Vessel Insights (POST endpoint)
    # ------------------------------------------------------------------

    def sync_vessel_insights(self, vessel_ids: List[str],
                             start_date: str = None,
                             end_date: str = None) -> Dict:
        """Fetch insights for specific vessels."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if not self.api_key:
            return stats

        if not start_date:
            start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        body = {
            "vessels": vessel_ids,
            "startDate": start_date,
            "endDate": end_date,
            "includes": [
                "FISHING", "GAPS", "COVERAGE", "EVENTS_SUMMARY",
                "VESSEL_IDENTITY"
            ]
        }

        try:
            data = self._api_post("/vessels/insights", json_body=body)
            if not data:
                return stats

            vessels = data.get('vessels', data) if isinstance(data, dict) else data
            if not isinstance(vessels, list):
                vessels = [vessels]

            for vessel_insight in vessels:
                stats['processed'] += 1
                result = self._insert_vessel_insight(vessel_insight, start_date, end_date)
                if result == 'inserted':
                    stats['inserted'] += 1
                elif result == 'updated':
                    stats['updated'] += 1
                else:
                    stats['skipped'] += 1

        except Exception as e:
            self.logger.warning(f"Vessel insights error: {e}")

        return stats

    def _insert_vessel_insight(self, insight: Dict, start_date: str,
                               end_date: str) -> str:
        """Insert or update vessel insight."""
        vessel_id = insight.get('vesselId', insight.get('id', ''))
        if not vessel_id:
            return 'skipped'

        identity = insight.get('identity', {})
        fishing = insight.get('fishing', {})
        coverage = insight.get('coverage', {})
        gaps = insight.get('gaps', {})
        events = insight.get('eventsSummary', {})

        mmsi = identity.get('ssvid')
        name = identity.get('shipname')
        flag = identity.get('flag')
        gear = identity.get('geartype')
        vtype = identity.get('vesselType')

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO gfw_vessel_insights (
                    vessel_id, vessel_mmsi, vessel_name, vessel_flag,
                    vessel_gear_type, vessel_type,
                    apparent_fishing_hours, active_hours,
                    fishing_events_count, loitering_events_count,
                    encounter_events_count, port_visit_count,
                    coverage_percentage, gaps_count,
                    analysis_period_start, analysis_period_end, metadata
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s::jsonb
                )
                ON CONFLICT (vessel_id, analysis_period_start, analysis_period_end)
                DO UPDATE SET
                    apparent_fishing_hours = EXCLUDED.apparent_fishing_hours,
                    active_hours = EXCLUDED.active_hours,
                    fishing_events_count = EXCLUDED.fishing_events_count,
                    loitering_events_count = EXCLUDED.loitering_events_count,
                    encounter_events_count = EXCLUDED.encounter_events_count,
                    port_visit_count = EXCLUDED.port_visit_count,
                    coverage_percentage = EXCLUDED.coverage_percentage,
                    gaps_count = EXCLUDED.gaps_count,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """, (
                vessel_id, mmsi, name, flag, gear, vtype,
                fishing.get('totalFishingHours'),
                fishing.get('totalActiveHours'),
                events.get('fishing', 0),
                events.get('loitering', 0),
                events.get('encounter', 0),
                events.get('portVisit', 0),
                coverage.get('percentage'),
                gaps.get('count', 0),
                start_date, end_date,
                json.dumps(insight),
            ))
            self.conn.commit()
            if 'UPDATE' in (cur.statusmessage or ''):
                return 'updated'
            return 'inserted'

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _upsert_vessel_from_event(self, vessel: Dict, event: Dict):
        """Insert or update vessel from event data."""
        ssvid = vessel.get('ssvid')
        if not ssvid:
            return

        position = event.get('position', {})
        lat = position.get('lat')
        lon = position.get('lon')

        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vessels (mmsi, vessel_name, flag_country, gear_type, source,
                                    last_position, last_seen)
                VALUES (%s, %s, %s, %s, 'gfw',
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326), NOW())
                ON CONFLICT (mmsi) DO UPDATE SET
                    vessel_name = COALESCE(EXCLUDED.vessel_name, vessels.vessel_name),
                    flag_country = COALESCE(EXCLUDED.flag_country, vessels.flag_country),
                    gear_type = COALESCE(EXCLUDED.gear_type, vessels.gear_type),
                    last_position = EXCLUDED.last_position,
                    last_seen = NOW(),
                    updated_at = NOW()
            """, (
                ssvid,
                vessel.get('name'),
                vessel.get('flag'),
                vessel.get('geartype'),
                lon or 0, lat or 0,
            ))
            self.conn.commit()

    def _insert_effort_from_event(self, event: Dict):
        """Create a fishing_effort record from a fishing event."""
        event_id = event.get('id')
        if not event_id:
            return

        position = event.get('position', {})
        lat = position.get('lat')
        lon = position.get('lon')
        if lat is None or lon is None:
            return

        start_str = event.get('start', '')
        end_str = event.get('end', '')
        fishing_hours = 0
        event_date = datetime.now(timezone.utc).date()

        try:
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            event_date = start_dt.date()
            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            fishing_hours = (end_dt - start_dt).total_seconds() / 3600
        except (ValueError, AttributeError):
            pass

        vessel = event.get('vessel', {})
        source_id = f"gfw_{event_id}"

        self._insert_effort_record(
            source_id, event_date, lat, lon, fishing_hours,
            vessel.get('geartype', ''), vessel.get('flag', ''), 1
        )

    def _insert_effort_record(self, source_id: str, event_date, lat: float,
                              lon: float, hours: float, gear: str,
                              flag: str, vessel_count: int = 1) -> bool:
        """Insert a fishing effort record. Returns True if new."""
        if isinstance(event_date, str):
            try:
                event_date = datetime.strptime(event_date[:10], "%Y-%m-%d").date()
            except ValueError:
                event_date = datetime.now(timezone.utc).date()

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM fishing_effort WHERE source = 'gfw' AND cell_id = %s",
                (source_id,)
            )
            if cur.fetchone():
                return False

            cur.execute("""
                INSERT INTO fishing_effort (
                    cell_id, date, location, lat_bin, lon_bin,
                    fishing_hours, vessel_count, gear_type, flag_country, source
                ) VALUES (
                    %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s, %s, %s, %s, %s, %s, 'gfw'
                )
            """, (
                source_id, event_date, lon, lat, lat, lon,
                round(hours, 2), vessel_count, gear, flag,
            ))
            self.conn.commit()
            return True

    # ------------------------------------------------------------------
    # Deterministic sample data (no API key fallback)
    # ------------------------------------------------------------------

    def _generate_sample_data(self, days_back: int, bbox: List[float]) -> Dict:
        """Generate deterministic fishing data when no API key available."""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=days_back)

        species_map = self.get_species_map()
        hotspot_weights = [h['w'] for h in FISHING_HOTSPOTS]
        total_weight = sum(hotspot_weights)

        fleet_rng = random.Random(42)
        fleet = self._generate_fleet(fleet_rng, size=80)

        current_date = start_date
        while current_date <= end_date:
            day_seed = int(hashlib.md5(
                f"gfw_{current_date.isoformat()}".encode()
            ).hexdigest()[:8], 16)
            rng = random.Random(day_seed)

            month_mult = MONTHLY_ACTIVITY[current_date.month - 1]
            base_events = int(20 * month_mult)
            num_events = rng.randint(max(5, base_events - 5), base_events + 10)

            for i in range(num_events):
                stats['processed'] += 1
                hotspot = self._pick_hotspot(rng, hotspot_weights, total_weight)

                lat = round(hotspot['lat'] + rng.gauss(0, hotspot['r'] * 0.5), 4)
                lon = round(hotspot['lon'] + rng.gauss(0, hotspot['r'] * 0.5), 4)
                lat = max(bbox[1], min(bbox[3], lat))
                lon = max(bbox[0], min(bbox[2], lon))

                vessel = rng.choice(fleet)
                gear = vessel['gear']
                flag = vessel['flag']

                if 'longline' in gear:
                    hours = round(rng.uniform(6, 14), 2)
                elif gear == 'trawlers':
                    hours = round(rng.uniform(4, 12), 2)
                else:
                    hours = round(rng.uniform(2, 10), 2)

                source_id = f"gfw_{current_date.isoformat()}_{i:04d}"

                inserted = self._insert_effort_record(
                    source_id, current_date, lat, lon, hours, gear, flag
                )
                if inserted:
                    stats['inserted'] += 1
                else:
                    stats['skipped'] += 1

                possible_species = GEAR_SPECIES_MAP.get(gear, [])
                if possible_species and rng.random() < 0.35:
                    sp_code = rng.choice(possible_species)
                    if sp_code in species_map:
                        self._insert_catch_from_effort(
                            rng, source_id, species_map[sp_code], sp_code,
                            current_date, lat, lon, gear,
                        )

                self._upsert_simulated_vessel(vessel, lat, lon)

            current_date += timedelta(days=1)

        return stats

    def _generate_fleet(self, rng: random.Random, size: int) -> List[Dict]:
        fleet = []
        prefixes = [
            'ATLANTIC', 'OCEAN', 'SEA', 'CAPE', 'BLUE', 'STAR', 'DEEP',
            'NORTH', 'EAGLE', 'SPIRIT', 'SILVER', 'GOLDEN', 'STORM',
        ]
        suffixes = [
            'VOYAGER', 'KING', 'QUEEN', 'HUNTER', 'HAWK', 'RUNNER',
            'WIND', 'STAR', 'MIST', 'DAWN', 'CREST', 'LADY',
        ]
        for i in range(size):
            name = f"{rng.choice(prefixes)} {rng.choice(suffixes)}"
            mmsi = f"{rng.randint(300000000, 399999999)}"
            gear = rng.choice(GFW_GEAR_TYPES)
            flag = rng.choice(VESSEL_FLAGS)
            fleet.append({'mmsi': mmsi, 'name': name, 'gear': gear, 'flag': flag})
        return fleet

    def _pick_hotspot(self, rng, weights, total):
        r = rng.uniform(0, total)
        cumulative = 0
        for idx, w in enumerate(weights):
            cumulative += w
            if r <= cumulative:
                return FISHING_HOTSPOTS[idx]
        return FISHING_HOTSPOTS[-1]

    def _insert_catch_from_effort(self, rng, effort_source_id, species_id,
                                  species_code, catch_date, lat, lon, gear):
        from harvesters.noaa_harvester import TYPICAL_WEIGHTS

        catch_source_id = f"gfw_catch_{effort_source_id}"
        wt_lo, wt_hi = TYPICAL_WEIGHTS.get(species_code, (20, 100))
        weight = round(rng.uniform(wt_lo, wt_hi), 1)
        method = GEAR_TO_METHOD.get(gear, gear)

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM catches WHERE source = 'gfw' AND source_id = %s",
                (catch_source_id,)
            )
            if cur.fetchone():
                return

            cur.execute("""
                INSERT INTO catches (
                    source, source_id, species_id, catch_date,
                    location, latitude, longitude, weight_lbs, quantity,
                    fishing_method, metadata
                ) VALUES (
                    'gfw', %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, 1,
                    %s, %s::jsonb
                )
            """, (
                catch_source_id, species_id, catch_date,
                lon, lat, lat, lon, weight, method,
                json.dumps({"gfw_effort_id": effort_source_id, "gear_type": gear, "simulated": True}),
            ))
            self.conn.commit()

    def _upsert_simulated_vessel(self, vessel, lat, lon):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO vessels (mmsi, vessel_name, flag_country, gear_type, source,
                                    last_position, last_seen)
                VALUES (%s, %s, %s, %s, 'gfw',
                        ST_SetSRID(ST_MakePoint(%s, %s), 4326), NOW())
                ON CONFLICT (mmsi) DO UPDATE SET
                    last_position = EXCLUDED.last_position,
                    last_seen = NOW(),
                    updated_at = NOW()
            """, (vessel['mmsi'], vessel['name'], vessel['flag'], vessel['gear'], lon, lat))
            self.conn.commit()


def main():
    """Run GFW harvester"""
    import sys

    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    harvester = GFWHarvester()
    stats = harvester.run(sync_type='incremental', days_back=days_back)
    print(f"GFW sync completed: {stats}")


if __name__ == "__main__":
    main()
