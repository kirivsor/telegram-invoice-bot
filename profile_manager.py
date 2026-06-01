"""User profile persistence for the Telegram Invoice Bot.

Profiles are stored in a PostgreSQL `users` table (one row per user).
Connection details come from the DATABASE_URL environment variable
(injected automatically by Railway). All public functions are
intentionally thin wrappers so callers never touch the database
directly.

Public API
----------
has_profile(user_id)             -> bool
create_profile(user_id, ...)     -> dict
get_profile(user_id)             -> dict | None
update_profile(user_id, **kw)    -> dict
increment_invoice_number(user_id) -> int
update_default_currency(user_id, currency) -> None
update_default_vat_rate(user_id, vat_rate) -> None
save_client(user_id, client_name, *, phone, address, bank, vat) -> None
get_saved_clients(user_id)       -> list[dict]
get_saved_client_by_name(user_id, name) -> dict | None
record_invoice(user_id, record)  -> None
get_invoices(user_id)            -> list[dict]
mark_invoice_paid(user_id, number) -> bool
increment_receipt_number(user_id) -> int
increment_quote_number(user_id) -> int
record_quote(user_id, record) -> None
get_quotes(user_id) -> list[dict]
get_quote_by_number(user_id, number) -> dict | None
update_quote_status(user_id, number, status) -> bool
mark_quote_converted(user_id, number, invoice_number=None) -> bool
"""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.extensions

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# The canonical set of keys every profile must contain.
# Used both as documentation and for forward-compat defaults when
# reading rows written by an older version of the bot.
PROFILE_SCHEMA: dict[str, Any] = {
    "user_id": int,
    "org_name": str,
    "phone": str,
    "email": str,                      # optional; "" when not provided
    "vat_number": str,                 # optional; "" when not provided
    "iban": str,
    "reference_style": str,            # "Standard" | "None"
    "last_invoice_number": int,
    "currency": str,                   # ISO 4217 code, e.g. "EUR"
    "language": str,                   # "en" | "ru"; default "en"
    "default_vat_rate": float,         # default VAT % applied to new docs, e.g. 21.0
    "saved_clients": list[dict],       # up to 3 recently saved client records (Bug 3)
    "invoices": list[dict],            # list of generated invoice records (Fix 5)
    "last_quote_number": int,          # Goal 1 — independent quote counter (Q-#####)
    "quotes": list[dict],              # Goal 1 — list of generated quote records
}

CURRENCY_DEFAULT = "EUR"

# Default VAT rate (as a human-facing percentage, e.g. 21.0 == 21%).
# 0.0 means "not VAT registered / no VAT". Stored per profile so new
# invoices and quotes can pre-fill it; always overridable per document.
VAT_RATE_DEFAULT = 0.0

# Max number of invoice records kept per user. Older ones get evicted
# (FIFO) so the row never grows unbounded. 500 is plenty for a
# personal/freelance bot — bump if you ever need more.
MAX_INVOICE_HISTORY = 500

# Same idea for quotes (Goal 1).
MAX_QUOTE_HISTORY = 500

# Canonical quote statuses. "converted" is terminal — a converted quote
# can never be converted again (double-conversion guard).
QUOTE_STATUS_PENDING = "Pending"
QUOTE_STATUS_ACCEPTED = "Accepted"
QUOTE_STATUS_CONVERTED = "Converted"

# Canonical empty client-record template. Used by both the migration
# path and save_client; keeping it here makes the schema obvious.
_EMPTY_CLIENT_RECORD: dict[str, Any] = {
    "name": "",
    "phone": None,
    "address": None,
    "bank": None,
    "vat": None,
}

# The full ordered column list used by every read and the upsert.
_COLUMNS: tuple[str, ...] = (
    "user_id",
    "org_name",
    "phone",
    "email",
    "vat_number",
    "iban",
    "reference_style",
    "last_invoice_number",
    "last_quote_number",
    "last_receipt_number",
    "currency",
    "language",
    "default_vat_rate",
    "saved_clients",
    "invoices",
    "quotes",
)

# Columns that are stored as JSONB and need json.dumps() on write.
_JSONB_COLUMNS: frozenset[str] = frozenset({"saved_clients", "invoices", "quotes"})

# ---------------------------------------------------------------------------
# Connection / schema bootstrap
# ---------------------------------------------------------------------------

