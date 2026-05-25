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
#
# Wire format for calendar callback_data:
#
#     cal:<flow>:<action>[:<args>]
#
#   flow:
#     inv  — invoice issue date
#     due  — invoice due date
#
#   action / args:
#     day:   <year>:<month>:<day>
#     prev:  <year>:<month>      (the month *currently* displayed)
#     next:  <year>:<month>
#     noop:  (no args)
#     cancel:(no args)
#
# Embedding the flow in every payload means the handler can dispatch
# correctly even if Telegram delivers a callback whose target state no
# longer matches the user's actual conversation state.

CAL_NS = "cal"

CAL_FLOW_INVOICE_DATE = "inv"
CAL_FLOW_DUE_DATE = "due"

CAL_ACTION_DAY = "day"
CAL_ACTION_PREV = "prev"
CAL_ACTION_NEXT = "next"
CAL_ACTION_NOOP = "noop"
CAL_ACTION_CANCEL = "cancel"

# Backward-compat aliases.  Existing imports keep working; new code
# should reference CAL_NS + CAL_ACTION_* directly.
CB_CAL_DAY = f"{CAL_NS}:{CAL_ACTION_DAY}"
CB_CAL_PREV = f"{CAL_NS}:{CAL_ACTION_PREV}"
CB_CAL_NEXT = f"{CAL_NS}:{CAL_ACTION_NEXT}"
CB_CAL_IGNORE = f"{CAL_NS}:{CAL_ACTION_NOOP}"
CB_CAL_CANCEL = f"{CAL_NS}:{CAL_ACTION_CANCEL}"

_WEEKDAY_HEADERS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def _cal_cb(flow: str, action: str, *args: int) -> str:
    """Build a calendar callback_data string with the canonical layout."""
    parts = [CAL_NS, flow, action, *(str(a) for a in args)]
    return ":".join(parts)


def calendar_keyboard(
    year: int,
    month: int,
    *,
    flow: str,
    min_date: date | None = None,
    max_date: date | None = None,
) -> InlineKeyboardMarkup:
    """Build the inline calendar keyboard for *year*/*month*.

    Args:
        year, month: month to render.
        flow: one of ``CAL_FLOW_INVOICE_DATE`` or ``CAL_FLOW_DUE_DATE``.
            Embedded into every emitted callback_data so the handler can
            dispatch correctly even when conversation state is ambiguous
            or stale.
        min_date, max_date: clamp range.  Days outside this range render
            as non-tappable dots; navigation buttons that would scroll
            past the bounds emit a noop callback (the handler surfaces
            a toast).

    A bad ``flow`` is coerced to the invoice-date flow rather than
    raised, so a typo in caller code can never produce a render-time
    crash.
    """
    if flow not in (CAL_FLOW_INVOICE_DATE, CAL_FLOW_DUE_DATE):
        flow = CAL_FLOW_INVOICE_DATE

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
            min_date = today.replace(year=y, month=m, day=monthrange(y, m)[1])
    if max_date is None:
        m = today.month + 3
        y = today.year
        if m > 12:
            m -= 12
            y += 1
        try:
            max_date = today.replace(year=y, month=m)
        except ValueError:
            max_date = today.replace(year=y, month=m, day=monthrange(y, m)[1])

    noop = _cal_cb(flow, CAL_ACTION_NOOP)

    month_name = date(year, month, 1).strftime("%B %Y")
    header = [
        InlineKeyboardButton(
            "\u2039",
            callback_data=_cal_cb(flow, CAL_ACTION_PREV, year, month),
        ),
        InlineKeyboardButton(month_name, callback_data=noop),
        InlineKeyboardButton(
            "\u203a",
            callback_data=_cal_cb(flow, CAL_ACTION_NEXT, year, month),
        ),
    ]

    weekdays = [
        InlineKeyboardButton(d, callback_data=noop)
        for d in _WEEKDAY_HEADERS
    ]

    first_weekday, total_days = monthrange(year, month)
    day_buttons: list[InlineKeyboardButton] = []

    for _ in range(first_weekday):
        day_buttons.append(InlineKeyboardButton(" ", callback_data=noop))

    for day in range(1, total_days + 1):
        d = date(year, month, day)
        if min_date <= d <= max_date:
            label = str(day)
            cb = _cal_cb(flow, CAL_ACTION_DAY, year, month, day)
        else:
            label = "\u00b7"
            cb = noop
        day_buttons.append(InlineKeyboardButton(label, callback_data=cb))

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(day_buttons), 7):
        rows.append(day_buttons[i : i + 7])

    cancel_row = [
        InlineKeyboardButton(
            strings.BTN_CANCEL,
            callback_data=_cal_cb(flow, CAL_ACTION_CANCEL),
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


def profile_edit_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard for choosing which profile field to edit."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_EDIT_ORG), KeyboardButton(strings.BTN_EDIT_PHONE)],
            [KeyboardButton(strings.BTN_EDIT_EMAIL), KeyboardButton(strings.BTN_EDIT_VAT)],
            [KeyboardButton(strings.BTN_EDIT_ACCOUNT), KeyboardButton(strings.BTN_EDIT_REFERENCES)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
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
