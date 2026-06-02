"""Database access layer for the Telegram Invoice Bot.

Single source of truth = PostgreSQL (Railway, via DATABASE_URL).

Design goals
------------
* One connection pool for the whole process (psycopg2 ThreadedConnectionPool).
  python-telegram-bot v20 runs handlers on an asyncio loop but the DB calls
  here are synchronous and short; the pool makes them cheap and the
  per-call critical sections are tiny. (If DB calls ever become a latency
  problem, wrap them in asyncio.to_thread — the API below won't change.)
* Connections are never leaked: every borrow goes through the
  `connection()` / `cursor()` context managers which always return the
  connection to the pool, committing on success and rolling back on error.
* Transient connection failures (pool exhaustion, dropped TCP) are retried
  with backoff before giving up.
* No bare excepts. All failures are logged.

This module owns SQL. Higher layers (profile_manager, handlers) call the
typed functions here and never touch psycopg2 directly.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator, Optional, Sequence

import psycopg2
import psycopg2.extras
import psycopg2.pool

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Pool lifecycle
# --------------------------------------------------------------------------

_POOL: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_POOL_LOCK = threading.Lock()

_MIN_CONN = int(os.environ.get("DB_POOL_MIN", "1"))
_MAX_CONN = int(os.environ.get("DB_POOL_MAX", "10"))
_CONNECT_RETRIES = 5
_CONNECT_BACKOFF = 0.5  # seconds, doubled each retry
# When the pool is momentarily exhausted under a burst, wait-and-retry
# instead of failing. ~6s worst case (60 * 0.1s) before giving up.
_POOL_WAIT_RETRIES = 60
_POOL_WAIT_BACKOFF = 0.1


def _normalize_url(url: str) -> str:
    """Railway sometimes emits the legacy 'postgres://' scheme; psycopg2
    is happy with it but SQLAlchemy-style consumers are not, so normalize
    for consistency."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set — check the Railway service variables "
            "(it should reference ${{Postgres.DATABASE_URL}})."
        )
    return _normalize_url(url)


def init_pool() -> None:
    """Create the global connection pool (idempotent).

    Retries the initial connection a few times so a deploy that races the
    database coming up doesn't crash-loop.
    """
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            return
        url = _database_url()
        last_err: Optional[BaseException] = None
        backoff = _CONNECT_BACKOFF
        for attempt in range(1, _CONNECT_RETRIES + 1):
            try:
                _POOL = psycopg2.pool.ThreadedConnectionPool(
                    minconn=_MIN_CONN,
                    maxconn=_MAX_CONN,
                    dsn=url,
                    cursor_factory=psycopg2.extras.RealDictCursor,
                )
                logger.info(
                    "DB pool ready (min=%s max=%s)", _MIN_CONN, _MAX_CONN
                )
                return
            except psycopg2.OperationalError as exc:
                last_err = exc
                logger.warning(
                    "DB pool init attempt %s/%s failed: %s",
                    attempt, _CONNECT_RETRIES, exc,
                )
                time.sleep(backoff)
                backoff *= 2
        raise RuntimeError(
            f"Could not initialise DB pool after {_CONNECT_RETRIES} attempts"
        ) from last_err


def close_pool() -> None:
    """Close all pooled connections (call on shutdown if desired)."""
    global _POOL
    with _POOL_LOCK:
        if _POOL is not None:
            _POOL.closeall()
            _POOL = None
            logger.info("DB pool closed")


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    if _POOL is None:
        init_pool()
    assert _POOL is not None  # for type checkers
    return _POOL


# --------------------------------------------------------------------------
# Context managers — the ONLY way the rest of the module touches the pool
# --------------------------------------------------------------------------

