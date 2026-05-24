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
save_client(user_id, client_name) -> None
get_saved_clients(user_id)       -> list[str]
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
    "iban": str,
    "reference_style": str,            # "Standard" | "None"
    "last_invoice_number": int,
    "currency": str,                   # ISO 4217 code, e.g. "EUR"
    "saved_clients": list[str],        # up to 3 recently saved client names
}

CURRENCY_DEFAULT = "EUR"

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
) -> dict[str, Any]:
    """Create and persist a new profile.  Raises FileExistsError if one
    already exists (callers should call has_profile() first).

    `email` is optional; pass "" (or omit) when the user skipped it.
    """
    if has_profile(user_id):
        raise FileExistsError(f"Profile for {user_id} already exists")

    data: dict[str, Any] = {
        "user_id": int(user_id),
        "org_name": org_name,
        "phone": phone,
        "email": (email or "").strip(),
        "iban": iban,
        "reference_style": reference_style,
        "last_invoice_number": 0,
        "currency": CURRENCY_DEFAULT,
        "saved_clients": [],
    }
    _save(user_id, data)
    return data


def get_profile(user_id: int | str) -> dict[str, Any] | None:
    """Return the profile dict, or None if the user has no profile.

    Missing keys (from older profile versions) are filled in with
    defaults so callers can always rely on the full schema.
    """
    data = _load(user_id)
    if data is None:
        return None

    # Forward-compat defaults for keys added after initial release.
    data.setdefault("last_invoice_number", 0)
    data.setdefault("currency", CURRENCY_DEFAULT)
    data.setdefault("saved_clients", [])
    data.setdefault("email", "")
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


def save_client(user_id: int | str, client_name: str) -> None:
    """Append client_name to the user's saved_clients list (max 3 entries).

    Rules:
    - client_name is stripped of leading/trailing whitespace.
    - If the stripped name is already present (case-insensitive), it is
      not added again.
    - The list is capped at 3 entries; if adding would exceed 3, the
      oldest entry (index 0) is dropped first.
    - No-op if the profile does not exist.
    """
    profile = get_profile(user_id)
    if profile is None:
        return

    name = client_name.strip()
    if not name:
        return

    saved: list[str] = list(profile.get("saved_clients") or [])

    # Case-insensitive duplicate check.
    name_lower = name.lower()
    if any(s.lower() == name_lower for s in saved):
        return

    saved.append(name)

    # Cap at 3 — drop the oldest when over the limit.
    while len(saved) > 3:
        saved.pop(0)

    update_profile(user_id, saved_clients=saved)


def get_saved_clients(user_id: int | str) -> list[str]:
    """Return the saved_clients list for user_id, or [] if missing/no profile."""
    profile = get_profile(user_id)
    if profile is None:
        return []
    return list(profile.get("saved_clients") or [])
