# clawbot-sql-connector

A lightweight Python library for SQL Server connectivity in OpenClaw / Oblio agent systems. Handles connection pooling, retry logic, and environment-based credential management.

> ⚠️ **Work in Progress** — API may change. Use in production at your own discretion.

## Features

- Environment-based credentials (never hardcoded)
- Automatic retry with backoff on transient failures
- `sqlcmd` subprocess wrapper for raw SQL execution
- Compatible with `pyodbc` and `mssql-tools`
- Designed for use with `clawbot-sql-memory`

## Installation

```bash
pip install pyodbc python-dotenv
# Also requires mssql-tools (sqlcmd)
curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add -
apt-get install mssql-tools
```

## Quick Start

```python
from sql_connector import SQLConnector

conn = SQLConnector()  # reads from .env
result = conn.execute("SELECT TOP 5 * FROM memory.Memories")
print(result)
```

## .env Setup

```env
SQL_SERVER=your-server.database.windows.net
SQL_PORT=1433
SQL_DATABASE=your_database
SQL_USER=your_admin_user
SQL_PASSWORD=your_password

# Cloud instance (optional)
SQL_CLOUD_SERVER=SQL5112.site4now.net
SQL_CLOUD_DATABASE=db_99ba1f_memory4oblio
SQL_CLOUD_USER=db_99ba1f_memory4oblio_admin
SQL_CLOUD_PASSWORD=your_cloud_password
```

## API

### `SQLConnector(profile='local')`
Initialize with `'local'` or `'cloud'` profile.

### `.execute(query: str, timeout: int = 30) -> str`
Run a SQL query. Returns raw `sqlcmd` output as a string.

### `.ping() -> bool`
Check connectivity. Returns `True` if the server is reachable.

### `.remember(category, key, content, importance=3, tags='') -> int`
Store a memory entry in `memory.Memories`. Returns the new row id.

### `.recall(category, key) -> str | None`
Retrieve the most recent active memory entry by category and key.

## Error Handling

All methods retry up to 3 times with exponential backoff on connection errors. SQL errors are logged to `infrastructure/logs/sql_dbo.log`.

## Integration with clawbot-sql-memory

This connector is the low-level transport layer. For higher-level semantic memory operations, use [clawbot-sql-memory](https://github.com/VeXHarbinger/clawbot-sql-memory).

## License

MIT
