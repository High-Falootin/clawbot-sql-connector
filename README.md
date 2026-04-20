# clawbot-sql-connector

> **STABLE** — Battle-tested in production. API is stable as of v2.0.

A sealed, retry-capable SQL Server connector for OpenClaw agents. Built on **pymssql** — no `sqlcmd`, no ODBC drivers, no system tools required.

## Features

- **Multi-backend:** `local` (on-prem) and `cloud` (hosted) in one connector
- **Env-var driven default:** set `SQL_DEFAULT_BACKEND` in `.env` — no code change needed
- **Sealed transport:** `execute()` and `query()` sealed via metaclass — subclasses cannot bypass parameterized queries
- **Retry with backoff:** automatic retry (3x, 2s delay) on transient connection failures
- **Operations:** `execute()` (INSERT/UPDATE/DELETE), `query()` (SELECT → list of dicts), `scalar()` (single value), `ping()` (health check)
- **Nothing hardcoded:** all credentials from `.env` only

## Quick Start

### Installation

```bash
# Via ClawHub
clawhub install sql-connector

# Or pip
pip install clawbot-sql-connector
```

### Dependencies

```bash
pip install pymssql python-dotenv
```

> `pymssql` bundles its own TDS driver. No `sqlcmd`, no ODBC, no system packages.

### Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**External / ClawHub users** (cloud SQL Server):
```env
SQL_CLOUD_SERVER=your-server.database.windows.net
SQL_CLOUD_DATABASE=your_database
SQL_CLOUD_USER=your_user
SQL_CLOUD_PASSWORD=your_password
SQL_DEFAULT_BACKEND=cloud      # optional, cloud is default for external users
```

**Local SQL Server** (self-hosted, Oblio setup):
```env
SQL_LOCAL_SERVER=10.0.0.110
SQL_LOCAL_DATABASE=Oblio_Memories
SQL_LOCAL_USER=oblio
SQL_LOCAL_PASSWORD=your_password
SQL_DEFAULT_BACKEND=local      # override default to local
```

### Use

```python
from sql_connector import get_connector

db = get_connector()           # uses SQL_DEFAULT_BACKEND from .env
# db = get_connector('cloud')  # explicit
# db = get_connector('local')  # explicit

# SELECT → list of dicts
rows = db.query(
    "SELECT id, content FROM memory.Memories WHERE category = %s",
    ('facts',)
)
for row in rows:
    print(row['content'])

# INSERT / UPDATE / DELETE → bool
ok = db.execute(
    "UPDATE memory.Memories SET importance = %s WHERE id = %s",
    (8, 42)
)

# Single value
count = db.scalar(
    "SELECT COUNT(*) FROM memory.TaskQueue WHERE status = %s",
    ('pending',)
)

# Health check
if db.ping():
    print("Connected")
```

## Parameterized Queries — Mandatory

**Always use `%s` placeholders. Never f-strings or string interpolation.**

```python
# ❌ WRONG — SQL injection risk
db.query(f"SELECT * FROM Memories WHERE category = '{category}'")

# ✅ CORRECT
db.query("SELECT * FROM Memories WHERE category = %s", (category,))
```

The sealed metaclass prevents `execute()` and `query()` from being overridden in subclasses, so this is enforced by design.

## Extending

Create a repository subclass for domain logic — don't subclass the transport:

```python
from sql_connector import MSSQLConnector

class MemoryRepository(MSSQLConnector):
    def get_recent_facts(self, limit: int = 10):
        return self.query(
            "SELECT TOP %s * FROM memory.Memories "
            "WHERE category = %s ORDER BY created_at DESC",
            (limit, 'facts')
        )

repo = MemoryRepository('local')
facts = repo.get_recent_facts(5)
```

## Error Handling

```python
from sql_connector import get_connector, SQLConnectionError, SQLQueryError

db = get_connector()

try:
    rows = db.query("SELECT * FROM memory.Memories WHERE id = %s", (99999,))
except SQLConnectionError as e:
    print(f"Connection failed (retry-eligible): {e}")
except SQLQueryError as e:
    print(f"Query failed (do not retry): {e}")
```

## Default Backend Logic

| `SQL_DEFAULT_BACKEND` env var | `get_connector()` connects to |
|-------------------------------|-------------------------------|
| Not set (external/ClawHub)    | `cloud` |
| `cloud`                       | `cloud` |
| `local`                       | `local` (Oblio's .env sets this) |

This means:
- ClawHub users get `cloud` by default (they have no local server)
- Oblio's `.env` sets `SQL_DEFAULT_BACKEND=local` for local-first operation
- No code change needed — just `.env` configuration

## ClawHub

This skill is published to [clawhub.ai](https://clawhub.ai) as `sql-connector`.

**Version policy:** Stable releases only. We run this in production and publish when stable for 30+ days.

---

## API Reference

### `get_connector(backend: str = _DEFAULT_BACKEND) → SQLConnector`

Factory. Returns `MSSQLConnector` for the given backend.

### `SQLConnector.query(sql, params=()) → list[dict]`

Execute SELECT. Returns rows as list of dicts.

### `SQLConnector.execute(sql, params=()) → bool`

Execute INSERT/UPDATE/DELETE. Returns True on success.

### `SQLConnector.scalar(sql, params=()) → Any`

Execute query returning a single value.

### `SQLConnector.ping() → bool`

Connectivity check. Returns True if connected.

### `SQLConnector.from_env(profile=_DEFAULT_BACKEND) → SQLConnector`

v1.x compatibility factory.

---

## License

MIT — see LICENSE.
