# ClawBot SQL Connector

Generic SQL Server connector for OpenClaw AI agents. Handles connection management, retry logic, structured result parsing, and common CRUD operations.

## Features
- **Retry with backoff** — connection errors auto-retry (3x default)
- **Structured results** — `query()` returns list of dicts, `execute_scalar()` for single values
- **Environment-based config** — reads `SQL_{PROFILE}_*` env vars
- **Safe escaping** — `_esc()` prevents SQL injection in string interpolation
- **Health checks** — `ping()` and `table_exists()` for monitoring

## Quick Start
```python
from sql_connector import SQLConnector

conn = SQLConnector.from_env('cloud')

# Simple query
rows = conn.query("SELECT id, name FROM users", ['id', 'name'])

# Scalar
count = conn.execute_scalar("SELECT COUNT(*) FROM memory.TaskQueue")

# Insert
conn.insert('memory.Memories', {'category': 'fact', 'key_name': 'sky', 'content': 'blue'})

# Health check
if conn.ping():
    print("Database is up")
```

## Configuration
```env
SQL_CLOUD_SERVER=your-server.database.windows.net
SQL_CLOUD_DATABASE=your_database
SQL_CLOUD_USER=your_user
SQL_CLOUD_PASSWORD=your_password
```

## Architecture
```
Your Agent → SQLConnector → sqlcmd CLI → SQL Server
                ↳ retry logic
                ↳ result parsing
                ↳ error classification
```

Built for the [Oblio](https://github.com/VeXHarbinger/oblio-heart-and-soul) agent ecosystem.

## License
MIT
