# SQL Connector Skill
> Generic SQL Server connectivity for OpenClaw agents

## Overview
Provides a reusable, battle-tested SQL Server connection layer with automatic retry, connection pooling, parameterized queries, and structured error handling. Built for MSSQL (via `sqlcmd`) with plans for ODBC/pyodbc support.

## Installation
```bash
clawhub install sql-connector
```

## Usage

### Quick Start
```python
from sql_connector import SQLConnector

# From environment variables
conn = SQLConnector.from_env('cloud')  # reads SQL_CLOUD_SERVER, etc.

# Direct
conn = SQLConnector(server='myserver.com', database='mydb', user='sa', password='secret')

# Execute queries
result = conn.execute("SELECT COUNT(*) FROM users")
scalar = conn.execute_scalar("SELECT MAX(id) FROM orders")
rows = conn.query("SELECT id, name FROM products WHERE active=1")
```

### Features
- **Auto-retry** with exponential backoff (configurable)
- **Connection validation** via `ping()`
- **Parameterized queries** to prevent SQL injection
- **Structured result parsing** — rows returned as list of dicts
- **Logging** — all queries logged at DEBUG level
- **Error classification** — distinguishes connection vs. query errors

### Configuration
Environment variables follow the pattern `SQL_{PROFILE}_*`:
```
SQL_CLOUD_SERVER=sql5112.site4now.net
SQL_CLOUD_DATABASE=db_99ba1f_memory4oblio
SQL_CLOUD_USER=myuser
SQL_CLOUD_PASSWORD=mypassword
```

### API Reference

| Method | Description |
|--------|-------------|
| `execute(sql)` | Execute SQL, return raw output |
| `execute_scalar(sql)` | Execute SQL, return single value |
| `query(sql, columns)` | Execute SELECT, return list of dicts |
| `ping()` | Test connection, return bool |
| `from_env(profile)` | Create from env vars |

## Requirements
- `sqlcmd` (mssql-tools) installed and in PATH
- Python 3.8+
- `.env` file with SQL credentials

## License
MIT
