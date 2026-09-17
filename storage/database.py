"""Criacao e acesso a conexoes SQLite."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY COLLATE NOCASE,
    state TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    cycle_id TEXT PRIMARY KEY,
    product_id TEXT,
    state TEXT,
    macroregion TEXT,
    destination TEXT,
    status TEXT NOT NULL,
    qr_code TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS cycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (cycle_id) REFERENCES cycles(cycle_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cycles_started_at
    ON cycles(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cycle_events_cycle_id
    ON cycle_events(cycle_id, id);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
