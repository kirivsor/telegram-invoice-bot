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

CB_CAL_DAY = "cal:day"
CB_CAL_PREV = "cal:prev"
CB_CAL_NEXT = "cal:next"
CB_CAL_IGNORE = "cal:ignore"
CB_CAL_CANCEL = "cal:cancel"

_WEEKDAY_HEADERS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def calendar_keyboard(
    year: int,
    month: int,
    min_date: date | None = None,
    max_date: date | None = None,
) -> InlineKeyboardMarkup:
    today = date.today()
    if min_date is None:
        m = today.month - 3
        y = today.year
        if m < 1:
            m += 12
            y -= 1
        try:
            min_date = today.replace(year=y, month=m)
        except ValueError:
            import calendar as _cal
            min_date = today.replace(year=y, month=m, day=_cal.monthrange(y, m)[1])
    if max_date is None:
        m = today.month + 3
        y = today.year
        if m > 12:
            m -= 12
            y += 1
        try:
            max_date = today.replace(year=y, month=m)
        except ValueError:
            import calendar as _cal
            max_date = today.replace(year=y, month=m, day=_cal.monthrange(y, m)[1])

    month_name = date(year, month, 1).strftime("%B %Y")
    header = [
        InlineKeyboardButton("\u2039", callback_data=f"{CB_CAL_PREV}:{year}:{month}"),
        InlineKeyboardButton(month_name, callback_data=CB_CAL_IGNORE),
        InlineKeyboardButton("\u203a", callback_data=f"{CB_CAL_NEXT}:{year}:{month}"),
    ]

    weekdays = [
        InlineKeyboardButton(d, callback_data=CB_CAL_IGNORE)
        for d in _WEEKDAY_HEADERS
    ]

    first_weekday, total_days = monthrange(year, month)
    day_buttons: list[InlineKeyboardButton] = []

    for _ in range(first_weekday):
        day_buttons.append(
            InlineKeyboardButton(" ", callback_data=CB_CAL_IGNORE)
        )

    for day in range(1, total_days + 1):
        d = date(year, month, day)
        if min_date <= d <= max_date:
            label = str(day)
            cb = f"{CB_CAL_DAY}:{year}:{month}:{day}"
        else:
            label = "\u00b7"
            cb = CB_CAL_IGNORE
        day_buttons.append(InlineKeyboardButton(label, callback_data=cb))

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(day_buttons), 7):
        rows.append(day_buttons[i : i + 7])

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
CB_EDIT_EMAIL = "edit:email"
CB_EDIT_VAT = "edit:vat"
CB_EDIT_ACCOUNT = "edit:account"
CB_EDIT_REFERENCES = "edit:references"
CB_EDIT_DONE = "edit:done"
CB_UPLOAD_LOGO = "edit:logo"  # reserved for future logo-upload flow


def profile_edit_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard shown alongside the profile summary."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("\U0001f3e2 Name", callback_data=CB_EDIT_NAME),
                InlineKeyboardButton("\U0001f4de Phone", callback_data=CB_EDIT_PHONE),
            ],
            [
                InlineKeyboardButton("\u2709\ufe0f Email", callback_data=CB_EDIT_EMAIL),
                InlineKeyboardButton("\U0001f3db\ufe0f VAT", callback_data=CB_EDIT_VAT),
            ],
            [
                InlineKeyboardButton("\U0001f3e6 Account", callback_data=CB_EDIT_ACCOUNT),
                InlineKeyboardButton(
                    "\U0001f522 References", callback_data=CB_EDIT_REFERENCES
                ),
            ],
            [
                InlineKeyboardButton(
                    "\u2705 Done", callback_data=CB_EDIT_DONE
                )
            ],
        ]
    )


# =============================================================================
# === INVOICE TRACKING — INLINE ===============================================
# =============================================================================

CB_TRACK_MARK_PAID_MENU = "trackinv:markpaid"
CB_TRACK_MARK_PAID_ITEM = "trackinv:pay"     # appended with :NUMBER
CB_TRACK_BACK_TO_LIST = "trackinv:back"
CB_TRACK_CLOSE = "trackinv:close"


def track_invoices_list_keyboard(has_unpaid: bool) -> InlineKeyboardMarkup:
    """Inline keyboard shown beneath the invoice-tracking list."""
    rows: list[list[InlineKeyboardButton]] = []
    if has_unpaid:
        rows.append(
            [InlineKeyboardButton(
                strings.BTN_TRACK_MARK_PAID,
                callback_data=CB_TRACK_MARK_PAID_MENU,
            )]
        )
    rows.append(
        [InlineKeyboardButton("\u2705 Done", callback_data=CB_TRACK_CLOSE)]
    )
    return InlineKeyboardMarkup(rows)


