"""Studio database access: connections, migrations, schema readiness, orphan sweep."""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import psycopg2

from studio import core_adapter
from studio.errors import database_unavailable

log = logging.getLogger("studio.db")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_LOCK_KEY = 7_302_154_001  # pg_advisory_xact_lock key for Studio migrations

DB_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


class _SchemaState:
    def __init__(self) -> None:
        self.ready = False
        self.sweep_pending = True
        self.lock = threading.Lock()
        self.last_error: str | None = None


schema = _SchemaState()


@contextmanager
def connection() -> Iterator:
    """A core-factory connection; commits on success, rolls back on error.

    Connection-level failures become ``StudioError(database_unavailable)``.
    """
    try:
        conn = core_adapter.get_connection()
    except DB_ERRORS as exc:
        log.warning("Database connect failed: %s", type(exc).__name__)
        raise database_unavailable() from exc
    try:
        yield conn
        conn.commit()
    except DB_ERRORS as exc:
        _safe_rollback(conn)
        raise database_unavailable() from exc
    except BaseException:
        _safe_rollback(conn)
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _safe_rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS_DIR.glob("*.sql") if p.name[:3].isdigit())


def migrate() -> list[str]:
    """Apply pending ``studio/migrations/NNN_*.sql`` in order. Returns versions applied now."""
    applied_now: list[str] = []
    conn = core_adapter.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_KEY,))
            cur.execute(
                """CREATE TABLE IF NOT EXISTS studio_schema_migrations (
                       version TEXT PRIMARY KEY,
                       applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
            )
            cur.execute("SELECT version FROM studio_schema_migrations")
            done = {row["version"] for row in cur.fetchall()}
            for path in migration_files():
                version = path.stem
                if version in done:
                    continue
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO studio_schema_migrations (version) VALUES (%s)", (version,))
                applied_now.append(version)
        conn.commit()
    except BaseException:
        _safe_rollback(conn)
        raise
    finally:
        conn.close()
    if applied_now:
        log.info("Applied Studio migrations: %s", ", ".join(applied_now))
    return applied_now


def sweep_orphans() -> int:
    """Documents left in 'processing' by a previous process become failed/interrupted."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE documents SET status = 'failed' WHERE status = 'processing' RETURNING id")
        ids = [row["id"] for row in cur.fetchall()]
        if ids:
            cur.execute(
                """UPDATE studio_document_meta
                   SET error_code = 'interrupted', processed_at = now()
                   WHERE document_id = ANY(%s)""",
                (ids,),
            )
    if ids:
        log.warning("Marked %d interrupted document(s) as failed: %s", len(ids), ids)
    return len(ids)


def ensure_schema() -> bool:
    """Create the core schema and apply Studio migrations once per process.

    Returns True when the schema is ready. Never raises for database problems.
    The orphan sweep runs after the first success following ``reset_for_startup``.
    """
    if schema.ready and not schema.sweep_pending:
        return True
    with schema.lock:
        try:
            if not schema.ready:
                core_adapter.init_db()
                migrate()
                schema.ready = True
                schema.last_error = None
            if schema.sweep_pending:
                sweep_orphans()
                schema.sweep_pending = False
            return True
        except Exception as exc:  # database down, wrong URL, permissions ...
            schema.last_error = type(exc).__name__
            log.warning("Database schema setup not possible yet: %s: %s", type(exc).__name__,
                        str(exc).strip().splitlines()[0] if str(exc).strip() else "")
            return schema.ready and not schema.sweep_pending


def reset_for_startup() -> None:
    schema.ready = False
    schema.sweep_pending = True


def ping() -> None:
    """Raises StudioError(database_unavailable) when the database cannot be queried."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")


def require_db() -> None:
    """FastAPI dependency: the database is reachable and the schema exists."""
    if not ensure_schema():
        raise database_unavailable()


# ---- formatting ------------------------------------------------------------------

def iso_utc(value: datetime | None) -> str | None:
    """ISO 8601 UTC with Z. Naive values (core ``documents.created_at``) are labelled UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