def _get_conn():
    """Open a new connection using DATABASE_URL with RealDictCursor."""
    url = os.environ["DATABASE_URL"]
    # Railway may emit "postgres://" (legacy) — normalise to "postgresql://".
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(
        url,
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _init_db() -> None:
    """Create the `users` table if it does not already exist.

    Called once at startup (from main.py) so a fresh deploy has its
    schema before the bot serves any update.
    """
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    org_name TEXT,
                    phone TEXT,
                    email TEXT DEFAULT '',
                    vat_number TEXT DEFAULT '',
                    iban TEXT,
                    reference_style TEXT DEFAULT 'Standard',
                    last_invoice_number INT DEFAULT 0,
                    last_quote_number INT DEFAULT 0,
                    last_receipt_number INT DEFAULT 0,
                    currency TEXT DEFAULT 'EUR',
                    language TEXT DEFAULT 'en',
                    default_vat_rate NUMERIC(5,2) DEFAULT 0.0,
                    saved_clients JSONB DEFAULT '[]',
                    invoices JSONB DEFAULT '[]',
                    quotes JSONB DEFAULT '[]'
                )
                """
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load(user_id: int | str) -> dict[str, Any] | None:
    """Fetch a single user row as a plain dict, or None if absent.

    RealDictCursor returns JSONB columns already decoded into Python
    lists/dicts, and NUMERIC into Decimal — callers normalise as needed.
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (int(user_id),))
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return dict(row)


def _save(user_id: int | str, data: dict[str, Any]) -> None:
    """Upsert the full profile dict into the users table.

    A single INSERT ... ON CONFLICT (user_id) DO UPDATE writes every
    managed column. JSONB columns are json.dumps()'d; everything else
    is passed through as-is.
    """
    values: list[Any] = []
    for col in _COLUMNS:
        if col == "user_id":
            values.append(int(user_id))
            continue
        val = data.get(col)
        if col in _JSONB_COLUMNS:
            values.append(json.dumps(val if val is not None else []))
        elif col == "default_vat_rate":
            values.append(float(val) if val is not None else VAT_RATE_DEFAULT)
        else:
            values.append(val)

    placeholders = ", ".join(["%s"] * len(_COLUMNS))
    column_list = ", ".join(_COLUMNS)
    update_assignments = ", ".join(
        f"{col} = EXCLUDED.{col}" for col in _COLUMNS if col != "user_id"
    )

    sql = (
        f"INSERT INTO users ({column_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (user_id) DO UPDATE SET {update_assignments}"
    )

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql, values)
    finally:
        conn.close()


def _opt_str(value: Any) -> str | None:
    """Coerce *value* to a stripped non-empty str, or None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_client_record(entry: Any) -> dict[str, Any] | None:
    """Coerce a saved_clients entry into the canonical dict shape.

    Returns None for malformed input (e.g. dict without a name). Legacy
    plain-string entries are converted on the fly.
    """
    if isinstance(entry, str):
        name = entry.strip()
        if not name:
            return None
        return {
            "name": name,
            "phone": None,
            "address": None,
            "bank": None,
            "vat": None,
        }
    if isinstance(entry, dict):
        name = str(entry.get("name", "")).strip()
        if not name:
            return None
        return {
            "name": name,
            "phone": _opt_str(entry.get("phone")),
            "address": _opt_str(entry.get("address")),
            "bank": _opt_str(entry.get("bank")),
            "vat": _opt_str(entry.get("vat")),
        }
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def has_profile(user_id: int | str) -> bool:
    """Return True if a profile exists for *user_id*."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM users WHERE user_id = %s", (int(user_id),)
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def create_profile(
    user_id: int | str,
    *,
    org_name: str,
    phone: str,
    iban: str,
    reference_style: str = "Standard",
    email: str = "",
    vat_number: str = "",
    currency: str = CURRENCY_DEFAULT,
    language: str = "en",
    default_vat_rate: float = VAT_RATE_DEFAULT,
) -> dict[str, Any]:
    """Create and persist a new profile.  Raises FileExistsError if one
    already exists (callers should call has_profile() first).

    `email` and `vat_number` are optional; pass "" (or omit) when the
    user skipped them.
    `currency` is the user's chosen default invoice currency.
    `language` is the user's chosen UI language ("en" | "ru").
    `default_vat_rate` is the user's default VAT percentage (e.g. 21.0);
    0.0 means no VAT. Always overridable per document.
    """
    if has_profile(user_id):
        raise FileExistsError(f"Profile for {user_id} already exists")

    try:
        vat_rate = round(float(default_vat_rate), 2)
    except (TypeError, ValueError):
        vat_rate = VAT_RATE_DEFAULT
    if vat_rate < 0:
        vat_rate = VAT_RATE_DEFAULT

    data: dict[str, Any] = {
        "user_id": int(user_id),
        "org_name": org_name,
        "phone": phone,
        "email": (email or "").strip(),
        "vat_number": (vat_number or "").strip(),
        "iban": iban,
        "reference_style": reference_style,
        "last_invoice_number": 0,
        "currency": (currency or CURRENCY_DEFAULT).strip().upper() or CURRENCY_DEFAULT,
        "language": (language or "en").strip().lower() or "en",
        "default_vat_rate": vat_rate,
        "saved_clients": [],
        "invoices": [],
        "last_quote_number": 0,
        "last_receipt_number": 0,
        "quotes": [],
    }
    _save(user_id, data)
    return data