@contextmanager
def connection() -> Iterator[Any]:
    """Borrow a connection from the pool, commit on success / rollback on
    error, and always return it. Retries a fresh borrow if the pooled
    connection turns out to be dead.
    """
    pool = _get_pool()
    conn = None
    last_err: Optional[BaseException] = None
    # More attempts than _CONNECT_RETRIES: pool exhaustion under a burst is
    # transient (other handlers return their connections in milliseconds),
    # so we wait-and-retry rather than failing the request.
    for attempt in range(1, _POOL_WAIT_RETRIES + 1):
        try:
            conn = pool.getconn()
            # Validate the connection isn't stale (cheap check).
            if getattr(conn, "closed", 0):
                pool.putconn(conn, close=True)
                conn = pool.getconn()
            break
        except psycopg2.pool.PoolError as exc:
            # Pool momentarily empty — back off briefly and try again.
            last_err = exc
            time.sleep(_POOL_WAIT_BACKOFF)
        except psycopg2.OperationalError as exc:
            last_err = exc
            logger.warning(
                "Borrowing DB connection failed (attempt %s/%s): %s",
                attempt, _POOL_WAIT_RETRIES, exc,
            )
            time.sleep(_CONNECT_BACKOFF * attempt)
    if conn is None:
        raise RuntimeError("Could not obtain a DB connection") from last_err

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def cursor() -> Iterator[psycopg2.extras.RealDictCursor]:
    """Borrow a connection and hand back a RealDictCursor for the duration."""
    with connection() as conn:
        cur = conn.cursor()
        try:
            yield cur
        finally:
            cur.close()


# --------------------------------------------------------------------------
# Small typed query helpers
# --------------------------------------------------------------------------

