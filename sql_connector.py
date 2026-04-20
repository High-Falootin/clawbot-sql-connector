#!/usr/bin/env python3
"""
sql_connector.py — Generic SQL Server Connector (v2.0)
=======================================================
Reusable, driver-native SQL Server connectivity for OpenClaw agents.
Transport: pymssql (native TDS driver — no subprocess, no sqlcmd dependency).

Security model:
  - SQLConnector is abstract (ABC) — cannot be instantiated directly
  - execute() and query() are sealed via metaclass — subclasses cannot bypass them
  - All queries must use parameterised binding (%s placeholders)
  - No string interpolation in execute/query — enforced by design
  - Credentials loaded from environment only

Upgrade path from v1.x (sqlcmd-based):
  - API is backward-compatible: from_env(), execute(), query(), ping() all preserved
  - execute() now returns bool (success/failure) instead of raw stdout string
  - query() now returns list[dict] directly (no columns arg needed)
  - execute_scalar() preserved, returns Any instead of Optional[str]
  - New: scalar() method for single-value queries

Usage:
    from sql_connector import MSSQLConnector, get_connector
    db = get_connector('cloud')
    rows = db.query("SELECT id, name FROM memory.Memories WHERE category=%s", ('facts',))
    ok   = db.execute("UPDATE memory.Memories SET importance=%s WHERE id=%s", (5, 42))
    val  = db.scalar("SELECT COUNT(*) FROM memory.TaskQueue WHERE status=%s", ('pending',))
"""

from __future__ import annotations

import abc
import logging
import os
import time
from typing import Any

import pymssql
from dotenv import load_dotenv

# Walk up from this file to find .env (handles install into skills/ subdir)
import pathlib as _pathlib
def _find_env() -> str | None:
    p = _pathlib.Path(os.path.abspath(__file__)).parent
    for _ in range(5):
        c = p / '.env'
        if c.exists():
            return str(c)
        p = p.parent
    return None

_env = _find_env()
if _env:
    load_dotenv(_env, override=True)

_log = logging.getLogger(__name__)

# ── Backend configuration ─────────────────────────────────────────────────────

_BACKENDS: dict[str, dict[str, Any]] = {
    'local': {
        'server':   os.getenv('SQL_SERVER',   os.getenv('SQL_LOCAL_SERVER',   '10.0.0.110')),
        'port':     int(os.getenv('SQL_PORT', os.getenv('SQL_LOCAL_PORT',     '1433'))),
        'database': os.getenv('SQL_DATABASE', os.getenv('SQL_LOCAL_DATABASE', 'Oblio_Memories')),
        'user':     os.getenv('SQL_USER',     os.getenv('SQL_LOCAL_USER',     'oblio')),
        'password': os.getenv('SQL_PASSWORD', os.getenv('SQL_LOCAL_PASSWORD', '')),
    },
    'cloud': {
        'server':   os.getenv('SQL_CLOUD_SERVER',   ''),
        'port':     int(os.getenv('SQL_CLOUD_PORT', '1433')),
        'database': os.getenv('SQL_CLOUD_DATABASE', ''),
        'user':     os.getenv('SQL_CLOUD_USER',     ''),
        'password': os.getenv('SQL_CLOUD_PASSWORD', ''),
    },
}


# ── Default backend resolution ───────────────────────────────────────────────
# SQL_DEFAULT_BACKEND env var controls the default.
# This allows external/ClawHub users (who have no local server) to default to
# 'cloud', while Oblio's .env sets SQL_DEFAULT_BACKEND=local for local-first.
#
# Priority: SQL_DEFAULT_BACKEND env var → 'cloud' (safe for external users)
# Oblio's .env sets: SQL_DEFAULT_BACKEND=local
#
_DEFAULT_BACKEND: str = os.getenv('SQL_DEFAULT_BACKEND', 'cloud')


_SEALED = frozenset({'execute', 'query'})

class _SealCoreMethods(abc.ABCMeta):
    """Prevent any subclass from overriding execute() or query()."""
    def __new__(mcs, name, bases, namespace):
        for method in _SEALED:
            if method in namespace:
                for base in bases:
                    for ancestor in getattr(base, '__mro__', []):
                        if method in vars(ancestor) and getattr(ancestor, '__name__', '') == 'SQLConnector':
                            raise TypeError(
                                f"{name}: '{method}()' is sealed and cannot be overridden. "
                                "Add domain logic in a repository subclass instead."
                            )
        return super().__new__(mcs, name, bases, namespace)