def get_profile(user_id: int | str) -> dict[str, Any] | None:
    """Return the profile dict, or None if the user has no profile.

    Missing keys (from older row versions) are filled in with defaults
    so callers can always rely on the full schema.

    Bug 3 — Legacy saved_clients entries written as plain strings are
    converted in-memory to the canonical dict shape on every read. The
    migration is non-persistent (no write side-effect from this read);
    the next save_client call naturally writes the normalized form.
    """
    data = _load(user_id)
    if data is None:
        return None

    # NUMERIC(5,2) comes back as Decimal — present it as a float so
    # callers (and the JSON-era contract) keep seeing a float.
    if data.get("default_vat_rate") is not None:
        try:
            data["default_vat_rate"] = float(data["default_vat_rate"])
        except (TypeError, ValueError):
            data["default_vat_rate"] = VAT_RATE_DEFAULT

    # Forward-compat defaults for keys added after initial release.
    data.setdefault("last_invoice_number", 0)
    data.setdefault("currency", CURRENCY_DEFAULT)
    data.setdefault("language", "en")
    data.setdefault("default_vat_rate", VAT_RATE_DEFAULT)
    data.setdefault("saved_clients", [])
    data.setdefault("email", "")
    data.setdefault("vat_number", "")
    data.setdefault("invoices", [])
    data.setdefault("last_quote_number", 0)
    data.setdefault("quotes", [])

    # Guard against NULL columns coming back from Postgres for the JSONB
    # history fields (treated the same as "missing" by callers).
    if data.get("saved_clients") is None:
        data["saved_clients"] = []
    if data.get("invoices") is None:
        data["invoices"] = []
    if data.get("quotes") is None:
        data["quotes"] = []

    # Bug 3 — normalize saved_clients into list[dict].
    normalized: list[dict[str, Any]] = []
    for entry in data.get("saved_clients") or []:
        record = _normalize_client_record(entry)
        if record is not None:
            normalized.append(record)
    data["saved_clients"] = normalized

    return data


def update_profile(user_id: int | str, **fields: Any) -> dict[str, Any]:
    """Update one or more fields on an existing profile.

    Raises KeyError if the profile does not exist.
    Unknown field names are accepted (forward-compat).
    """
    data = _load(user_id)
    if data is None:
        raise KeyError(f"No profile for user_id={user_id}")

    data.update(fields)
    _save(user_id, data)
    return data


def increment_invoice_number(user_id: int | str) -> int:
    """Atomically increment last_invoice_number and return the new value."""
    data = _load(user_id)
    if data is None:
        raise KeyError(f"No profile for user_id={user_id}")

    new_number = int(data.get("last_invoice_number", 0)) + 1
    data["last_invoice_number"] = new_number
    _save(user_id, data)
    return new_number


def update_default_currency(user_id: int | str, currency: str) -> None:
    """Persist *currency* as the user's new default invoice currency.

    No-op if the profile does not exist (best-effort, never raises).
    """
    try:
        update_profile(user_id, currency=currency.strip().upper())
    except KeyError:
        pass


def update_default_vat_rate(user_id: int | str, vat_rate: float) -> None:
    """Persist *vat_rate* (a percentage, e.g. 21.0) as the user's default.

    Coerces to a non-negative float rounded to 2 decimals. No-op if the
    profile does not exist (best-effort, never raises).
    """
    try:
        rate = round(float(vat_rate), 2)
    except (TypeError, ValueError):
        return
    if rate < 0:
        rate = 0.0
    try:
        update_profile(user_id, default_vat_rate=rate)
    except KeyError:
        pass


