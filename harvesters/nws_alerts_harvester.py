"""
NWS Marine Alerts Harvester
Pulls active marine weather alerts from the National Weather Service API
https://api.weather.gov/
"""

import httpx
from datetime import datetime, timezone
from typing import Dict
from harvesters.base import BaseHarvester


# South Shore Long Island marine forecast zones
MARINE_ZONES = [
    'ANZ345',  # South Shore Bays (Jones Inlet through Shinnecock Bay)
    'ANZ350',  # Moriches Inlet to Montauk Point out 20nm
    'ANZ353',  # Fire Island Inlet to Moriches Inlet out 20nm
    'ANZ355',  # Sandy Hook to Fire Island Inlet out 20nm
]


class NWSAlertsHarvester(BaseHarvester):
    """Harvester for NWS active marine alerts"""

    NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

    def __init__(self):
        super().__init__('nws_marine_alerts')

    def sync(self, **kwargs) -> Dict:
        """Fetch active marine alerts from NWS"""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        zones_param = ','.join(MARINE_ZONES)

        try:
            self.logger.info(f"Fetching NWS alerts for zones: {zones_param}")
            response = httpx.get(
                self.NWS_ALERTS_URL,
                params={'zone': zones_param},
                timeout=30.0,
                headers={
                    'User-Agent': 'MarineFishing/1.0 (contact@example.com)',
                    'Accept': 'application/geo+json',
                }
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            self.logger.error(f"HTTP error fetching NWS alerts: {e}")
            return stats
        except Exception as e:
            self.logger.error(f"Error fetching NWS alerts: {e}")
            return stats

        features = data.get('features', [])
        self.logger.info(f"Got {len(features)} alert features from NWS")

        # First, expire old alerts
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE marine_alerts
                SET is_active = false
                WHERE is_active = true AND expires < NOW()
            """)
            expired_count = cur.rowcount
            if expired_count > 0:
                self.logger.info(f"Expired {expired_count} old alerts")
            self.conn.commit()

        # Process each alert
        with self.conn.cursor() as cur:
            for feature in features:
                try:
                    props = feature.get('properties', {})
                    alert_id = props.get('id', '')
                    if not alert_id:
                        stats['skipped'] += 1
                        continue

                    stats['processed'] += 1

                    event = props.get('event', '')
                    severity = (props.get('severity', '') or '').lower()
                    headline = props.get('headline', '')
                    description = props.get('description', '')
                    instruction = props.get('instruction', '')
                    status = props.get('status', 'actual')
                    area_desc = props.get('areaDesc', '')

                    # Parse onset/expires
                    onset = _parse_iso(props.get('onset') or props.get('effective'))
                    expires = _parse_iso(props.get('expires') or props.get('ends'))

                    # Extract zone IDs from the alert
                    affected_zones = props.get('geocode', {}).get('UGC', [])
                    # Filter to our marine zones
                    relevant_zones = [z for z in affected_zones if z in MARINE_ZONES]
                    if not relevant_zones:
                        # Fallback: use area description to determine zone
                        relevant_zones = MARINE_ZONES[:1]

                    for zone_id in relevant_zones:
                        zone_alert_id = alert_id + '::' + zone_id
                        cur.execute("""
                            INSERT INTO marine_alerts
                                (alert_id, zone_id, zone_name, event, severity, headline,
                                 description, instruction, onset, expires, status, is_active)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                            ON CONFLICT (alert_id) DO UPDATE SET
                                event = EXCLUDED.event,
                                severity = EXCLUDED.severity,
                                headline = EXCLUDED.headline,
                                description = EXCLUDED.description,
                                instruction = EXCLUDED.instruction,
                                onset = EXCLUDED.onset,
                                expires = EXCLUDED.expires,
                                status = EXCLUDED.status,
                                is_active = CASE
                                    WHEN EXCLUDED.expires IS NOT NULL AND EXCLUDED.expires < NOW()
                                    THEN false ELSE true
                                END
                        """, (
                            zone_alert_id, zone_id,
                            area_desc[:200] if area_desc else None,
                            event[:100] if event else None,
                            severity,
                            headline[:500] if headline else None,
                            description, instruction, onset, expires, status,
                        ))
                        stats['inserted'] += 1

                except Exception as e:
                    self.logger.warning(f"Skipping alert: {e}")
                    self.conn.rollback()
                    stats['skipped'] += 1

            self.conn.commit()

        self.logger.info(f"Processed {stats['processed']} alerts, inserted/updated {stats['inserted']}")
        return stats


def _parse_iso(dt_str):
    """Parse ISO datetime string, returning None on failure"""
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def main():
    """Run NWS alerts harvester"""
    harvester = NWSAlertsHarvester()
    stats = harvester.run(sync_type='incremental')
    print(f"NWS alerts sync completed: {stats}")


if __name__ == "__main__":
    main()
