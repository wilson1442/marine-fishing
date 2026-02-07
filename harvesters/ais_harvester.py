"""
AIS Stream Harvester
Connects to aisstream.io WebSocket for real-time AIS data from fishing vessels.
Filters for ship type 30 (fishing), stores positions, detects fishing/loitering.

API docs: https://aisstream.io/documentation
"""

import json
import os
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import websocket

from harvesters.base import BaseHarvester


# Default bounding box: US East Coast + offshore [[lat1, lon1], [lat2, lon2]]
# Covers Florida Keys (24N) to Nova Scotia (46N), Gulf Stream to Grand Banks (55W)
DEFAULT_BBOX = [[24.0, -82.0], [46.0, -55.0]]


class AISStreamHarvester(BaseHarvester):
    """Harvester for aisstream.io real-time AIS data focused on fishing vessels."""

    WS_URL = "wss://stream.aisstream.io/v0/stream"

    def __init__(self):
        super().__init__('aisstream')
        self.api_key = os.getenv('AISSTREAM_API_KEY', '')
        self._running = False
        self._stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}
        # Track vessel state for fishing/loitering detection
        self._vessel_state = {}  # mmsi -> {positions: [...], last_speed: ..., slow_since: ...}

    def sync(self, **kwargs) -> Dict:
        """Run the persistent WebSocket connection."""
        if not self.api_key:
            self.logger.error("No AISSTREAM_API_KEY configured")
            return self._stats

        bbox = kwargs.get('bbox', DEFAULT_BBOX)
        duration = kwargs.get('duration', 0)  # 0 = run forever

        self._running = True
        self._stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        # Handle graceful shutdown
        def signal_handler(signum, frame):
            self.logger.info("Received shutdown signal, stopping...")
            self._running = False

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

        start_time = time.time()
        reconnect_delay = 5
        self._last_sync_log_update = 0

        # Clean up stale 'running' entries from previous crashed runs
        self._cleanup_stale_sync_logs()

        while self._running:
            try:
                stats_before = self._stats['processed']
                self._connect_and_stream(bbox, duration, start_time)
                if not self._running:
                    break
                # Reset delay if we received data during this connection
                if self._stats['processed'] > stats_before:
                    reconnect_delay = 5
                # If we get here without _running being False, we disconnected unexpectedly
                self.logger.warning(f"WebSocket disconnected, reconnecting in {reconnect_delay}s...")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)
            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                if not self._running:
                    break
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

            # Check duration limit
            if duration > 0 and (time.time() - start_time) >= duration:
                self._running = False

        return self._stats

    def _cleanup_stale_sync_logs(self):
        """Mark any previous 'running' entries for this source as failed."""
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE data_sync_log
                    SET status = 'failed', completed_at = NOW(),
                        error_message = 'Process terminated without graceful shutdown'
                    WHERE source = %s AND status = 'running' AND id != %s
                """, (self.source_name, self.sync_log_id or 0))
                updated = cur.rowcount
            self.conn.commit()
            if updated:
                self.logger.info(f"Cleaned up {updated} stale 'running' sync log entries")

            # Set initial heartbeat on current sync log
            if self.sync_log_id:
                with self.conn.cursor() as cur:
                    cur.execute("""
                        UPDATE data_sync_log
                        SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('last_heartbeat', NOW())
                        WHERE id = %s
                    """, (self.sync_log_id,))
                self.conn.commit()
        except Exception as e:
            self.logger.error(f"Error cleaning up stale sync logs: {e}")

    def _update_sync_log_progress(self):
        """Periodically update the sync log with current stats and heartbeat."""
        now = time.time()
        if now - self._last_sync_log_update < 300:  # Every 5 minutes
            return
        self._last_sync_log_update = now
        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE data_sync_log
                    SET records_processed = %s,
                        records_inserted = %s,
                        records_updated = %s,
                        records_skipped = %s,
                        metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('last_heartbeat', NOW())
                    WHERE id = %s
                """, (
                    self._stats.get('processed', 0),
                    self._stats.get('inserted', 0),
                    self._stats.get('updated', 0),
                    self._stats.get('skipped', 0),
                    self.sync_log_id,
                ))
            self.conn.commit()
        except Exception as e:
            self.logger.error(f"Error updating sync log progress: {e}")

    def _connect_and_stream(self, bbox, duration, start_time):
        """Connect to WebSocket and process messages."""
        subscription = {
            "APIKey": self.api_key,
            "BoundingBoxes": [[bbox[0], bbox[1]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }

        self.logger.info(f"Connecting to {self.WS_URL}...")
        ws = websocket.create_connection(self.WS_URL, timeout=30)

        try:
            ws.send(json.dumps(subscription))
            self.logger.info("Subscription sent, receiving AIS messages...")

            ws.settimeout(60)  # Timeout to check if we should stop

            while self._running:
                try:
                    raw = ws.recv()
                    if not raw:
                        continue

                    msg = json.loads(raw)
                    self._process_message(msg)

                    # Periodic sync log update every 1000 messages
                    if self._stats['processed'] % 1000 == 0 and self._stats['processed'] > 0:
                        self.logger.info(f"Progress: {self._stats}")
                        self._update_sync_log_progress()

                    # Check duration
                    if duration > 0 and (time.time() - start_time) >= duration:
                        self._running = False

                except websocket.WebSocketTimeoutException:
                    continue
                except websocket.WebSocketConnectionClosedException:
                    self.logger.warning("WebSocket connection closed by server")
                    break
        finally:
            ws.close()

    def _process_message(self, msg: Dict):
        """Route an AIS message to the appropriate handler."""
        msg_type = msg.get("MessageType")
        ais_msg = msg.get("Message", {})
        metadata = msg.get("MetaData", {})

        if msg_type == "PositionReport":
            position = ais_msg.get("PositionReport", {})
            self._handle_position_report(position, metadata)
        elif msg_type == "ShipStaticData":
            static_data = ais_msg.get("ShipStaticData", {})
            self._handle_static_data(static_data, metadata)

    def _handle_position_report(self, position: Dict, metadata: Dict):
        """Handle AIS position report (message types 1/2/3/18/19)."""
        self._stats['processed'] += 1

        mmsi = str(metadata.get("MMSI", ""))
        if not mmsi:
            self._stats['skipped'] += 1
            return

        # Only process fishing vessels (ship type 30) or unknown types
        ship_type = metadata.get("ShipType", 0)
        if ship_type != 0 and ship_type != 30:
            self._stats['skipped'] += 1
            return

        lat = position.get("Latitude")
        lon = position.get("Longitude")
        if lat is None or lon is None or (lat == 0 and lon == 0):
            self._stats['skipped'] += 1
            return

        speed = position.get("Sog")  # Speed over ground in knots
        course = position.get("Cog")  # Course over ground
        heading = position.get("TrueHeading")
        nav_status = position.get("NavigationalStatus")

        # Fix heading 511 = not available
        if heading == 511:
            heading = None

        try:
            self.connect_db()

            # Ensure vessel exists
            self._ensure_vessel(mmsi, metadata)

            # Insert position
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vessel_positions (mmsi, location, speed_knots, course, heading, nav_status)
                    VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s)
                """, (mmsi, lon, lat, speed, course, heading, nav_status))

                # Update vessel last position
                cur.execute("""
                    UPDATE vessels
                    SET last_position = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                        last_seen = NOW(),
                        updated_at = NOW()
                    WHERE mmsi = %s
                """, (lon, lat, mmsi))

            self.conn.commit()
            self._stats['inserted'] += 1

            # Behavior detection
            self._detect_behavior(mmsi, lat, lon, speed, course)

        except Exception as e:
            self.logger.error(f"Error inserting position for MMSI {mmsi}: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            self._stats['skipped'] += 1

    def _handle_static_data(self, static_data: Dict, metadata: Dict):
        """Handle AIS static/voyage data (message type 5/24)."""
        self._stats['processed'] += 1

        mmsi = str(metadata.get("MMSI", ""))
        if not mmsi:
            self._stats['skipped'] += 1
            return

        ship_type = static_data.get("Type", metadata.get("ShipType", 0))
        if ship_type != 0 and ship_type != 30:
            self._stats['skipped'] += 1
            return

        name = metadata.get("ShipName", "").strip()
        imo = static_data.get("ImoNumber")
        callsign = static_data.get("CallSign", "").strip()
        dimension = static_data.get("Dimension", {})

        length = None
        if dimension:
            a = dimension.get("A", 0)
            b = dimension.get("B", 0)
            if a + b > 0:
                length = a + b

        try:
            self.connect_db()
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO vessels (mmsi, imo, vessel_name, vessel_type, length_meters, gear_type, source)
                    VALUES (%s, %s, %s, %s, %s, %s, 'aisstream')
                    ON CONFLICT (mmsi) DO UPDATE SET
                        imo = COALESCE(EXCLUDED.imo, vessels.imo),
                        vessel_name = COALESCE(NULLIF(EXCLUDED.vessel_name, ''), vessels.vessel_name),
                        vessel_type = COALESCE(EXCLUDED.vessel_type, vessels.vessel_type),
                        length_meters = COALESCE(EXCLUDED.length_meters, vessels.length_meters),
                        updated_at = NOW()
                """, (
                    mmsi,
                    str(imo) if imo and imo != 0 else None,
                    name if name else None,
                    'fishing',
                    length,
                    callsign if callsign else None,
                ))
            self.conn.commit()
            self._stats['updated'] += 1
        except Exception as e:
            self.logger.error(f"Error upserting vessel {mmsi}: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass
            self._stats['skipped'] += 1

    def _ensure_vessel(self, mmsi: str, metadata: Dict):
        """Ensure a vessel record exists for the MMSI."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM vessels WHERE mmsi = %s", (mmsi,))
            if cur.fetchone():
                return

            name = metadata.get("ShipName", "").strip()
            cur.execute("""
                INSERT INTO vessels (mmsi, vessel_name, vessel_type, source)
                VALUES (%s, %s, 'fishing', 'aisstream')
                ON CONFLICT (mmsi) DO NOTHING
            """, (mmsi, name if name else None))

    def _detect_behavior(self, mmsi: str, lat: float, lon: float,
                         speed: Optional[float], course: Optional[float]):
        """Detect fishing activity and loitering from vessel behavior patterns."""
        now = datetime.now(timezone.utc)

        if mmsi not in self._vessel_state:
            self._vessel_state[mmsi] = {
                'positions': [],
                'fishing_start': None,
                'loitering_start': None,
                'last_courses': [],
            }

        state = self._vessel_state[mmsi]
        state['positions'].append({
            'lat': lat, 'lon': lon, 'speed': speed,
            'course': course, 'time': now
        })

        # Keep only last 60 positions
        if len(state['positions']) > 60:
            state['positions'] = state['positions'][-60:]

        if course is not None:
            state['last_courses'].append(course)
            if len(state['last_courses']) > 10:
                state['last_courses'] = state['last_courses'][-10:]

        if speed is None:
            return

        # Fishing detection: speed 1-5 knots with course changes
        is_fishing_speed = 1.0 <= speed <= 5.0
        has_course_changes = self._has_significant_course_changes(state['last_courses'])

        if is_fishing_speed and has_course_changes:
            if state['fishing_start'] is None:
                state['fishing_start'] = now
            elif (now - state['fishing_start']).total_seconds() > 1800:  # 30 min
                self._record_fishing_event(mmsi, state['fishing_start'], now, lat, lon, speed)
                state['fishing_start'] = now  # Reset for next event
        else:
            if state['fishing_start'] is not None:
                duration = (now - state['fishing_start']).total_seconds()
                if duration > 1800:
                    self._record_fishing_event(mmsi, state['fishing_start'], now, lat, lon, speed)
                state['fishing_start'] = None

        # Loitering detection: speed < 1 knot for > 30 minutes
        is_loitering_speed = speed < 1.0

        if is_loitering_speed:
            if state['loitering_start'] is None:
                state['loitering_start'] = now
            elif (now - state['loitering_start']).total_seconds() > 1800:
                self._record_loitering_event(mmsi, state['loitering_start'], now, lat, lon, speed)
                state['loitering_start'] = now
        else:
            if state['loitering_start'] is not None:
                duration = (now - state['loitering_start']).total_seconds()
                if duration > 1800:
                    self._record_loitering_event(mmsi, state['loitering_start'], now, lat, lon, speed)
                state['loitering_start'] = None

    def _has_significant_course_changes(self, courses: list) -> bool:
        """Check if there are significant course changes (suggesting fishing patterns)."""
        if len(courses) < 3:
            return False

        changes = 0
        for i in range(1, len(courses)):
            diff = abs(courses[i] - courses[i - 1])
            if diff > 180:
                diff = 360 - diff
            if diff > 15:
                changes += 1

        return changes >= 2

    def _record_fishing_event(self, mmsi: str, start: datetime, end: datetime,
                              lat: float, lon: float, avg_speed: float):
        """Insert a detected fishing event."""
        duration_hours = (end - start).total_seconds() / 3600.0
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO detected_fishing_events
                        (mmsi, start_time, end_time, location, avg_speed_knots, duration_hours, detection_method)
                    VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, 'speed_pattern')
                """, (mmsi, start, end, lon, lat, round(avg_speed, 1), round(duration_hours, 2)))
            self.conn.commit()
            self.logger.info(f"Detected fishing: MMSI {mmsi}, {duration_hours:.1f}h")
        except Exception as e:
            self.logger.error(f"Error recording fishing event: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass

    def _record_loitering_event(self, mmsi: str, start: datetime, end: datetime,
                                lat: float, lon: float, avg_speed: float):
        """Insert a detected loitering event."""
        duration_hours = (end - start).total_seconds() / 3600.0
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO detected_loitering_events
                        (mmsi, start_time, end_time, location, avg_speed_knots, duration_hours)
                    VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s)
                """, (mmsi, start, end, lon, lat, round(avg_speed, 1), round(duration_hours, 2)))
            self.conn.commit()
            self.logger.info(f"Detected loitering: MMSI {mmsi}, {duration_hours:.1f}h")
        except Exception as e:
            self.logger.error(f"Error recording loitering event: {e}")
            try:
                self.conn.rollback()
            except Exception:
                pass


def main():
    """Run AIS Stream harvester"""
    import sys

    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 0  # 0 = run forever

    harvester = AISStreamHarvester()
    stats = harvester.run(sync_type='streaming', duration=duration)
    print(f"AIS Stream harvester completed: {stats}")


if __name__ == "__main__":
    main()