def save_client(
    user_id: int | str,
    client_name: str,
    *,
    phone: str | None = None,
    address: str | None = None,
    bank: str | None = None,
    vat: str | None = None,
) -> None:
    """Append a client record to the user's saved_clients list (max 3).

    Bug 3 — A client record is now a dict with name + optional phone /
    address / bank / vat. The legacy str-only form is silently migrated
    on read (see get_profile).

    Rules:
    - client_name is stripped of leading/trailing whitespace.
    - If the stripped name is already present (case-insensitive), the
      call is a no-op. (No update-on-resave — kept for backwards
      compatibility with previous behavior.)
    - Each optional field is stripped; empty strings become None.
    - The list is capped at 3 entries; the oldest is evicted on overflow.
    - No-op if the profile does not exist.
    """
    profile = get_profile(user_id)
    if profile is None:
        return

    name = client_name.strip()
    if not name:
        return

    saved: list[dict[str, Any]] = list(profile.get("saved_clients") or [])

    name_lower = name.lower()
    if any(str(s.get("name", "")).lower() == name_lower for s in saved):
        return

    record = {
        "name": name,
        "phone": _opt_str(phone),
        "address": _opt_str(address),
        "bank": _opt_str(bank),
        "vat": _opt_str(vat),
    }
    saved.append(record)

    # Cap at 3 — drop the oldest when over the limit.
    while len(saved) > 3:
        saved.pop(0)

    update_profile(user_id, saved_clients=saved)


def get_saved_clients(user_id: int | str) -> list[dict[str, Any]]:
    """Return the saved_clients list for user_id, or [] if missing/no profile.

    Bug 3 — Returns list[dict] now. Callers that only need names (e.g.
    keyboard rendering) should extract the "name" field; keyboards.py
    handles both legacy list[str] and new list[dict] for safety.
    """
    profile = get_profile(user_id)
    if profile is None:
        return []
    return list(profile.get("saved_clients") or [])


def get_saved_client_by_name(
    user_id: int | str, name: str
) -> dict[str, Any] | None:
    """Look up a saved client by name (case-insensitive).

    Returns the stored record (with all optional fields), or None if
    the user has no profile or no client with that name. (Bug 3.)
    """
    profile = get_profile(user_id)
    if profile is None:
        return None
    target = name.strip().lower()
    if not target:
        return None
    for entry in profile.get("saved_clients") or []:
        if str(entry.get("name", "")).lower() == target:
            return dict(entry)
    return None


# ---------------------------------------------------------------------------
# Invoice tracking (Fix 5)
# ---------------------------------------------------------------------------

def record_invoice(user_id: int | str, record: dict[str, Any]) -> None:
    """Append a generated invoice's metadata to the user's history.

    `record` should contain at least: number, client_name, amount,
    currency, due_date, sent_at, paid, reference. Extra keys are
    accepted but the canonical set is what the tracking UI reads.

    Caps the history at MAX_INVOICE_HISTORY entries (FIFO eviction).
    No-op if the profile does not exist.
    """
    profile = get_profile(user_id)
    if profile is None:
        return

    invoices = list(profile.get("invoices") or [])
    invoices.append(record)

    # Evict oldest entries if we're over the cap.
    while len(invoices) > MAX_INVOICE_HISTORY:
        invoices.pop(0)

    update_profile(user_id, invoices=invoices)


def get_invoices(user_id: int | str) -> list[dict[str, Any]]:
    """Return the invoice history list, or [] if missing/no profile."""
    profile = get_profile(user_id)
    if profile is None:
        return []
    return list(profile.get("invoices") or [])


def mark_invoice_paid(
    user_id: int | str,
    number: int,
    *,
    payment_method: str | None = None,
    payment_date: str | None = None,
) -> bool:
    """Mark the invoice with the given number as paid.

    Optionally also stamps the payment_method (free text or canonical
    label) and payment_date (pre-formatted string), so the auto-receipt
    in handlers.py and any future re-render stay consistent.

    Returns True if a matching unpaid invoice was found and flipped,
    False otherwise (already paid, not found, or no profile).
    """
    profile = get_profile(user_id)
    if profile is None:
        return False

    invoices = list(profile.get("invoices") or [])
    changed = False
    for inv in invoices:
        try:
            if int(inv.get("number", -1)) == int(number) and not inv.get("paid"):
                inv["paid"] = True
                if payment_method is not None:
                    inv["payment_method"] = payment_method
                if payment_date is not None:
                    inv["payment_date"] = payment_date
                changed = True
                break
        except (TypeError, ValueError):
            continue

    if changed:
        update_profile(user_id, invoices=invoices)
    return changed


