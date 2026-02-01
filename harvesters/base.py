"""
Base Harvester Class
Common functionality for all data harvesters
"""

import io
import logging
from datetime import datetime
from typing import Dict, Optional
from abc import ABC, abstractmethod
import psycopg2
from psycopg2.extras import execute_values
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/opt/marine-fishing/api/.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class LogCaptureHandler(logging.Handler):
    """Captures log messages into a StringIO buffer for database storage."""

    def __init__(self):
        super().__init__()
        self.buffer = io.StringIO()
        self.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.write(msg + '\n')
        except Exception:
            self.handleError(record)

    def get_logs(self) -> str:
        return self.buffer.getvalue()

    def clear(self):
        self.buffer = io.StringIO()


class BaseHarvester(ABC):
    """Base class for all data harvesters"""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.logger = logging.getLogger(f"harvester.{source_name}")
        self.db_url = os.getenv('DATABASE_URL', 'postgresql://marine_user:marine_fishing_2026@localhost:5432/marine_fishing')
        self.conn = None
        self.sync_log_id = None

    def connect_db(self):
        """Establish database connection"""
        if self.conn is None or self.conn.closed:
            # Parse DATABASE_URL
            # Format: postgresql://user:pass@host:port/dbname
            url = self.db_url.replace('postgresql://', '')
            user_pass, host_db = url.split('@')
            user, password = user_pass.split(':')
            host_port, dbname = host_db.split('/')
            if ':' in host_port:
                host, port = host_port.split(':')
            else:
                host = host_port
                port = 5432

            self.conn = psycopg2.connect(
                host=host,
                port=port,
                database=dbname,
                user=user,
                password=password
            )
            self.logger.info("Database connection established")

    def close_db(self):
        """Close database connection"""
        if self.conn and not self.conn.closed:
            self.conn.close()
            self.logger.info("Database connection closed")

    def start_sync_log(self, sync_type: str, date_range_start: Optional[datetime] = None,
                       date_range_end: Optional[datetime] = None) -> int:
        """Create a sync log entry and return its ID"""
        self.connect_db()
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO data_sync_log (source, sync_type, date_range_start, date_range_end, status)
                VALUES (%s, %s, %s, %s, 'running')
                RETURNING id
            """, (self.source_name, sync_type, date_range_start, date_range_end))
            self.sync_log_id = cur.fetchone()[0]
            self.conn.commit()
        self.logger.info(f"Started sync log #{self.sync_log_id}")
        return self.sync_log_id

    def complete_sync_log(self, stats: Dict, status: str = 'completed',
                          error_message: str = None, log_messages: str = None):
        """Update sync log with completion status and captured log messages"""
        if not self.sync_log_id:
            return

        self.connect_db()
        with self.conn.cursor() as cur:
            cur.execute("""
                UPDATE data_sync_log
                SET completed_at = NOW(),
                    records_processed = %s,
                    records_inserted = %s,
                    records_updated = %s,
                    records_skipped = %s,
                    status = %s,
                    error_message = %s,
                    log_messages = %s
                WHERE id = %s
            """, (
                stats.get('processed', 0),
                stats.get('inserted', 0),
                stats.get('updated', 0),
                stats.get('skipped', 0),
                status,
                error_message,
                log_messages,
                self.sync_log_id
            ))
            self.conn.commit()
        self.logger.info(f"Completed sync log #{self.sync_log_id}: {status}")

    def get_species_id(self, species_code: str) -> Optional[int]:
        """Get species ID by code"""
        self.connect_db()
        with self.conn.cursor() as cur:
            cur.execute("SELECT id FROM species WHERE species_code = %s", (species_code.upper(),))
            result = cur.fetchone()
            return result[0] if result else None

    def get_species_map(self) -> Dict[str, int]:
        """Get mapping of species codes to IDs"""
        self.connect_db()
        with self.conn.cursor() as cur:
            cur.execute("SELECT species_code, id FROM species WHERE species_code IS NOT NULL")
            return {row[0]: row[1] for row in cur.fetchall()}

    @abstractmethod
    def sync(self, **kwargs) -> Dict:
        """Run the sync process - must be implemented by subclasses"""
        pass

    def run(self, **kwargs) -> Dict:
        """Main entry point for running the harvester"""
        stats = {'processed': 0, 'inserted': 0, 'updated': 0, 'skipped': 0}

        # Attach log capture handler for this sync run
        capture_handler = LogCaptureHandler()
        self.logger.addHandler(capture_handler)

        try:
            self.logger.info(f"Starting {self.source_name} harvester")
            self.connect_db()
            self.start_sync_log(kwargs.get('sync_type', 'incremental'))
            stats = self.sync(**kwargs)
            self.logger.info(f"Sync completed: {stats}")
            self.complete_sync_log(stats, 'completed',
                                   log_messages=capture_handler.get_logs())
        except Exception as e:
            self.logger.error(f"Sync failed: {e}")
            self.complete_sync_log(stats, 'failed', str(e),
                                   log_messages=capture_handler.get_logs())
            raise
        finally:
            self.logger.removeHandler(capture_handler)
            self.close_db()

        return stats
