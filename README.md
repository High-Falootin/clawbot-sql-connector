# clawbot-sql-connector

> ⚠️ **ALPHA — Use at your own risk.** API is functional and tested but may change. We're actively using this in production and will stabilize the API after 30 days of community feedback. Please open issues for anything that breaks.

A sealed, retry-capable SQL Server connector for OpenClaw agents. Built on **pymssql** — no `sqlcmd` or `mssql-tools` required.

## Features

- `get_connector('cloud')` / `get_connector('local')` factory
- Abstract base (`SQLConnector`) with `_LockCoreMethods` metaclass — `execute()` and `query()` cannot be overridden in subclasses, keeping all queries parameterized
- Automatic retry with exponential backoff on transient failures
- `execute()` — INSERT/UPDATE/DELETE, returns bool
- `query()` — SELECT, returns list of dicts
- `scalar()` — single value (e.g. `INSERTED.id`)
- `ping()` — connectivity check
- Environment-based credentials via `.env` — nothing hardcoded

## Requirements

```bash
pip install pymssql python-dotenv
```

> **Note:** `pymssql` bundles its own TDS driver. No `sqlcmd`, no ODBC drivers, no `mssql-tools` needed.

## Installation

```bash
clawhub install sql-connector
```

## .env Setup

Backend configuration uses a simple naming pattern. Add these to your `.env`:

```env
# Local instance
SQL_local_server=10.0.0.110
SQL_local_port=1433
SQL_local_database=YourDatabase
SQL_local_user=your_user
SQL_local_password=your_password

# Cloud instance (Azure / site4now / etc.)
SQL_cloud_server=yourserver.database.windows.net
SQL_cloud_port=1433
SQL_cloud_database=your_cloud_db
SQL_cloud_user=your_cloud_user
SQL_cloud_password=your_cloud_password

# Add new backends with the same pattern:
# SQL_<backend>_server, SQL_<backend>_database, SQL_<backend>_user, SQL_<backend>_password
SQL_staging_server=staging.database.windows.net
SQL_staging_port=1433
SQL_staging_database=staging_db
SQL_staging_user=staging_user
SQL_staging_password=staging_password
```

Then connect:

```python
db = get_connector('local')      # Uses SQL_local_* vars
db = get_connector('cloud')      # Uses SQL_cloud_* vars
db = get_connector('staging')    # Uses SQL_staging_* vars
```

**To add a new backend:** Just add 4 env vars to `.env` following the pattern. No code changes needed.

## Quick Start

```python
from sql_connector import get_connector

db = get_connector('cloud')   # or 'local'

# INSERT / UPDATE / DELETE
ok = db.execute(
    "INSERT INTO memory.Logs (category, msg) VALUES (%s, %s)",
    ("info", "hello world")
)

# SELECT → list of dicts
rows = db.query(
    "SELECT id, content FROM memory.Memories WHERE category = %s",
    ("facts",)
)

# Single value
count = db.scalar("SELECT COUNT(*) FROM memory.TaskQueue WHERE status = %s", ("pending",))

# Connectivity check
if db.ping():
    print("connected")
```

## Architecture

```
SQLConnector (ABC, _LockCoreMethods metaclass)
  ├── execute() / query() / scalar()   ← SEALED — parameterized only, no overrides
  ├── ping()
  ├── _connect()                        ← abstract
  └── MSSQLConnector (pymssql)          ← concrete implementation
```

Extend by subclassing `MSSQLConnector` to add domain-specific repository methods. See [clawbot-sql-memory](https://github.com/VeXHarbinger/clawbot-sql-memory) for an example.

## Security Note

All queries are parameterized. The metaclass seals `execute()` and `query()` so subclasses cannot bypass parameterization. Never pass user input via f-strings or string concatenation into SQL — the connector will not prevent it at the call site if you build your query string before passing it in.

## Related

- [clawbot-sql-memory](https://github.com/VeXHarbinger/clawbot-sql-memory) — Semantic memory layer built on this connector
- [oblio-heart-and-soul](https://github.com/VeXHarbinger/oblio-heart-and-soul) — Full agent system reference implementation

## Community

Found a bug? Have an improvement? Open an issue — this is alpha and community feedback shapes the v1 API.

## License

MIT
