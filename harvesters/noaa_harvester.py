"""
NOAA Fisheries Data Harvester
Pulls commercial and recreational landings data from NOAA FOSS API
https://apps-st.fisheries.noaa.gov/ods/foss/landings/
"""

import httpx
import hashlib
import json
import math
import random
from datetime import datetime, date
from typing import Dict, List, Optional
from harvesters.base import BaseHarvester


# NOAA FOSS species names -> our species codes
NOAA_SPECIES_MAP = {
    'TUNA, ALBACORE': 'ALB',
    'TUNA, BIGEYE': 'BET',
    'TUNA, BLUEFIN': 'BFT',
    'TUNA, YELLOWFIN': 'YFT',
    'TUNA, SKIPJACK': 'SKJ',
    'SWORDFISH': 'SWO',
    'DOLPHINFISH': 'DOL',
    'WAHOO': 'WAH',
    'SAILFISH': 'SAI',
    'MARLIN, BLUE': 'BUM',
    'MARLIN, WHITE': 'WHM',
}

# Target regions for the Atlantic coast
TARGET_REGIONS = ['Middle Atlantic', 'New England', 'South Atlantic']

# Offshore fishing areas by state (lat, lon center + spread radius in degrees)
# These represent typical pelagic fishing grounds off each state
STATE_FISHING_AREAS = {
    'NEW YORK':       {'lat': 40.3, 'lon': -72.2, 'spread': 0.6},
    'NEW JERSEY':     {'lat': 39.5, 'lon': -73.0, 'spread': 0.6},
    'MARYLAND':       {'lat': 38.2, 'lon': -74.2, 'spread': 0.5},
    'VIRGINIA':       {'lat': 37.0, 'lon': -74.8, 'spread': 0.6},
    'NORTH CAROLINA': {'lat': 35.5, 'lon': -74.8, 'spread': 0.7},
    'SOUTH CAROLINA': {'lat': 33.0, 'lon': -78.5, 'spread': 0.6},
    'FLORIDA-EAST':   {'lat': 27.5, 'lon': -79.5, 'spread': 0.8},
    'MASSACHUSETTS':  {'lat': 41.5, 'lon': -69.5, 'spread': 0.6},
    'RHODE ISLAND':   {'lat': 41.0, 'lon': -70.8, 'spread': 0.4},
    'CONNECTICUT':    {'lat': 41.0, 'lon': -72.0, 'spread': 0.3},
    'MAINE':          {'lat': 43.5, 'lon': -68.5, 'spread': 0.6},
    'NEW HAMPSHIRE':  {'lat': 42.9, 'lon': -70.0, 'spread': 0.3},
}

# Typical individual fish weight ranges (lbs) by species code
TYPICAL_WEIGHTS = {
    'BFT': (150, 700),
    'YFT': (30, 180),
    'BET': (40, 200),
    'ALB': (20, 80),
    'SKJ': (8, 25),
    'SWO': (100, 400),
    'DOL': (10, 50),
    'WAH': (20, 80),
    'SAI': (40, 100),
    'BUM': (200, 600),
    'WHM': (50, 150),
}

# Monthly fishing season weights (1-12). Higher = more activity that month.
SEASONAL_WEIGHTS = {
    'BFT': [1, 1, 2, 3, 5, 10, 12, 12, 10, 6, 3, 1],
    'YFT': [1, 1, 2, 3, 6, 10, 12, 12, 10, 5, 2, 1],
    'BET': [1, 1, 2, 4, 6, 8, 10, 12, 10, 6, 3, 1],
    'ALB': [1, 1, 1, 2, 4, 7, 10, 12, 12, 8, 3, 1],
    'SKJ': [1, 1, 1, 2, 5, 8, 12, 12, 10, 5, 2, 1],
    'SWO': [2, 2, 3, 4, 6, 8, 10, 12, 12, 8, 4, 2],
    'DOL': [1, 1, 2, 4, 8, 12, 12, 10, 8, 5, 2, 1],
    'WAH': [1, 1, 2, 3, 6, 10, 12, 12, 10, 6, 2, 1],
    'SAI': [1, 1, 2, 4, 8, 12, 12, 10, 8, 4, 2, 1],
    'BUM': [1, 1, 1, 2, 5, 10, 12, 12, 10, 5, 2, 1],
    'WHM': [1, 1, 1, 3, 6, 10, 12, 12, 10, 5, 2, 1],
}

# Gear types used for each collection type
COMMERCIAL_GEARS = ['longline', 'troll', 'handline', 'gillnet', 'purse_seine']
RECREATIONAL_GEARS = ['rod_reel', 'troll', 'handline']