def track_invoices_mark_paid_keyboard(
    unpaid: list[dict],
) -> InlineKeyboardMarkup:
    """Inline keyboard listing each unpaid invoice as a tappable row.

    Each row's callback_data is `trackinv:pay:<number>`.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for inv in unpaid:
        number = int(inv.get("number", 0))
        recipient = (inv.get("client_name") or "\u2014").strip() or "\u2014"
        # Truncate label so it fits comfortably in a Telegram button.
        if len(recipient) > 22:
            recipient = recipient[:21].rstrip() + "\u2026"
        currency = (inv.get("currency") or "EUR").upper()
        amount = float(inv.get("amount", 0))
        label = f"INV-{number:05d} \u2014 {recipient} \u2014 {amount:,.2f} {currency}"
        rows.append(
            [InlineKeyboardButton(
                label,
                callback_data=f"{CB_TRACK_MARK_PAID_ITEM}:{number}",
            )]
        )
    rows.append(
        [InlineKeyboardButton(
            strings.BTN_TRACK_BACK, callback_data=CB_TRACK_BACK_TO_LIST,
        )]
    )
    return InlineKeyboardMarkup(rows)


# =============================================================================
# === MAIN MENU — REPLY =======================================================
# =============================================================================


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CREATE_INVOICE)],
            [KeyboardButton(strings.BTN_TRACK_INVOICES)],
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
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_REF_STANDARD)],
            [KeyboardButton(strings.BTN_REF_NONE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def email_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown while asking for the optional email.

    Single Skip button. The user can either type an email or tap Skip
    to leave the field empty. The same keyboard is reused on profile
    editing — tapping Skip there *clears* the email.
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.BTN_SKIP_EMAIL)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def vat_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown while asking for the optional VAT number.

    Mirrors email_keyboard — single Skip button. Reused for both
    onboarding and profile editing (where Skip clears the value).
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.BTN_SKIP_VAT)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# =============================================================================
# === INVOICE FLOW — REPLY ====================================================
# =============================================================================


def invoice_client_keyboard(saved_clients: list[str] | None = None) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(strings.BTN_NO_NAME)]]
    for name in (saved_clients or [])[:3]:
        rows.append([KeyboardButton(name)])
    rows.append([KeyboardButton(strings.BTN_CANCEL)])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def client_details_choice_keyboard() -> ReplyKeyboardMarkup:
    """Yes/No keyboard shown right after the client name is captured.

    Used to decide whether to enter the optional client-details sub-flow.
    """
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.BTN_ADD_CLIENT_DETAILS),
                KeyboardButton(strings.BTN_SKIP_CLIENT_DETAILS),
            ],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def client_detail_skip_keyboard() -> ReplyKeyboardMarkup:
    """Skip + Cancel keyboard reused for every optional client-detail step
    (phone / address / bank / VAT).
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_SKIP_DETAIL)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def save_client_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_SAVE_CLIENT)],
            [KeyboardButton(strings.BTN_SKIP_SAVE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_date_keyboard() -> ReplyKeyboardMarkup:
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
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.BTN_CANCEL)]],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard(currency: str = "EUR") -> ReplyKeyboardMarkup:
    change_currency_label = f"{strings.BTN_CHANGE_CURRENCY} ({currency})"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_ADD_ANOTHER)],
            [KeyboardButton(strings.BTN_CREATE_INVOICE_CONFIRM)],
            [KeyboardButton(strings.BTN_DUE_DATE)],
            [KeyboardButton(change_currency_label), KeyboardButton(strings.BTN_SAVE_CLIENT)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard_saved(currency: str = "EUR") -> ReplyKeyboardMarkup:
    change_currency_label = f"{strings.BTN_CHANGE_CURRENCY} ({currency})"
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_ADD_ANOTHER)],
            [KeyboardButton(strings.BTN_CREATE_INVOICE_CONFIRM)],
            [KeyboardButton(strings.BTN_DUE_DATE)],
            [KeyboardButton(change_currency_label), KeyboardButton(strings.CLIENT_SAVED_INLINE)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def currency_keyboard() -> ReplyKeyboardMarkup:
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


def currency_picker_keyboard() -> ReplyKeyboardMarkup:
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
            [KeyboardButton(strings.BTN_BACK)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_after_pdf_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CREATE_ANOTHER)],
            [KeyboardButton(strings.BTN_ALL_DONE)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )

def due_date_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard shown when the user taps 'Set due date' in the invoice flow."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_DUE_NET30), KeyboardButton(strings.BTN_DUE_NET15)],
            [KeyboardButton(strings.BTN_DUE_ON_RECEIPT)],
            [KeyboardButton(strings.BTN_DUE_CUSTOM)],
            [KeyboardButton(strings.BTN_BACK)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def track_invoices_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard shown beneath the invoice tracking list."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_MARK_AS_PAID)],
            [KeyboardButton(strings.BTN_BACK_TO_MENU)],
        ],
        resize_keyboard=True,
    )
