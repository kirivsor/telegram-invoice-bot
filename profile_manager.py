"""Profile manager for the Telegram Invoice Bot.

Handles all JSON read/write/save logic for profiles.json. This is the
only module that touches the on-disk profile store.

Profile data model (one entry per Telegram user, keyed by user_id as
a string):

    {
        "org_name": str,
        "phone": str,
        "iban": str,
        "reference_style": str,        # "Standard" or "None"
        "currency": str,               # always "EUR"
        "last_invoice_number": int,
        "created_at": str,             # ISO datetime
        "updated_at": str,             # ISO datetime
        "logo_path": str | None,       # optional, future feature
    }

All writes are atomic (temp file + os.replace). If profiles.json is
unreadable, it is renamed aside as profiles.json.corrupted.<timestamp>
and a fresh, empty profiles.json is created in its place.
"""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILES_PATH = Path("profiles.json")
CURRENCY_DEFAULT = "EUR"


# ─── Internal helpers ───────────────────────────────────────────────────────

def _now_iso() -> str:
    """Current local time as an ISO 8601 string."""
    return datetime.now().isoformat()


def _quarantine_corrupted_file() -> None:
    """Move the unreadable profiles file aside for forensic recovery."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = PROFILES_PATH.parent / f"{PROFILES_PATH.name}.corrupted.{timestamp}"
    try:
        PROFILES_PATH.rename(target)
        logger.error("Corrupted profiles file moved to %s", target)
    except OSError:
        logger.exception(
            "Failed to rename corrupted profiles file %s", PROFILES_PATH
        )


# ─── Bulk read / write ──────────────────────────────────────────────────────

def load_profiles() -> dict[str, dict[str, Any]]:
    """Load and return all profiles as a dict keyed by user_id string.

    Returns an empty dict if the file is missing. If the file exists
    but cannot be parsed (or is not a JSON object), the bad file is
    quarantined, a fresh empty profiles.json is created, and an empty
    dict is returned.
    """
    if not PROFILES_PATH.exists():
        return {}

    try:
        with PROFILES_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.exception(
            "Could not read %s; quarantining and starting fresh",
            PROFILES_PATH,
        )
        _quarantine_corrupted_file()
        save_profiles({})
        return {}

    if not isinstance(data, dict):
        logger.error(
            "%s did not contain a JSON object; quarantining and starting "
            "fresh",
            PROFILES_PATH,
        )
        _quarantine_corrupted_file()
        save_profiles({})
        return {}

    return data


def save_profiles(profiles: dict[str, dict[str, Any]]) -> None:
    """Persist all profiles atomically.

    Writes to a temp file in the same directory, fsyncs, then
    os.replace()s it over profiles.json so a partial write cannot
    corrupt the real file.
    """
    fd, tmp_path = tempfile.mkstemp(
        prefix=".profiles.",
        suffix=".tmp",
        dir=str(PROFILES_PATH.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(profiles, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, PROFILES_PATH)
    except OSError:
        # Tidy up the temp file if the atomic replace didn't happen.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ─── Per-user operations ────────────────────────────────────────────────────

def get_profile(user_id: int | str) -> dict[str, Any] | None:
    """Return user_id's profile, or None if no such profile exists."""
    return load_profiles().get(str(user_id))


def has_profile(user_id: int | str) -> bool:
    """True iff a profile exists for user_id."""
    return str(user_id) in load_profiles()


def create_profile(
    user_id: int | str,
    *,
    org_name: str,
    phone: str,
    iban: str,
    reference_style: str,
    logo_path: str | None = None,
) -> dict[str, Any]:
    """Create and persist a new profile for user_id; return the record.

    Overwrites any existing profile for the same user_id; callers that
    care should check has_profile() first.
    """
    now = _now_iso()
    profile: dict[str, Any] = {
        "org_name": org_name,
        "phone": phone,
        "iban": iban,
        "reference_style": reference_style,
        "currency": CURRENCY_DEFAULT,
        "last_invoice_number": 0,
        "created_at": now,
        "updated_at": now,
        "logo_path": logo_path,
    }

    profiles = load_profiles()
    profiles[str(user_id)] = profile
    save_profiles(profiles)
    return profile


def update_profile(user_id: int | str, **fields: Any) -> dict[str, Any]:
    """Update one or more fields on user_id's profile and persist.

    Refreshes updated_at automatically. Raises KeyError if the profile
    does not exist.
    """
    profiles = load_profiles()
    key = str(user_id)
    if key not in profiles:
        raise KeyError(f"No profile for user_id={user_id}")

    profile = profiles[key]
    profile.update(fields)
    profile["updated_at"] = _now_iso()
    save_profiles(profiles)
    return profile


def increment_invoice_number(user_id: int | str) -> int:
    """Bump user_id's last_invoice_number by one; return the new value.

    Persists immediately. Raises KeyError if the profile does not exist.
    """
    profiles = load_profiles()
    key = str(user_id)
    if key not in profiles:
        raise KeyError(f"No profile for user_id={user_id}")

    profile = profiles[key]
    next_number = int(profile.get("last_invoice_number", 0)) + 1
    profile["last_invoice_number"] = next_number
    profile["updated_at"] = _now_iso()
    save_profiles(profiles)
    return next_number
