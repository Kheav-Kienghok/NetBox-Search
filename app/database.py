import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_index (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type         TEXT NOT NULL,      -- 'vm_interface' | 'ip_address'

    -- from IPAM > IP Addresses
    ip_address          TEXT,
    dns_name            TEXT,

    -- from Virtualization > Virtual Machines
    vm_id               INTEGER,
    vm_name             TEXT,
    vm_status           TEXT,
    vm_vcpus            TEXT,
    vm_memory_gib       TEXT,
    vm_disk_gib         TEXT,
    vm_tags             TEXT,
    vm_wazuh_installed  TEXT,
    vm_comments         TEXT,

    -- interface this IP is assigned to (if any)
    interface_id        INTEGER,
    interface_name       TEXT,
    interface_enabled    INTEGER,
    mac_address          TEXT,

    description         TEXT,
    netbox_url          TEXT,
    search_text         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_search_index_type ON search_index(record_type);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def get_db_path() -> Path:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def replace_search_index(rows: list[dict]) -> None:
    """Atomically replace the whole search_index table with fresh rows."""
    with get_connection() as conn:
        conn.execute("DELETE FROM search_index")
        conn.executemany(
            """
            INSERT INTO search_index (
                record_type, ip_address, dns_name,
                vm_id, vm_name, vm_status, vm_vcpus, vm_memory_gib, vm_disk_gib,
                vm_tags, vm_wazuh_installed, vm_comments,
                interface_id, interface_name, interface_enabled, mac_address,
                description, netbox_url, search_text
            ) VALUES (
                :record_type, :ip_address, :dns_name,
                :vm_id, :vm_name, :vm_status, :vm_vcpus, :vm_memory_gib, :vm_disk_gib,
                :vm_tags, :vm_wazuh_installed, :vm_comments,
                :interface_id, :interface_name, :interface_enabled, :mac_address,
                :description, :netbox_url, :search_text
            )
            """,
            rows,
        )


def load_search_index() -> list[dict]:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM search_index")
        return [dict(row) for row in cur.fetchall()]


def set_meta(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_meta(key: str) -> str | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT value FROM sync_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else None
