"""All reply- and inline-keyboard builders for the Telegram Invoice Bot.

Keeping every keyboard here keeps handlers.py free of layout logic.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import strings

# =============================================================================
# === INLINE CALENDAR =========================================================
# =============================================================================

# Callback-data prefixes / sentinel values.
CB_CAL_DAY = "cal:day"
CB_CAL_PREV = "cal:prev"
CB_CAL_NEXT = "cal:next"
CB_CAL_IGNORE = "cal:ignore"
CB_CAL_CANCEL = "cal:cancel"

_WEEKDAY_HEADERS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _twelve_months_ago(today: date) -> date:
    """Return the date exactly 12 calendar months before *today*."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:  # Feb 29 edge case
        return today.replace(year=today.year - 1, day=28)


def calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Build an inline calendar for the given month.

    Days outside the allowed range (last 12 months .. today) are shown
    as "·" and carry the ignore callback so they are inert.
    """
    today = date.today()
    earliest = _twelve_months_ago(today)

    # ── Header row: ‹ MONTH YEAR › ──────────────────────────────────────
    month_name = date(year, month, 1).strftime("%B %Y")
    header = [
        InlineKeyboardButton("‹", callback_data=f"{CB_CAL_PREV}:{year}:{month}"),
        InlineKeyboardButton(month_name, callback_data=CB_CAL_IGNORE),
        InlineKeyboardButton("›", callback_data=f"{CB_CAL_NEXT}:{year}:{month}"),
    ]

    # ── Weekday label row ───────────────────────────────────────────────
    weekdays = [
        InlineKeyboardButton(d, callback_data=CB_CAL_IGNORE)
        for d in _WEEKDAY_HEADERS
    ]

    # ── Day rows ─────────────────────────────────────────────────────────
    first_weekday, total_days = monthrange(year, month)
    # first_weekday: 0=Mon … 6=Sun
    day_buttons: list[InlineKeyboardButton] = []

    # Blank cells before the 1st
    for _ in range(first_weekday):
        day_buttons.append(
            InlineKeyboardButton(" ", callback_data=CB_CAL_IGNORE)
        )

    for day in range(1, total_days + 1):
        d = date(year, month, day)
        if earliest <= d <= today:
            label = str(day)
            cb = f"{CB_CAL_DAY}:{year}:{month}:{day}"
        else:
            label = "·"
            cb = CB_CAL_IGNORE
        day_buttons.append(InlineKeyboardButton(label, callback_data=cb))

    # Split into rows of 7
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(day_buttons), 7):
        rows.append(day_buttons[i : i + 7])

    # ── Cancel row ───────────────────────────────────────────────────────
    cancel_row = [
        InlineKeyboardButton(
            strings.BTN_CANCEL, callback_data=CB_CAL_CANCEL
        )
    ]

    return InlineKeyboardMarkup([header, weekdays, *rows, cancel_row])


# =============================================================================
# === PROFILE EDITING — INLINE ================================================
# =============================================================================

CB_EDIT_NAME = "edit:name"
CB_EDIT_PHONE = "edit:phone"
CB_EDIT_ACCOUNT = "edit:account"
CB_EDIT_REFERENCES = "edit:references"
CB_EDIT_DONE = "edit:done"
CB_UPLOAD_LOGO = "edit:logo"  # reserved for future logo-upload flow


def profile_edit_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard shown alongside the profile summary."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🏢 Name", callback_data=CB_EDIT_NAME),
                InlineKeyboardButton("📞 Phone", callback_data=CB_EDIT_PHONE),
            ],
            [
                InlineKeyboardButton(
                    "🏦 Account", callback_data=CB_EDIT_ACCOUNT
                ),
                InlineKeyboardButton(
                    "🔢 References", callback_data=CB_EDIT_REFERENCES
                ),
            ],
            [
                InlineKeyboardButton(
                    "✅ Done", callback_data=CB_EDIT_DONE
                )
            ],
        ]
    )


# =============================================================================
# === MAIN MENU — REPLY =======================================================
# =============================================================================


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent main-menu keyboard (shown after onboarding / all-done)."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CREATE_INVOICE)],
            [
                KeyboardButton(strings.BTN_EDIT_PROFILE),
                KeyboardButton(strings.BTN_HELP),
            ],
        ],
        resize_keyboard=True,
    )


# =============================================================================
# === ONBOARDING — REPLY ======================================================
# =============================================================================


def onboarding_references_keyboard() -> ReplyKeyboardMarkup:
    """Two-button keyboard for choosing the invoice reference style."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_REF_STANDARD)],
            [KeyboardButton(strings.BTN_REF_NONE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# =============================================================================
# === INVOICE FLOW — REPLY ====================================================
# =============================================================================


def invoice_client_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard for the client-name step (offers 'No name' shortcut)."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_NO_NAME)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def save_client_keyboard() -> ReplyKeyboardMarkup:
    """Two-button keyboard offered after PDF delivery when a client name
    was used, asking whether to save it for future autofill."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_SAVE_CLIENT)],
            [KeyboardButton(strings.BTN_SKIP_SAVE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def saved_clients_keyboard(saved_clients: list[str]) -> ReplyKeyboardMarkup:
    """One button per saved client name (each in its own row), with a
    final row containing the BTN_NO_NAME shortcut.

    Used in invoice_start_entry when the user has saved clients.
    """
    rows = [[KeyboardButton(name)] for name in saved_clients]
    rows.append([KeyboardButton(strings.BTN_NO_NAME)])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
    )


def invoice_date_keyboard() -> ReplyKeyboardMarkup:
    """Date-selection keyboard: Today / Yesterday / Pick a date / Cancel."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.BTN_TODAY),
                KeyboardButton(strings.BTN_YESTERDAY),
            ],
            [KeyboardButton(strings.BTN_PICK_DATE)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_item_keyboard() -> ReplyKeyboardMarkup:
    """Generic keyboard shown during item-name and item-price steps."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown after adding an item (add more / create invoice)."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_ADD_ANOTHER)],
            [KeyboardButton(strings.BTN_CREATE_INVOICE_CONFIRM)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def currency_keyboard() -> ReplyKeyboardMarkup:
    """Currency-selection keyboard."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.BTN_CURRENCY_EUR),
                KeyboardButton(strings.BTN_CURRENCY_USD),
            ],
            [
                KeyboardButton(strings.BTN_CURRENCY_KZT),
                KeyboardButton(strings.BTN_CURRENCY_OTHER),
            ],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_after_pdf_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown after the PDF is delivered."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CREATE_ANOTHER)],
            [KeyboardButton(strings.BTN_ALL_DONE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