def increment_receipt_number(user_id: int | str) -> int:
    """Atomically increment last_receipt_number and return the new value.

    Receipts are numbered independently of invoices (RCP-#####).
    """
    data = _load(user_id)
    if data is None:
        raise KeyError(f"No profile for user_id={user_id}")

    new_number = int(data.get("last_receipt_number", 0) or 0) + 1
    data["last_receipt_number"] = new_number
    _save(user_id, data)
    return new_number


# ---------------------------------------------------------------------------
# Quote tracking (Goal 1)
# ---------------------------------------------------------------------------

def increment_quote_number(user_id: int | str) -> int:
    """Atomically increment last_quote_number and return the new value.

    Quotes are numbered independently of invoices (Q-#####).
    """
    data = _load(user_id)
    if data is None:
        raise KeyError(f"No profile for user_id={user_id}")

    new_number = int(data.get("last_quote_number", 0) or 0) + 1
    data["last_quote_number"] = new_number
    _save(user_id, data)
    return new_number


def record_quote(user_id: int | str, record: dict[str, Any]) -> None:
    """Append a generated quote's metadata to the user's history.

    `record` should contain at least: number, client_name, amount,
    currency, valid_until, created_at, status, items, vat_rate,
    client_details. Caps the history at MAX_QUOTE_HISTORY (FIFO).
    No-op if the profile does not exist.
    """
    profile = get_profile(user_id)
    if profile is None:
        return

    quotes = list(profile.get("quotes") or [])
    quotes.append(record)

    while len(quotes) > MAX_QUOTE_HISTORY:
        quotes.pop(0)

    update_profile(user_id, quotes=quotes)


def get_quotes(user_id: int | str) -> list[dict[str, Any]]:
    """Return the quote history list, or [] if missing/no profile."""
    profile = get_profile(user_id)
    if profile is None:
        return []
    return list(profile.get("quotes") or [])


def get_quote_by_number(
    user_id: int | str, number: int
) -> dict[str, Any] | None:
    """Return a single quote record by its number, or None if not found."""
    profile = get_profile(user_id)
    if profile is None:
        return None
    for q in profile.get("quotes") or []:
        try:
            if int(q.get("number", -1)) == int(number):
                return dict(q)
        except (TypeError, ValueError):
            continue
    return None


def update_quote_status(
    user_id: int | str, number: int, status: str
) -> bool:
    """Set a quote's status (Pending / Accepted / Converted).

    Returns True if a matching quote was found and updated, else False.
    Will not move a quote *out* of the Converted (terminal) state.
    """
    profile = get_profile(user_id)
    if profile is None:
        return False

    quotes = list(profile.get("quotes") or [])
    changed = False
    for q in quotes:
        try:
            if int(q.get("number", -1)) == int(number):
                if str(q.get("status")) == QUOTE_STATUS_CONVERTED:
                    return False  # terminal — never un-convert
                q["status"] = status
                changed = True
                break
        except (TypeError, ValueError):
            continue

    if changed:
        update_profile(user_id, quotes=quotes)
    return changed


def mark_quote_converted(
    user_id: int | str, number: int, invoice_number: int | None = None
) -> bool:
    """Mark a quote as Converted (terminal) so it can't be re-converted.

    Optionally stamps the invoice_number it was converted into. Returns
    True only if the quote existed and was NOT already converted; returns
    False if it was already converted (the double-conversion guard) or
    not found.
    """
    profile = get_profile(user_id)
    if profile is None:
        return False

    quotes = list(profile.get("quotes") or [])
    changed = False
    for q in quotes:
        try:
            if int(q.get("number", -1)) == int(number):
                if str(q.get("status")) == QUOTE_STATUS_CONVERTED:
                    return False  # already converted — guard
                q["status"] = QUOTE_STATUS_CONVERTED
                if invoice_number is not None:
                    q["converted_invoice_number"] = int(invoice_number)
                changed = True
                break
        except (TypeError, ValueError):
            continue

    if changed:
        update_profile(user_id, quotes=quotes)
    return changed
