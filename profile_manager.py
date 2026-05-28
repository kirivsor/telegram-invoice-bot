"""User profile persistence for the Telegram Invoice Bot.

Profiles are stored as JSON files, one per user, under DATA_DIR.
All public functions are intentionally thin wrappers so callers
never need to touch the filesystem directly.

Public API
----------
has_profile(user_id)             -> bool
create_profile(user_id, ...)     -> dict
get_profile(user_id)             -> dict | None
update_profile(user_id, **kw)    -> dict
increment_invoice_number(user_id) -> int
update_default_currency(user_id, currency) -> None
save_client(user_id, client_name, *, phone, address, bank, vat) -> None
get_saved_clients(user_id)       -> list[dict]
get_saved_client_by_name(user_id, name) -> dict | None
record_invoice(user_id, record)  -> None
get_invoices(user_id)            -> list[dict]
mark_invoice_paid(user_id, number) -> bool
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Storage location
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

# The canonical set of keys every profile must contain.
# Used both as documentation and for forward-compat defaults when
# reading profiles written by an older version of the bot.
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
    "saved_clients": list[dict],       # up to 3 recently saved client records (Bug 3)
    "invoices": list[dict],            # list of generated invoice records (Fix 5)
}

CURRENCY_DEFAULT = "EUR"

# Max number of invoice records kept per user. Older ones get evicted
# (FIFO) so the JSON file never grows unbounded. 500 is plenty for a
# personal/freelance bot — bump if you ever need more.
MAX_INVOICE_HISTORY = 500

# Canonical empty client-record template. Used by both the migration
# path and save_client; keeping it here makes the schema obvious.
_EMPTY_CLIENT_RECORD: dict[str, Any] = {
    "name": "",
    "phone": None,
    "address": None,
    "bank": None,
    "vat": None,
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _profile_path(user_id: int | str) -> Path:
    return DATA_DIR / f"{user_id}.json"


def _load(user_id: int | str) -> dict[str, Any] | None:
    path = _profile_path(user_id)
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _save(user_id: int | str, data: dict[str, Any]) -> None:
    path = _profile_path(user_id)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)


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
    return _profile_path(user_id).exists()


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
) -> dict[str, Any]:
    """Create and persist a new profile.  Raises FileExistsError if one
    already exists (callers should call has_profile() first).

    `email` and `vat_number` are optional; pass "" (or omit) when the
    user skipped them.
    `currency` is the user's chosen default invoice currency.
    `language` is the user's chosen UI language ("en" | "ru").
    """
    if has_profile(user_id):
        raise FileExistsError(f"Profile for {user_id} already exists")

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
        "saved_clients": [],
        "invoices": [],
    }
    _save(user_id, data)
    return data


def get_profile(user_id: int | str) -> dict[str, Any] | None:
    """Return the profile dict, or None if the user has no profile.

    Missing keys (from older profile versions) are filled in with
    defaults so callers can always rely on the full schema.

    Bug 3 — Legacy saved_clients entries written as plain strings are
    converted in-memory to the canonical dict shape on every read. The
    migration is non-persistent (no write side-effect from this read);
    the next save_client call naturally writes the normalized form.
    """
    data = _load(user_id)
    if data is None:
        return None

    # Forward-compat defaults for keys added after initial release.
    data.setdefault("last_invoice_number", 0)
    data.setdefault("currency", CURRENCY_DEFAULT)
    data.setdefault("language", "en")
    data.setdefault("saved_clients", [])
    data.setdefault("email", "")
    data.setdefault("vat_number", "")
    data.setdefault("invoices", [])

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

    new_number = int(data.get("last_receipt_number", 0)) + 1
    data["last_receipt_number"] = new_number
    _save(user_id, data)
    return new_number
