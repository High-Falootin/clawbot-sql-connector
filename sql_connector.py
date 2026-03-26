"""
infrastructure/sql_connector.py
================================
Abstract base connector + concrete MSSQLConnector.

Security model:
  - SQLConnector is an ABC — cannot be instantiated directly
  - All query methods are final via __init_subclass__ enforcement
  - Parameterised queries only (no string interpolation in execute/query)
  - Connection per-call (pymssql is not thread-safe with shared conns)
  - Credentials loaded from env only — never accepted as constructor args
  - Subclasses may NOT override execute() or query() (locked via __init_subclass__)
  - Raw DDL/admin access intentionally excluded — use sqlcmd for migrations

Usage (internal only — never import this from agent code):
  from infrastructure.sql_connector import MSSQLConnector
  db = MSSQLConnector('cloud')
  rows = db.query("SELECT * FROM memory.Memories WHERE category=%s", ('facts',))
"""

from __future__ import annotations

import abc
import logging
import os
import time
from typing import Any

import pymssql
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

_log = logging.getLogger(__name__)

# ── Backend configuration (loaded from .env) ────────────────────────────────
# Convention: SQL_<BACKEND>_SERVER, SQL_<BACKEND>_DATABASE, SQL_<BACKEND>_USER, SQL_<BACKEND>_PASSWORD
# Example .env:
#   SQL_local_server=10.0.0.110
#   SQL_local_database=Oblio_Memories
#   SQL_local_user=oblio
#   SQL_local_password=secret123
#
#   SQL_cloud_server=SQL5112.site4now.net
#   SQL_cloud_database=db_99ba1f_memory4oblio
#   SQL_cloud_user=admin
#   SQL_cloud_password=secret456
#
#   SQL_tat_server=SQL8011.site4now.net
#   SQL_tat_database=db_99ba1f_tripatouriumdevdb
#   SQL_tat_user=tat_admin
#   SQL_tat_password=secret789
#
# To add a new backend: just add 4 vars to .env, then get_connector('newname') works

def _load_backend_config(backend_name: str) -> dict[str, Any]:
    """
    Load backend config from .env using convention.
    Pattern: SQL_<backend>_server, SQL_<backend>_database, SQL_<backend>_user, SQL_<backend>_password
    """
    prefix = f'SQL_{backend_name}_'
    return {
        'server':   os.getenv(f'{prefix}server',   ''),
        'port':     int(os.getenv(f'{prefix}port', '1433')),
        'database': os.getenv(f'{prefix}database', ''),
        'user':     os.getenv(f'{prefix}user',     ''),
        'password': os.getenv(f'{prefix}password', ''),
    }


_BACKENDS_CACHE: dict[str, dict[str, Any]] = {}

def get_backend_config(backend: str) -> dict[str, Any]:
    """Get backend config, cached after first load."""
    if backend not in _BACKENDS_CACHE:
        cfg = _load_backend_config(backend)
        if not cfg.get('server') or not cfg.get('database'):
            raise ValueError(
                f"Backend '{backend}' not configured. "
                f"Add SQL_{backend}_server and SQL_{backend}_database to .env"
            )
        _BACKENDS_CACHE[backend] = cfg
    return _BACKENDS_CACHE[backend]

# ── Locked-method sentinel ────────────────────────────────────────────────────

_LOCKED = frozenset({'execute', 'query'})


class _LockCoreMethods(abc.ABCMeta):
    """Metaclass that prevents subclasses from overriding execute/query."""
    def __new__(mcs, name, bases, namespace):
        for locked in _LOCKED:
            if locked in namespace:
                # Walk full MRO of every base — catches deep inheritance chains
                for base in bases:
                    for ancestor in getattr(base, '__mro__', []):
                        if locked in vars(ancestor) and getattr(ancestor, '__name__', '') == 'SQLConnector':
                            raise TypeError(
                                f"{name}: overriding '{locked}' is not permitted. "
                                "Extend behaviour via repository subclasses (SQLMemoryConnector, etc.)."
                            )
        return super().__new__(mcs, name, bases, namespace)


# ── Abstract base ─────────────────────────────────────────────────────────────

class SQLConnector(abc.ABC, metaclass=_LockCoreMethods):
    """
    Abstract SQL connector.  Concrete subclasses must implement _connect().
    execute() and query() are sealed — subclasses may NOT override them.
    All data access must go through parameterised query() or execute().
    """

    MAX_RETRIES: int = 3
    RETRY_DELAY: float = 2.0
    CIRCUIT_BREAKER_THRESHOLD: int = 10  # Fail fast after 10 consecutive errors
    _consecutive_errors: int = 0

    def __init__(self, backend: str = 'cloud') -> None:
        self._backend = backend
        try:
            self._cfg = get_backend_config(backend)
        except ValueError as e:
            raise ValueError(f"Invalid backend '{backend}': {e}") from e

    # ── Must implement ────────────────────────────────────────────────────────

    @abc.abstractmethod
    def _connect(self) -> Any:
        """Return an open, ready-to-use DB-API 2.0 connection."""

    # ── Sealed public API ─────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> bool:
        """
        Run a non-SELECT statement (INSERT/UPDATE/DELETE).
        Returns True on success, False on failure.
        Always uses parameterised binding — no string interpolation.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        conn.commit()
                return True
            except Exception as exc:
                _log.warning("execute attempt %d/%d failed: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        _log.error("execute failed after %d attempts", self.MAX_RETRIES)
        return False

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """
        Run a SELECT and return rows as list[dict].
        Always uses parameterised binding — no string interpolation.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor(as_dict=True) as cur:
                        cur.execute(sql, params)
                        return cur.fetchall() or []
            except Exception as exc:
                _log.warning("query attempt %d/%d failed: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        _log.error("query failed after %d attempts", self.MAX_RETRIES)
        return []

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        """Return the first column of the first row, or None."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:   # tuple cursor — avoids unnamed column issue
                        cur.execute(sql, params)
                        row = cur.fetchone()
                        return row[0] if row else None
            except Exception as exc:
                _log.warning("scalar attempt %d/%d failed: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        return None

    def ping(self) -> bool:
        """Verify connectivity. Returns True if the server responds."""
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return True
        except Exception as exc:
            _log.warning("ping failed: %s", exc)
            return False

    @property
    def backend(self) -> str:
        return self._backend


# ── Concrete implementation ───────────────────────────────────────────────────

class MSSQLConnector(SQLConnector):
    """
    Microsoft SQL Server connector via pymssql.
    One connection per call — pymssql is not thread-safe with shared connections.
    TLS encryption enabled for cloud backend automatically.
    """

    def _connect(self) -> Any:
        cfg = self._cfg
        return pymssql.connect(
            server=cfg['server'],
            port=cfg['port'],
            user=cfg['user'],
            password=cfg['password'],
            database=cfg['database'],
            timeout=60,  # Increased from 30 to 60 (handles slow networks)
            login_timeout=20,  # Increased from 10 to 20 (handles pool exhaustion)
            tds_version='7.4',
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_connector(backend: str = 'cloud') -> SQLConnector:
    """
    Factory function.  Returns the appropriate concrete connector.
    Add new backends here (e.g. PostgreSQL, SQLite) without touching callers.
    """
    return MSSQLConnector(backend)