def fetch_one(sql: str, params: Sequence[Any] = ()) -> Optional[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return dict(row) if row is not None else None


def fetch_all(sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    """Run a write. Returns affected rowcount."""
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def init_schema(schema_path: str = "schema.sql") -> None:
    """Apply schema.sql once at startup. Idempotent (file is all IF NOT EXISTS)."""
    here = os.path.dirname(os.path.abspath(__file__))
    path = schema_path if os.path.isabs(schema_path) else os.path.join(here, schema_path)
    with open(path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    with connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
    logger.info("Schema applied from %s", path)


# ==========================================================================
# USERS
# ==========================================================================

_USER_SCALAR_COLUMNS = (
    "user_id", "org_name", "phone", "email", "vat_number", "iban",
    "reference_style", "last_invoice_number", "last_quote_number",
    "last_receipt_number", "currency", "language", "default_vat_rate",
)


def get_user(user_id: int) -> Optional[dict[str, Any]]:
    row = fetch_one(
        "SELECT user_id, org_name, phone, email, vat_number, iban, "
        "reference_style, last_invoice_number, last_quote_number, "
        "last_receipt_number, currency, language, default_vat_rate, "
        "created_at, updated_at "
        "FROM users WHERE user_id = %s",
        (int(user_id),),
    )
    if row and row.get("default_vat_rate") is not None:
        row["default_vat_rate"] = _to_float(row["default_vat_rate"])
    return row


def user_exists(user_id: int) -> bool:
    return fetch_one("SELECT 1 FROM users WHERE user_id = %s", (int(user_id),)) is not None


def insert_user(data: dict[str, Any]) -> None:
    cols = list(_USER_SCALAR_COLUMNS)
    placeholders = ", ".join(["%s"] * len(cols))
    values = [data.get(c) for c in cols]
    values[0] = int(data["user_id"])
    execute(
        f"INSERT INTO users ({', '.join(cols)}) VALUES ({placeholders})",
        values,
    )


def update_user_fields(user_id: int, fields: dict[str, Any]) -> None:
    """Update only the scalar profile columns present in `fields`.

    JSONB/history fields are ignored here on purpose — invoices, quotes
    and saved_clients now live in their own tables.
    """
    allowed = {c for c in _USER_SCALAR_COLUMNS if c != "user_id"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    assignments = ", ".join(f"{k} = %s" for k in sets)
    values = list(sets.values()) + [int(user_id)]
    execute(f"UPDATE users SET {assignments} WHERE user_id = %s", values)


def bump_counter(user_id: int, column: str) -> int:
    """Atomic increment of an integer counter, returns the new value.

    Concurrency-safe: read-modify-write happens in one UPDATE statement.
    """
    if column not in {"last_invoice_number", "last_quote_number", "last_receipt_number"}:
        raise ValueError(f"Refusing to bump unknown counter column: {column!r}")
    row = fetch_one(
        f"UPDATE users SET {column} = COALESCE({column}, 0) + 1 "
        f"WHERE user_id = %s RETURNING {column}",
        (int(user_id),),
    )
    if row is None:
        raise KeyError(f"No profile for user_id={user_id}")
    return int(row[column])


# ==========================================================================
# SAVED CLIENTS
# ==========================================================================

def get_saved_clients(user_id: int) -> list[dict[str, Any]]:
    return fetch_all(
        "SELECT name, phone, address, bank, vat "
        "FROM saved_clients WHERE user_id = %s ORDER BY created_at ASC",
        (int(user_id),),
    )


def get_saved_client_by_name(user_id: int, name: str) -> Optional[dict[str, Any]]:
    target = name.strip()
    if not target:
        return None
    return fetch_one(
        "SELECT name, phone, address, bank, vat FROM saved_clients "
        "WHERE user_id = %s AND lower(name) = lower(%s)",
        (int(user_id), target),
    )


def upsert_saved_client(
    user_id: int,
    name: str,
    *,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    bank: Optional[str] = None,
    vat: Optional[str] = None,
) -> None:
    """Insert a client; do nothing if (user, lower(name)) already exists.

    Preserves the old no-update-on-resave behavior. The 3-item cap from
    the JSONB era is intentionally dropped — there's no reason to delete
    a saved client now that they're real rows.
    """
    execute(
        "INSERT INTO saved_clients (user_id, name, phone, address, bank, vat) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (user_id, lower(name)) DO NOTHING",
        (int(user_id), name.strip(), phone, address, bank, vat),
    )


# ==========================================================================
# INVOICES
# ==========================================================================

def _row_to_invoice_record(row: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Map an invoices row + its items back into the dict shape handlers
    expect (the same keys the old JSONB record used)."""
    return {
        "number": int(row["number"]),
        "client_name": row["client_name"],
        "amount": _to_float(row["amount"]),
        "currency": row["currency"],
        "invoice_date": row["invoice_date"],
        "due_date": row["due_date"],
        "sent_at": row["sent_at"].isoformat(timespec="seconds") if row.get("sent_at") else None,
        "paid": row["status"] == "paid",
        "reference": row["reference"],
        "items": [{"name": it["name"], "price": _to_float(it["price"])} for it in items],
        "tax_rate": _to_float(row["tax_rate"]),
        "client_details": row["client_details"],
        "payment_method": row.get("payment_method"),
        "payment_date": row.get("payment_date"),
        "converted_from_quote": row.get("source_quote_number"),
    }


def insert_invoice(user_id: int, record: dict[str, Any]) -> str:
    """Insert one invoice + its line items in a single transaction.

    Returns the new invoice UUID. Idempotent on (user_id, number): if the
    invoice number already exists it is left untouched (defensive against
    double-submit).
    """
    items = record.get("items") or []
    sent_at = record.get("sent_at")  # ISO string or None
    with cursor() as cur:
        cur.execute(
            "INSERT INTO invoices "
            "(user_id, number, client_name, amount, currency, invoice_date, "
            " due_date, sent_at, status, reference, tax_rate, client_details, "
            " source_quote_number, payment_method, payment_date) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id, number) DO NOTHING "
            "RETURNING id",
            (
                int(user_id),
                int(record["number"]),
                record.get("client_name"),
                record.get("amount") or 0,
                record.get("currency") or "EUR",
                record.get("invoice_date"),
                record.get("due_date"),
                sent_at,
                "paid" if record.get("paid") else "unpaid",
                record.get("reference"),
                record.get("tax_rate"),
                psycopg2.extras.Json(record["client_details"])
                if record.get("client_details") is not None else None,
                record.get("converted_from_quote") or record.get("source_quote_number"),
                record.get("payment_method"),
                record.get("payment_date"),
            ),
        )
        row = cur.fetchone()
        if row is None:
            # Conflict: invoice already exists, fetch its id.
            cur.execute(
                "SELECT id FROM invoices WHERE user_id = %s AND number = %s",
                (int(user_id), int(record["number"])),
            )
            row = cur.fetchone()
            return str(row["id"])
        invoice_id = row["id"]
        for pos, it in enumerate(items):
            cur.execute(
                "INSERT INTO invoice_items (invoice_id, position, name, price) "
                "VALUES (%s,%s,%s,%s)",
                (invoice_id, pos, it.get("name", ""), it.get("price") or 0),
            )
        return str(invoice_id)


def get_invoices(user_id: int) -> list[dict[str, Any]]:
    """Return all invoices for the user (newest first), in the legacy
    record shape, with items attached. No cap — financial records are
    never silently dropped."""
    rows = fetch_all(
        "SELECT * FROM invoices WHERE user_id = %s ORDER BY number ASC",
        (int(user_id),),
    )
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    item_rows = fetch_all(
        "SELECT invoice_id, name, price FROM invoice_items "
        "WHERE invoice_id = ANY(%s::uuid[]) ORDER BY position ASC",
        (ids,),
    )
    by_invoice: dict[Any, list[dict[str, Any]]] = {}
    for it in item_rows:
        by_invoice.setdefault(it["invoice_id"], []).append(it)
    return [_row_to_invoice_record(r, by_invoice.get(r["id"], [])) for r in rows]


def mark_invoice_paid(
    user_id: int,
    number: int,
    *,
    payment_method: Optional[str] = None,
    payment_date: Optional[str] = None,
) -> bool:
    """Flip an unpaid invoice to paid. Atomic: the WHERE clause ensures we
    only update if it's currently unpaid, so concurrent calls can't both
    succeed. Returns True iff a row transitioned."""
    rowcount = execute(
        "UPDATE invoices SET status = 'paid', "
        "payment_method = COALESCE(%s, payment_method), "
        "payment_date = COALESCE(%s, payment_date) "
        "WHERE user_id = %s AND number = %s AND status <> 'paid'",
        (payment_method, payment_date, int(user_id), int(number)),
    )
    return rowcount > 0


def stamp_invoice_source_quote(user_id: int, quote_number: int, invoice_number: int) -> None:
    execute(
        "UPDATE invoices SET source_quote_number = %s "
        "WHERE user_id = %s AND number = %s",
        (int(quote_number), int(user_id), int(invoice_number)),
    )


# ==========================================================================
# QUOTES
# ==========================================================================

def _row_to_quote_record(row: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "number": int(row["number"]),
        "client_name": row["client_name"],
        "amount": _to_float(row["amount"]),
        "currency": row["currency"],
        "date": row["quote_date"],
        "valid_until": row["valid_until"],
        "created_at": row["created_at_label"],
        "status": row["status"],
        "vat_rate": _to_float(row["tax_rate"]),
        "tax_rate": _to_float(row["tax_rate"]),
        "client_details": row["client_details"],
        "items": [{"name": it["name"], "price": _to_float(it["price"])} for it in items],
        "converted_invoice_number": row.get("converted_invoice_number"),
    }


def insert_quote(user_id: int, record: dict[str, Any]) -> str:
    items = record.get("items") or []
    with cursor() as cur:
        cur.execute(
            "INSERT INTO quotes "
            "(user_id, number, client_name, amount, currency, quote_date, "
            " valid_until, created_at_label, status, tax_rate, client_details, "
            " converted_invoice_number) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (user_id, number) DO NOTHING "
            "RETURNING id",
            (
                int(user_id),
                int(record["number"]),
                record.get("client_name"),
                record.get("amount") or 0,
                record.get("currency") or "EUR",
                record.get("date") or record.get("quote_date"),
                record.get("valid_until"),
                record.get("created_at"),
                record.get("status") or "Pending",
                record.get("vat_rate") if record.get("vat_rate") is not None
                else record.get("tax_rate"),
                psycopg2.extras.Json(record["client_details"])
                if record.get("client_details") is not None else None,
                record.get("converted_invoice_number"),
            ),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(
                "SELECT id FROM quotes WHERE user_id = %s AND number = %s",
                (int(user_id), int(record["number"])),
            )
            return str(cur.fetchone()["id"])
        quote_id = row["id"]
        for pos, it in enumerate(items):
            cur.execute(
                "INSERT INTO quote_items (quote_id, position, name, price) "
                "VALUES (%s,%s,%s,%s)",
                (quote_id, pos, it.get("name", ""), it.get("price") or 0),
            )
        return str(quote_id)


def get_quotes(user_id: int) -> list[dict[str, Any]]:
    rows = fetch_all(
        "SELECT * FROM quotes WHERE user_id = %s ORDER BY number ASC",
        (int(user_id),),
    )
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    item_rows = fetch_all(
        "SELECT quote_id, name, price FROM quote_items "
        "WHERE quote_id = ANY(%s::uuid[]) ORDER BY position ASC",
        (ids,),
    )
    by_quote: dict[Any, list[dict[str, Any]]] = {}
    for it in item_rows:
        by_quote.setdefault(it["quote_id"], []).append(it)
    return [_row_to_quote_record(r, by_quote.get(r["id"], [])) for r in rows]


def get_quote_by_number(user_id: int, number: int) -> Optional[dict[str, Any]]:
    row = fetch_one(
        "SELECT * FROM quotes WHERE user_id = %s AND number = %s",
        (int(user_id), int(number)),
    )
    if row is None:
        return None
    items = fetch_all(
        "SELECT name, price FROM quote_items WHERE quote_id = %s ORDER BY position ASC",
        (row["id"],),
    )
    return _row_to_quote_record(row, items)


def update_quote_status(user_id: int, number: int, status: str) -> bool:
    """Set status, but never move a Converted quote (terminal)."""
    rowcount = execute(
        "UPDATE quotes SET status = %s "
        "WHERE user_id = %s AND number = %s AND status <> 'Converted'",
        (status, int(user_id), int(number)),
    )
    return rowcount > 0


def mark_quote_converted(
    user_id: int, number: int, invoice_number: Optional[int] = None
) -> bool:
    """Atomically mark Converted; returns False if already converted
    (double-conversion guard) or not found."""
    rowcount = execute(
        "UPDATE quotes SET status = 'Converted', "
        "converted_invoice_number = COALESCE(%s, converted_invoice_number) "
        "WHERE user_id = %s AND number = %s AND status <> 'Converted'",
        (invoice_number, int(user_id), int(number)),
    )
    return rowcount > 0


def stamp_quote_converted_invoice(user_id: int, quote_number: int, invoice_number: int) -> None:
    execute(
        "UPDATE quotes SET converted_invoice_number = %s "
        "WHERE user_id = %s AND number = %s",
        (int(invoice_number), int(user_id), int(quote_number)),
    )


def upsert_quote(user_id: int, record: dict[str, Any]) -> str:
    """Insert a quote, or fully replace an existing one with the same
    (user_id, number) — used by the 'edit quote' flow. Replaces the
    quote's scalar fields and its item rows atomically.

    Will not resurrect/overwrite a Converted quote (terminal).
    """
    items = record.get("items") or []
    number = int(record["number"])
    with cursor() as cur:
        cur.execute(
            "SELECT id, status FROM quotes WHERE user_id = %s AND number = %s",
            (int(user_id), number),
        )
        existing = cur.fetchone()
        if existing is None:
            # Delegate to plain insert path (reuse same connection).
            cur.execute(
                "INSERT INTO quotes "
                "(user_id, number, client_name, amount, currency, quote_date, "
                " valid_until, created_at_label, status, tax_rate, client_details, "
                " converted_invoice_number) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    int(user_id), number, record.get("client_name"),
                    record.get("amount") or 0, record.get("currency") or "EUR",
                    record.get("date") or record.get("quote_date"),
                    record.get("valid_until"), record.get("created_at"),
                    record.get("status") or "Pending",
                    record.get("vat_rate") if record.get("vat_rate") is not None
                    else record.get("tax_rate"),
                    psycopg2.extras.Json(record["client_details"])
                    if record.get("client_details") is not None else None,
                    record.get("converted_invoice_number"),
                ),
            )
            quote_id = cur.fetchone()["id"]
        else:
            if existing["status"] == "Converted":
                # Terminal — refuse to edit a converted quote.
                return str(existing["id"])
            quote_id = existing["id"]
            cur.execute(
                "UPDATE quotes SET client_name=%s, amount=%s, currency=%s, "
                "quote_date=%s, valid_until=%s, created_at_label=%s, status=%s, "
                "tax_rate=%s, client_details=%s WHERE id=%s",
                (
                    record.get("client_name"), record.get("amount") or 0,
                    record.get("currency") or "EUR",
                    record.get("date") or record.get("quote_date"),
                    record.get("valid_until"), record.get("created_at"),
                    record.get("status") or "Pending",
                    record.get("vat_rate") if record.get("vat_rate") is not None
                    else record.get("tax_rate"),
                    psycopg2.extras.Json(record["client_details"])
                    if record.get("client_details") is not None else None,
                    quote_id,
                ),
            )
            cur.execute("DELETE FROM quote_items WHERE quote_id = %s", (quote_id,))
        for pos, it in enumerate(items):
            cur.execute(
                "INSERT INTO quote_items (quote_id, position, name, price) "
                "VALUES (%s,%s,%s,%s)",
                (quote_id, pos, it.get("name", ""), it.get("price") or 0),
            )
        return str(quote_id)


def delete_quote(user_id: int, number: int) -> bool:
    """Delete a quote (and its items via FK cascade). Returns True if a
    row was removed."""
    rowcount = execute(
        "DELETE FROM quotes WHERE user_id = %s AND number = %s",
        (int(user_id), int(number)),
    )
    return rowcount > 0
