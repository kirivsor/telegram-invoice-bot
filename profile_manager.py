"""User profile + document persistence for the Telegram Invoice Bot.

REFACTORED (Stage 1): this module is now a thin facade over `db.py`.
Its public API is **unchanged** so handlers.py keeps working without
edits — but underneath, invoices / quotes / saved_clients are real
normalized tables instead of JSONB blobs on the users row.

What changed vs. the JSONB era
-------------------------------
* record_invoice / record_quote          -> INSERT a row (+ item rows)
* mark_invoice_paid / update_quote_status -> atomic UPDATE (no race)
* save_client                            -> INSERT ... ON CONFLICT
* get_*                                  -> SELECT from the new tables
* The 500-record cap and 3-client cap are GONE: financial records are
  never silently deleted.

Public API (unchanged)
----------------------
has_profile / create_profile / get_profile / update_profile
increment_invoice_number / increment_quote_number / increment_receipt_number
update_default_currency / update_default_vat_rate
save_client / get_saved_clients / get_saved_client_by_name
record_invoice / get_invoices / mark_invoice_paid
record_quote / get_quotes / get_quote_by_number
update_quote_status / mark_quote_converted
"""

from __future__ import annotations

import logging
from typing import Any

import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants kept for backwards-compat (handlers import these)
# ---------------------------------------------------------------------------

CURRENCY_DEFAULT = "EUR"
VAT_RATE_DEFAULT = 0.0

QUOTE_STATUS_PENDING = "Pending"
QUOTE_STATUS_ACCEPTED = "Accepted"
QUOTE_STATUS_CONVERTED = "Converted"


def _init_db() -> None:
    """Bootstrap the connection pool and apply schema.sql (idempotent).

    Called once from main.py at startup. Kept under the old name so
    main.py needs no change.
    """
    db.init_pool()
    db.init_schema()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def has_profile(user_id: int | str) -> bool:
    return db.user_exists(int(user_id))


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
    """Create and persist a new profile. Raises FileExistsError if present."""
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
        "last_quote_number": 0,
        "last_receipt_number": 0,
        "currency": (currency or CURRENCY_DEFAULT).strip().upper() or CURRENCY_DEFAULT,
        "language": (language or "en").strip().lower() or "en",
        "default_vat_rate": vat_rate,
    }
    db.insert_user(data)
    return get_profile(user_id) or data


def get_profile(user_id: int | str) -> dict[str, Any] | None:
    """Return the profile dict, or None. Shape matches the old contract:
    scalar fields PLUS saved_clients / invoices / quotes (now loaded from
    their own tables, so old callers that read these keys still work)."""
    row = db.get_user(int(user_id))
    if row is None:
        return None

    row.setdefault("last_invoice_number", 0)
    row.setdefault("last_quote_number", 0)
    row.setdefault("last_receipt_number", 0)
    row.setdefault("currency", CURRENCY_DEFAULT)
    row.setdefault("language", "en")
    row.setdefault("default_vat_rate", VAT_RATE_DEFAULT)
    row.setdefault("email", "")
    row.setdefault("vat_number", "")

    # Attach the related collections so legacy callers reading
    # profile["saved_clients"] / ["invoices"] / ["quotes"] keep working.
    row["saved_clients"] = db.get_saved_clients(int(user_id))
    row["invoices"] = db.get_invoices(int(user_id))
    row["quotes"] = db.get_quotes(int(user_id))
    return row


def update_profile(user_id: int | str, **fields: Any) -> dict[str, Any]:
    """Update profile fields. Raises KeyError if the profile is absent.

    NOTE: writes to the JSONB-era keys 'invoices' / 'quotes' /
    'saved_clients' are now IGNORED (those are real tables). Any handler
    still trying to bulk-rewrite those lists is a no-op for the list part;
    use record_invoice / record_quote / save_client / mark_* instead.
    """
    if not has_profile(user_id):
        raise KeyError(f"No profile for user_id={user_id}")
    ignored = {"invoices", "quotes", "saved_clients"}
    scalar = {k: v for k, v in fields.items() if k not in ignored}
    if any(k in ignored for k in fields):
        logger.debug(
            "update_profile ignored collection keys %s for user_id=%s "
            "(use record_/save_/mark_ helpers instead)",
            [k for k in fields if k in ignored], user_id,
        )
    if scalar:
        db.update_user_fields(int(user_id), scalar)
    return get_profile(user_id) or {}