class NOAAHarvester(BaseHarvester):
    """Harvester for NOAA FOSS commercial fisheries landings data"""

    FOSS_API_URL = "https://apps-st.fisheries.noaa.gov/ods/foss/landings/"

    def __init__(self):
        super().__init__('noaa_commercial')

    def sync(self, years: List[int] = None, **kwargs) -> Dict:
        """
        Sync commercial landings data from NOAA FOSS.

        Fetches annual aggregated landings and disaggregates into individual
        catch records distributed across months and offshore fishing areas.
        """
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if years is None:
            current_year = datetime.now().year
            # NOAA data typically lags 1-2 years; fetch last 5
            years = list(range(current_year - 5, current_year))

        species_map = self.get_species_map()

        for year in years:
            self.logger.info(f"Fetching NOAA FOSS landings for {year}")

            for noaa_name, species_code in NOAA_SPECIES_MAP.items():
                if species_code not in species_map:
                    continue

                try:
                    records = self._fetch_landings(year, noaa_name, 'Commercial')
                    if not records:
                        continue

                    for record in records:
                        total_lbs = record.get('pounds')
                        if not total_lbs or total_lbs <= 0:
                            stats['skipped'] += 1
                            continue

                        state = record.get('state_name', '')
                        if state not in STATE_FISHING_AREAS:
                            stats['skipped'] += 1
                            continue

                        stats['processed'] += 1

                        catch_stats = self._disaggregate_and_insert(
                            year=year,
                            species_code=species_code,
                            species_id=species_map[species_code],
                            species_raw=noaa_name,
                            state=state,
                            total_lbs=float(total_lbs),
                            collection='Commercial',
                            noaa_record=record,
                        )
                        stats['inserted'] += catch_stats['inserted']
                        stats['skipped'] += catch_stats['skipped']

                except Exception as e:
                    self.logger.error(f"Error fetching {noaa_name} for {year}: {e}")

        return stats

    def _fetch_landings(self, year: int, species_name: str, collection: str) -> List[Dict]:
        """Fetch landings from NOAA FOSS API for a given year and species."""
        query = {
            "year": year,
            "ts_afs_name": species_name,
            "collection": collection,
        }
        params = {
            "q": json.dumps(query),
            "limit": 100,
        }

        try:
            response = httpx.get(self.FOSS_API_URL, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            items = data.get('items', [])

            # Filter to target regions
            items = [r for r in items if r.get('region_name') in TARGET_REGIONS]

            if items:
                self.logger.info(
                    f"  {species_name} {year} {collection}: "
                    f"{len(items)} state records"
                )
            return items

        except httpx.HTTPError as e:
            self.logger.warning(f"HTTP error fetching {species_name} {year}: {e}")
            return []

    def _disaggregate_and_insert(
        self,
        year: int,
        species_code: str,
        species_id: int,
        species_raw: str,
        state: str,
        total_lbs: float,
        collection: str,
        noaa_record: Dict,
    ) -> Dict:
        """
        Disaggregate an annual state-level total into individual catch records
        distributed across months and locations based on seasonal patterns.
        """
        stats = {'inserted': 0, 'skipped': 0}

        # Determine individual catch weight range
        wt_lo, wt_hi = TYPICAL_WEIGHTS.get(species_code, (20, 100))
        avg_weight = (wt_lo + wt_hi) / 2

        # Estimate number of individual catches
        est_catches = max(1, int(total_lbs / avg_weight))
        # Cap to keep things reasonable for map display
        est_catches = min(est_catches, 200)

        # Recalculate per-catch weight to distribute the total evenly
        per_catch_lbs = total_lbs / est_catches

        # Get seasonal distribution for this species
        season = SEASONAL_WEIGHTS.get(species_code, [1] * 12)
        season_total = sum(season)

        # Get fishing area for this state
        area = STATE_FISHING_AREAS[state]

        # Use a deterministic seed so re-runs produce the same records
        seed_str = f"noaa_{year}_{species_code}_{state}_{collection}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        gears = COMMERCIAL_GEARS if collection == 'Commercial' else RECREATIONAL_GEARS

        # Original NOAA record stored as metadata
        metadata = json.dumps({
            "noaa_total_lbs": total_lbs,
            "noaa_state": state,
            "noaa_region": noaa_record.get('region_name'),
            "noaa_collection": collection,
            "noaa_source": noaa_record.get('source'),
            "noaa_tsn": noaa_record.get('tsn'),
            "disaggregated": True,
        })

        # Distribute catches across months
        catch_idx = 0
        for month_idx in range(12):
            month = month_idx + 1
            month_fraction = season[month_idx] / season_total
            month_catches = max(0, round(est_catches * month_fraction))

            for _ in range(month_catches):
                catch_idx += 1

                # Deterministic source_id for dedup
                source_id = f"noaa_{year}_{species_code}_{state}_{collection}_{catch_idx}"

                # Random day, location, weight within bounds
                day = rng.randint(1, 28)
                lat = round(area['lat'] + rng.uniform(-area['spread'], area['spread']), 4)
                lon = round(area['lon'] + rng.uniform(-area['spread'], area['spread']), 4)
                weight = round(per_catch_lbs * rng.uniform(0.6, 1.4), 1)
                gear = rng.choice(gears)

                try:
                    catch_date = date(year, month, day)
                except ValueError:
                    catch_date = date(year, month, 28)

                inserted = self._insert_catch(
                    source_id=source_id,
                    species_id=species_id,
                    species_raw=species_raw,
                    catch_date=catch_date,
                    lat=lat,
                    lon=lon,
                    weight=weight,
                    gear=gear,
                    metadata=metadata,
                )
                if inserted:
                    stats['inserted'] += 1
                else:
                    stats['skipped'] += 1

        return stats

    def _insert_catch(
        self, source_id: str, species_id: int, species_raw: str,
        catch_date: date, lat: float, lon: float, weight: float,
        gear: str, metadata: str,
    ) -> bool:
        """Insert a single catch record. Returns True if inserted, False if duplicate."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM catches WHERE source = 'noaa_commercial' AND source_id = %s",
                (source_id,)
            )
            if cur.fetchone():
                return False

            cur.execute("""
                INSERT INTO catches (
                    source, source_id, species_id, species_raw, catch_date,
                    location, latitude, longitude, weight_lbs, quantity,
                    fishing_method, metadata
                ) VALUES (
                    'noaa_commercial', %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, 1,
                    %s, %s::jsonb
                )
            """, (
                source_id, species_id, species_raw, catch_date,
                lon, lat, lat, lon, weight,
                gear, metadata,
            ))
            self.conn.commit()
            return True


class MRIPHarvester(BaseHarvester):
    """Harvester for NOAA FOSS recreational fishing data (MRIP source)"""

    FOSS_API_URL = "https://apps-st.fisheries.noaa.gov/ods/foss/landings/"

    def __init__(self):
        super().__init__('noaa_mrip')

    def sync(self, years: List[int] = None, **kwargs) -> Dict:
        """
        Sync recreational landings from NOAA FOSS (MRIP collection).
        Same API, filtered to Recreational collection.
        """
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        if years is None:
            current_year = datetime.now().year
            years = list(range(current_year - 3, current_year))

        species_map = self.get_species_map()

        for year in years:
            self.logger.info(f"Fetching NOAA MRIP recreational data for {year}")

            for noaa_name, species_code in NOAA_SPECIES_MAP.items():
                if species_code not in species_map:
                    continue

                try:
                    records = self._fetch_recreational(year, noaa_name)
                    if not records:
                        continue

                    for record in records:
                        # MRIP uses tot_count (estimated fish count) and/or pounds
                        total_lbs = record.get('pounds')
                        tot_count = record.get('tot_count')

                        if (not total_lbs or total_lbs <= 0) and (not tot_count or tot_count <= 0):
                            stats['skipped'] += 1
                            continue

                        state = record.get('state_name', '')
                        if state not in STATE_FISHING_AREAS:
                            stats['skipped'] += 1
                            continue

                        stats['processed'] += 1

                        catch_stats = self._disaggregate_and_insert(
                            year=year,
                            species_code=species_code,
                            species_id=species_map[species_code],
                            species_raw=noaa_name,
                            state=state,
                            total_lbs=float(total_lbs) if total_lbs else None,
                            tot_count=int(tot_count) if tot_count else None,
                            noaa_record=record,
                        )
                        stats['inserted'] += catch_stats['inserted']
                        stats['skipped'] += catch_stats['skipped']

                except Exception as e:
                    self.logger.error(f"Error fetching MRIP {noaa_name} for {year}: {e}")

        return stats

    def _fetch_recreational(self, year: int, species_name: str) -> List[Dict]:
        """Fetch recreational landings from NOAA FOSS."""
        query = {
            "year": year,
            "ts_afs_name": species_name,
            "collection": "Recreational",
        }
        params = {
            "q": json.dumps(query),
            "limit": 100,
        }

        try:
            response = httpx.get(self.FOSS_API_URL, params=params, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            items = data.get('items', [])
            items = [r for r in items if r.get('region_name') in TARGET_REGIONS]

            if items:
                self.logger.info(
                    f"  {species_name} {year} Recreational: {len(items)} state records"
                )
            return items

        except httpx.HTTPError as e:
            self.logger.warning(f"HTTP error fetching MRIP {species_name} {year}: {e}")
            return []

    def _disaggregate_and_insert(
        self,
        year: int,
        species_code: str,
        species_id: int,
        species_raw: str,
        state: str,
        total_lbs: Optional[float],
        tot_count: Optional[int],
        noaa_record: Dict,
    ) -> Dict:
        """Disaggregate MRIP annual totals into individual recreational catch records."""
        stats = {'inserted': 0, 'skipped': 0}

        wt_lo, wt_hi = TYPICAL_WEIGHTS.get(species_code, (20, 100))
        avg_weight = (wt_lo + wt_hi) / 2

        # Use tot_count if available, otherwise estimate from pounds
        if tot_count and tot_count > 0:
            est_catches = tot_count
        elif total_lbs:
            est_catches = max(1, int(total_lbs / avg_weight))
        else:
            return stats

        # Cap for map display; recreational can have huge counts
        est_catches = min(est_catches, 150)

        # Per-catch weight
        if total_lbs and total_lbs > 0:
            per_catch_lbs = total_lbs / est_catches
        else:
            per_catch_lbs = avg_weight

        season = SEASONAL_WEIGHTS.get(species_code, [1] * 12)
        season_total = sum(season)

        area = STATE_FISHING_AREAS[state]
        # Recreational fishing tends to be closer to shore
        spread = area['spread'] * 0.7

        seed_str = f"mrip_{year}_{species_code}_{state}"
        seed = int(hashlib.md5(seed_str.encode()).hexdigest()[:8], 16)
        rng = random.Random(seed)

        metadata = json.dumps({
            "noaa_total_lbs": total_lbs,
            "noaa_tot_count": tot_count,
            "noaa_state": state,
            "noaa_region": noaa_record.get('region_name'),
            "noaa_collection": "Recreational",
            "noaa_source": noaa_record.get('source'),
            "noaa_tsn": noaa_record.get('tsn'),
            "disaggregated": True,
        })

        catch_idx = 0
        for month_idx in range(12):
            month = month_idx + 1
            month_fraction = season[month_idx] / season_total
            month_catches = max(0, round(est_catches * month_fraction))

            for _ in range(month_catches):
                catch_idx += 1
                source_id = f"mrip_{year}_{species_code}_{state}_{catch_idx}"

                day = rng.randint(1, 28)
                lat = round(area['lat'] + rng.uniform(-spread, spread), 4)
                lon = round(area['lon'] + rng.uniform(-spread, spread), 4)
                weight = round(per_catch_lbs * rng.uniform(0.5, 1.5), 1)
                gear = rng.choice(RECREATIONAL_GEARS)

                try:
                    catch_date = date(year, month, day)
                except ValueError:
                    catch_date = date(year, month, 28)

                inserted = self._insert_catch(
                    source_id=source_id,
                    species_id=species_id,
                    species_raw=species_raw,
                    catch_date=catch_date,
                    lat=lat,
                    lon=lon,
                    weight=weight,
                    gear=gear,
                    metadata=metadata,
                )
                if inserted:
                    stats['inserted'] += 1
                else:
                    stats['skipped'] += 1

        return stats

    def _insert_catch(
        self, source_id: str, species_id: int, species_raw: str,
        catch_date: date, lat: float, lon: float, weight: float,
        gear: str, metadata: str,
    ) -> bool:
        """Insert a single catch record."""
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM catches WHERE source = 'noaa_mrip' AND source_id = %s",
                (source_id,)
            )
            if cur.fetchone():
                return False

            cur.execute("""
                INSERT INTO catches (
                    source, source_id, species_id, species_raw, catch_date,
                    location, latitude, longitude, weight_lbs, quantity,
                    fishing_method, metadata
                ) VALUES (
                    'noaa_mrip', %s, %s, %s, %s,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, 1,
                    %s, %s::jsonb
                )
            """, (
                source_id, species_id, species_raw, catch_date,
                lon, lat, lat, lon, weight,
                gear, metadata,
            ))
            self.conn.commit()
            return True


def main():
    """Run NOAA harvester"""
    import sys

    harvester_type = sys.argv[1] if len(sys.argv) > 1 else 'commercial'

    if harvester_type == 'mrip':
        harvester = MRIPHarvester()
    else:
        harvester = NOAAHarvester()

    stats = harvester.run(sync_type='incremental')
    print(f"NOAA sync completed: {stats}")


if __name__ == "__main__":
    main()
