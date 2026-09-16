# NetBox Search

A small FastAPI + HTMX app that pulls IPAM (IP addresses) and Virtualization
(VMs, VM interfaces) data out of NetBox every few hours, joins them into one
combined record (VM ↔ interface ↔ IP address), and gives you a fuzzy search
box over the result.

## How it fits together

```
NetBox API  --(httpx, paginated)-->  sync.run_sync()
                                          |
                                          v
                              combined rows (VM+interface+IPs)
                                          |
                              +-----------+------------+
                              v                        v
                         SQLite (data/netbox_search.db)   in-memory cache
                         persists across restarts         (rapidfuzz, hot path)

APScheduler runs run_sync() every SYNC_INTERVAL_HOURS (default 4),
plus once at startup. FastAPI serves an HTMX page that hits /search
on every keystroke (debounced) and /sync for a manual refresh.
```

Search ranking: exact/substring matches on the combined text (IP, VM name,
interface name, MAC, description, tags) are shown first, then any remaining
slots are filled with rapidfuzz fuzzy matches - so typing part of an IP
octet doesn't get outranked by an unrelated but "fuzzily closer" address,
while a typo in a VM name still finds something.

## Project layout

```
app/
  config.py       # Settings (env vars / .env)
  netbox_client.py# Thin NetBox REST client with auto-pagination
  sync.py         # Fetch + join VMs/interfaces/IPs -> combined rows
  database.py     # SQLite storage for the combined index + sync metadata
  search.py       # In-memory fuzzy search cache (rapidfuzz)
  scheduler.py    # APScheduler: periodic sync every N hours
  main.py         # FastAPI app, routes, lifespan (startup sync + scheduler)
  templates/      # Jinja2 + HTMX templates
  static/         # CSS
```

## Setup

```bash
cd netbox-search
cp .env.example .env
# edit .env: set NETBOX_URL and NETBOX_TOKEN (a read-only API token is enough)

uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open http://localhost:8000 . On startup the app will try an initial
sync; if NetBox isn't reachable yet it logs a warning and keeps running -
fix your `.env` and click "Sync now", or wait for the next scheduled run.

## NetBox token permissions

A read-only API token is sufficient. It needs GET access to:
- `virtualization.virtual_machine`
- `virtualization.vminterface`
- `ipam.ipaddress`

## Configuration (`.env`)

| Variable               | Default                     | Meaning                                   |
|-------------------------|-----------------------------|--------------------------------------------|
| `NETBOX_URL`            | -                            | Base URL of your NetBox instance           |
| `NETBOX_TOKEN`          | -                            | API token                                  |
| `NETBOX_VERIFY_SSL`     | `true`                       | Set `false` for self-signed certs (lab use)|
| `SYNC_INTERVAL_HOURS`   | `4`                          | How often the background sync runs         |
| `SYNC_ON_STARTUP`       | `true`                       | Run a sync as soon as the app boots         |
| `DB_PATH`               | `data/netbox_search.db`      | SQLite file for the combined index         |
| `HOST` / `PORT`         | `0.0.0.0` / `8000`           | Uvicorn bind address                        |

## Extending

- **Add device (non-VM) interfaces too**: mirror `sync.py`'s VM-interface
  loop using `/api/dcim/interfaces/` and `/api/dcim/devices/`, and add a
  `record_type == "device_interface"` branch.
- **Bigger inventories**: if the in-memory rapidfuzz scan gets slow (tens of
  thousands of rows), pre-filter with a SQLite `LIKE`/FTS5 query before
  ranking the candidates with rapidfuzz.
- **Prefixes**: NetBox's `/api/ipam/prefixes/` isn't pulled in yet; it would
  slot into `sync.py` the same way IP addresses do.
