#!/usr/bin/env python3
"""
sql_connector.py — Generic SQL Server Connector
================================================
Provides reusable SQL Server connectivity with retry, logging, and structured
result parsing. No memory/agent semantics — just reliable SQL execution.

Usage:
    from sql_connector import SQLConnector
    conn = SQLConnector.from_env('cloud')
    rows = conn.query("SELECT id, name FROM users", ['id', 'name'])
"""

import os
import subprocess
import logging
import time
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sql_connector")


def _esc(val, max_len: int = 4000) -> str:
    """Escape a value for safe SQL string interpolation."""
    if val is None:
        return ""
    s = str(val).replace("'", "''")
    return s[:max_len]


class SQLConnectorError(Exception):
    """Base exception for SQL connector errors."""
    pass


class SQLConnectionError(SQLConnectorError):
    """Connection-level failure."""
    pass


class SQLQueryError(SQLConnectorError):
    """Query execution failure."""
    pass


class SQLConnector:
    """
    Generic SQL Server connector using sqlcmd.
    
    Handles connection, execution, retry, and result parsing.
    No application-specific logic — just reliable SQL.
    """

    SQLCMD = "/opt/mssql-tools/bin/sqlcmd"

    def __init__(self, server: str, database: str, user: str, password: str,
                 max_retries: int = 3, retry_delay: float = 2.0, timeout: int = 30):
        self.server = server
        self.database = database
        self.user = user
        self.password = password
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        
        logger.info(f"SQLConnector initialized (server={server}, db={database})")

    @classmethod
    def from_env(cls, profile: str = 'cloud', **kwargs) -> 'SQLConnector':
        """
        Create a connector from environment variables.
        
        Reads SQL_{PROFILE}_SERVER, SQL_{PROFILE}_USER, etc.
        """
        prefix = f"SQL_{profile.upper()}"
        server = os.getenv(f"{prefix}_SERVER")
        database = os.getenv(f"{prefix}_DATABASE")
        user = os.getenv(f"{prefix}_USER")
        password = os.getenv(f"{prefix}_PASSWORD")

        if not all([server, database, user, password]):
            raise SQLConnectionError(
                f"Missing env vars for profile '{profile}'. "
                f"Need: {prefix}_SERVER, {prefix}_DATABASE, {prefix}_USER, {prefix}_PASSWORD"
            )

        return cls(server=server, database=database, user=user, password=password, **kwargs)

    def _build_cmd(self, sql: str) -> list:
        """Build the sqlcmd command list."""
        return [
            self.SQLCMD,
            "-S", self.server,
            "-d", self.database,
            "-U", self.user,
            "-P", self.password,
            "-Q", sql,
            "-W",  # Remove trailing spaces
        ]

    def execute(self, sql: str) -> str:
        """
        Execute a SQL statement with retry logic.
        Returns raw stdout output.
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"Execute (attempt {attempt}): {sql[:100]}...")
                result = subprocess.run(
                    self._build_cmd(sql),
                    capture_output=True, text=True,
                    timeout=self.timeout
                )

                if result.returncode != 0:
                    error_msg = result.stderr.strip() or result.stdout.strip()
                    # Connection errors → retry
                    if any(kw in error_msg.lower() for kw in ['login timeout', 'network', 'connection']):
                        last_error = SQLConnectionError(error_msg)
                        logger.warning(f"Connection error (attempt {attempt}): {error_msg[:100]}")
                        time.sleep(self.retry_delay * attempt)
                        continue
                    # Query errors → don't retry
                    raise SQLQueryError(error_msg)

                return result.stdout
            except subprocess.TimeoutExpired:
                last_error = SQLConnectionError(f"Query timed out after {self.timeout}s")
                logger.warning(f"Timeout (attempt {attempt})")
                time.sleep(self.retry_delay * attempt)
            except SQLQueryError:
                raise
            except Exception as e:
                last_error = SQLConnectorError(str(e))
                logger.warning(f"Unexpected error (attempt {attempt}): {e}")
                time.sleep(self.retry_delay * attempt)

        raise last_error or SQLConnectorError("All retry attempts exhausted")

    def execute_scalar(self, sql: str) -> Optional[str]:
        """Execute SQL and return a single scalar value."""
        out = self.execute(sql)
        lines = [l.strip() for l in out.strip().splitlines() if l.strip() and not l.startswith('-')]
        # Skip header row
        if len(lines) >= 2:
            val = lines[1].strip()
            if val and not val.startswith('('):
                return val
        return None

    def query(self, sql: str, columns: List[str]) -> List[Dict[str, Any]]:
        """
        Execute a SELECT and return results as a list of dicts.
        
        Args:
            sql: SELECT statement
            columns: Expected column names in order
        
        Returns:
            List of dicts, one per row
        """
        out = self.execute(sql)
        return self._parse_table(out, columns)

    def _parse_table(self, output: str, columns: List[str]) -> List[Dict[str, Any]]:
        """Parse sqlcmd tabular output into list of dicts."""
        if not output:
            return []

        lines = output.strip().splitlines()
        rows = []
        data_started = False

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('(') and stripped.endswith('affected)'):
                continue
            if set(stripped) <= {'-', ' '}:
                data_started = True
                continue
            if not data_started:
                continue

            parts = stripped.split()
            if len(parts) >= len(columns):
                row = {}
                for i, col in enumerate(columns):
                    if i == len(columns) - 1:
                        row[col] = ' '.join(parts[i:]).strip()
                    else:
                        row[col] = parts[i].strip()
                rows.append(row)

        return rows

    def ping(self) -> bool:
        """Test database connectivity."""
        try:
            result = self.execute("SELECT 1")
            return '1' in result
        except Exception:
            return False

    def table_exists(self, schema: str, table: str) -> bool:
        """Check if a table exists."""
        result = self.execute_scalar(
            f"SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA='{_esc(schema)}' AND TABLE_NAME='{_esc(table)}'"
        )
        return result is not None and int(result) > 0

    def insert(self, table: str, data: Dict[str, Any]) -> str:
        """
        Insert a row into a table.
        
        Args:
            table: Full table name (e.g., 'memory.Memories')
            data: Dict of column→value pairs
        """
        cols = ', '.join(data.keys())
        vals = ', '.join(f"'{_esc(v)}'" if v is not None else 'NULL' for v in data.values())
        return self.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals})")

    def update(self, table: str, data: Dict[str, Any], where: str) -> str:
        """
        Update rows in a table.
        
        Args:
            table: Full table name
            data: Dict of column→value pairs to update
            where: WHERE clause (without the WHERE keyword)
        """
        sets = ', '.join(f"{k}='{_esc(v)}'" for k, v in data.items())
        return self.execute(f"UPDATE {table} SET {sets} WHERE {where}")