def increment_invoice_number(user_id: int | str) -> int:
    return db.bump_counter(int(user_id), "last_invoice_number")


def increment_quote_number(user_id: int | str) -> int:
    return db.bump_counter(int(user_id), "last_quote_number")


def increment_receipt_number(user_id: int | str) -> int:
    return db.bump_counter(int(user_id), "last_receipt_number")


def update_default_currency(user_id: int | str, currency: str) -> None:
    try:
        update_profile(user_id, currency=currency.strip().upper())
    except KeyError:
        pass


def update_default_vat_rate(user_id: int | str, vat_rate: float) -> None:
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


# ---------------------------------------------------------------------------
# Saved clients
# ---------------------------------------------------------------------------

def save_client(
    user_id: int | str,
    client_name: str,
    *,
    phone: str | None = None,
    address: str | None = None,
    bank: str | None = None,
    vat: str | None = None,
) -> None:
    """Insert a saved client (no-op if the name already exists for this
    user, case-insensitive). No-op if the profile doesn't exist."""
    if not has_profile(user_id):
        return
    name = client_name.strip()
    if not name:
        return
    db.upsert_saved_client(
        int(user_id), name,
        phone=_opt_str(phone), address=_opt_str(address),
        bank=_opt_str(bank), vat=_opt_str(vat),
    )


def get_saved_clients(user_id: int | str) -> list[dict[str, Any]]:
    return db.get_saved_clients(int(user_id))


def get_saved_client_by_name(user_id: int | str, name: str) -> dict[str, Any] | None:
    return db.get_saved_client_by_name(int(user_id), name)


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def record_invoice(user_id: int | str, record: dict[str, Any]) -> None:
    """Persist a generated invoice (+ its line items) as real rows.
    No-op if the profile doesn't exist."""
    if not has_profile(user_id):
        return
    try:
        db.insert_invoice(int(user_id), record)
    except Exception:
        logger.exception("Failed to record invoice for user_id=%s", user_id)
        raise


def get_invoices(user_id: int | str) -> list[dict[str, Any]]:
    return db.get_invoices(int(user_id))


def mark_invoice_paid(
    user_id: int | str,
    number: int,
    *,
    payment_method: str | None = None,
    payment_date: str | None = None,
) -> bool:
    return db.mark_invoice_paid(
        int(user_id), int(number),
        payment_method=payment_method, payment_date=payment_date,
    )


# ---------------------------------------------------------------------------
# Quotes
# ---------------------------------------------------------------------------

def record_quote(user_id: int | str, record: dict[str, Any]) -> None:
    if not has_profile(user_id):
        return
    try:
        db.insert_quote(int(user_id), record)
    except Exception:
        logger.exception("Failed to record quote for user_id=%s", user_id)
        raise


def get_quotes(user_id: int | str) -> list[dict[str, Any]]:
    return db.get_quotes(int(user_id))


def get_quote_by_number(user_id: int | str, number: int) -> dict[str, Any] | None:
    return db.get_quote_by_number(int(user_id), int(number))


def update_quote_status(user_id: int | str, number: int, status: str) -> bool:
    return db.update_quote_status(int(user_id), int(number), status)


def mark_quote_converted(
    user_id: int | str, number: int, invoice_number: int | None = None
) -> bool:
    return db.mark_quote_converted(int(user_id), int(number), invoice_number)


def update_quote(user_id: int | str, record: dict[str, Any]) -> None:
    """Insert-or-replace a quote in place (used by the edit-quote flow).
    No-op if the profile doesn't exist."""
    if not has_profile(user_id):
        return
    try:
        db.upsert_quote(int(user_id), record)
    except Exception:
        logger.exception("Failed to update quote for user_id=%s", user_id)
        raise


def delete_quote(user_id: int | str, number: int) -> bool:
    """Delete a quote and its items. Returns True if removed."""
    return db.delete_quote(int(user_id), int(number))