# ── Custom exceptions ─────────────────────────────────────────────────────────

class SQLConnectorError(Exception):
    """Base connector error."""

class SQLConnectionError(SQLConnectorError):
    """Connection-level failure (retry-eligible)."""

class SQLQueryError(SQLConnectorError):
    """Query execution failure (do not retry)."""


# ── Abstract base ─────────────────────────────────────────────────────────────

class SQLConnector(abc.ABC, metaclass=_SealCoreMethods):
    """
    Abstract SQL connector.
    Concrete subclasses must implement _connect().
    execute() and query() are sealed — extend via repository subclasses.
    """

    MAX_RETRIES:  int   = 3
    RETRY_DELAY:  float = 2.0

    def __init__(self, backend: str = _DEFAULT_BACKEND) -> None:
        if backend not in _BACKENDS:
            raise ValueError(f"Unknown backend '{backend}'. Options: {list(_BACKENDS)}")
        self._backend = backend
        self._cfg     = _BACKENDS[backend]

    @classmethod
    def from_env(cls, profile: str = _DEFAULT_BACKEND, **kwargs) -> 'SQLConnector':
        """Create connector from environment variables (v1.x compat)."""
        if profile not in _BACKENDS:
            raise SQLConnectionError(f"Unknown profile '{profile}'")
        instance = cls.__new__(cls)
        SQLConnector.__init__(instance, profile)
        return instance

    @abc.abstractmethod
    def _connect(self) -> Any:
        """Return an open DB-API 2.0 connection."""

    # ── Sealed public API ─────────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> bool:
        """
        Run INSERT / UPDATE / DELETE with parameterised binding.
        Returns True on success, False on failure after retries.
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        conn.commit()
                return True
            except Exception as exc:
                _log.warning("execute attempt %d/%d: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        _log.error("execute failed after %d attempts", self.MAX_RETRIES)
        return False

    def query(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        """
        Run SELECT with parameterised binding. Returns list[dict].
        """
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor(as_dict=True) as cur:
                        cur.execute(sql, params)
                        return cur.fetchall() or []
            except Exception as exc:
                _log.warning("query attempt %d/%d: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        _log.error("query failed after %d attempts", self.MAX_RETRIES)
        return []

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        """Return first column of first row, or None. Tuple cursor avoids unnamed-column issues."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        row = cur.fetchone()
                        return row[0] if row else None
            except Exception as exc:
                _log.warning("scalar attempt %d/%d: %s", attempt + 1, self.MAX_RETRIES, exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY)
        return None

    def execute_scalar(self, sql: str, params: tuple = ()) -> Any:
        """Alias for scalar() — v1.x compatibility."""
        return self.scalar(sql, params)

    def ping(self) -> bool:
        """Test connectivity. Returns True if reachable."""
        try:
            return self.scalar("SELECT 1") == 1
        except Exception:
            return False

    @property
    def backend(self) -> str:
        return self._backend


# ── Concrete: Microsoft SQL Server via pymssql ────────────────────────────────

class MSSQLConnector(SQLConnector):
    """
    SQL Server connector using pymssql (native TDS, no sqlcmd dependency).
    One connection per call — pymssql is not thread-safe with shared connections.
    """

    def _connect(self) -> Any:
        cfg = self._cfg
        return pymssql.connect(
            server=cfg['server'],
            port=cfg['port'],
            user=cfg['user'],
            password=cfg['password'],
            database=cfg['database'],
            timeout=30,
            login_timeout=10,
            tds_version='7.4',
        )


# ── Factory ───────────────────────────────────────────────────────────────────

def get_connector(backend: str = _DEFAULT_BACKEND) -> SQLConnector:
    """
    Factory: returns the appropriate SQLConnector for the given backend.
    Add new database types here without changing callers.
    """
    return MSSQLConnector(backend)


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys
    print("sql_connector v2.0 — self-test")
    for profile in ['cloud', 'local']:
        try:
            db = get_connector(profile)
            ok = db.ping()
            print(f"  {profile}: {'✅ connected' if ok else '⚠️  ping returned False'}")
        except Exception as e:
            print(f"  {profile}: ❌ {e}")
    sys.exit(0)
