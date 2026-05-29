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


def _fmt_rate(rate: float | int) -> str:
    """Render a VAT percentage without a trailing .0 (21.0 -> '21', 5.5 -> '5.5')."""
    try:
        r = float(rate)
    except (TypeError, ValueError):
        return "0"
    return f"{r:g}"

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
CAL_FLOW_QUOTE_DATE = "qte"
CAL_FLOW_QUOTE_VALID = "qvu"

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
    lang: str = "en",
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
        lang: UI language ("en" | "ru"). Used for the Cancel button label.
        min_date, max_date: clamp range.  Days outside this range render
            as non-tappable dots; navigation buttons that would scroll
            past the bounds emit a noop callback (the handler surfaces
            a toast).

    A bad ``flow`` is coerced to the invoice-date flow rather than
    raised, so a typo in caller code can never produce a render-time
    crash.
    """
    if flow not in (CAL_FLOW_INVOICE_DATE, CAL_FLOW_DUE_DATE,
                    CAL_FLOW_QUOTE_DATE, CAL_FLOW_QUOTE_VALID):
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
            strings.get_string("BTN_CANCEL", lang),
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


def profile_edit_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Reply keyboard for choosing which profile field to edit."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_EDIT_ORG", lang)),
                KeyboardButton(strings.get_string("BTN_EDIT_PHONE", lang)),
            ],
            [
                KeyboardButton(strings.get_string("BTN_EDIT_EMAIL", lang)),
                KeyboardButton(strings.get_string("BTN_EDIT_VAT", lang)),
            ],
            [
                KeyboardButton(strings.get_string("BTN_EDIT_ACCOUNT", lang)),
                KeyboardButton(strings.get_string("BTN_EDIT_REFERENCES", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_EDIT_VAT_RATE", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
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


def track_invoices_list_keyboard(
    has_unpaid: bool, lang: str = "en"
) -> InlineKeyboardMarkup:
    """Inline keyboard shown beneath the invoice-tracking list."""
    rows: list[list[InlineKeyboardButton]] = []
    if has_unpaid:
        rows.append(
            [InlineKeyboardButton(
                strings.get_string("BTN_TRACK_MARK_PAID", lang),
                callback_data=CB_TRACK_MARK_PAID_MENU,
            )]
        )
    rows.append(
        [InlineKeyboardButton("\u2705 Done", callback_data=CB_TRACK_CLOSE)]
    )
    return InlineKeyboardMarkup(rows)


def track_invoices_mark_paid_keyboard(
    unpaid: list[dict], lang: str = "en",
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
            strings.get_string("BTN_TRACK_BACK", lang),
            callback_data=CB_TRACK_BACK_TO_LIST,
        )]
    )
    return InlineKeyboardMarkup(rows)


# =============================================================================
# === MAIN MENU — REPLY =======================================================
# =============================================================================


def main_menu_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_CREATE_INVOICE", lang)),
                KeyboardButton(strings.get_string("BTN_CREATE_QUOTE", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CREATE_RECEIPT", lang))],
            [
                KeyboardButton(strings.get_string("BTN_TRACK_INVOICES", lang)),
                KeyboardButton(strings.get_string("BTN_MY_QUOTES", lang)),
            ],
            [
                KeyboardButton(strings.get_string("BTN_EDIT_PROFILE", lang)),
                KeyboardButton(strings.get_string("BTN_HELP", lang)),
            ],
        ],
        resize_keyboard=True,
    )

# =============================================================================
# === ONBOARDING — REPLY ======================================================
# =============================================================================


def onboarding_references_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_REF_STANDARD", lang))],
            [KeyboardButton(strings.get_string("BTN_REF_NONE", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def vat_rate_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Keyboard for the default-VAT-rate step (onboarding + profile edit).

    Single 'Skip / 0%' button (sets the rate to 0) plus Cancel. The user
    can instead type a number like 21 or 5.5.
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_VAT_RATE_SKIP", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def email_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Keyboard shown while asking for the optional email.

    Single Skip button. The user can either type an email or tap Skip
    to leave the field empty. The same keyboard is reused on profile
    editing — tapping Skip there *clears* the email.
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.get_string("BTN_SKIP_EMAIL", lang))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def vat_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Keyboard shown while asking for the optional VAT number.

    Mirrors email_keyboard — single Skip button. Reused for both
    onboarding and profile editing (where Skip clears the value).
    """
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.get_string("BTN_SKIP_VAT", lang))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Keyboard shown while asking for a phone number.

    Includes a `request_contact=True` button so the user can share
    their Telegram-registered phone in one tap, plus a Cancel button
    for the normal escape behaviour. Used by both the onboarding phone
    step and the profile-edit phone step.
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(
                strings.get_string("BTN_SHARE_CONTACT", lang),
                request_contact=True,
            )],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# =============================================================================
# === INVOICE FLOW — REPLY ====================================================
# =============================================================================


def invoice_client_keyboard(
    saved_clients: list[str] | list[dict] | None = None,
    lang: str = "en",
) -> ReplyKeyboardMarkup:
    """Build the keyboard shown when asking for a client name.

    Bug 3 — saved_clients is now a list[dict] (with keys name/phone/
    address/bank/vat). Legacy list[str] is still accepted for safety.
    Only the name is shown on the button; the rest is auto-loaded by
    handlers.invoice_client when the button is tapped.
    """
    rows = [[KeyboardButton(strings.get_string("BTN_NO_NAME", lang))]]

    names: list[str] = []
    for entry in (saved_clients or [])[:3]:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            if name:
                names.append(name)
        elif isinstance(entry, str):
            name = entry.strip()
            if name:
                names.append(name)

    for name in names:
        rows.append([KeyboardButton(name)])

    rows.append([KeyboardButton(strings.get_string("BTN_CANCEL", lang))])
    return ReplyKeyboardMarkup(
        rows,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def client_details_choice_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Yes/No keyboard shown right after the client name is captured.

    Used to decide whether to enter the optional client-details sub-flow.
    """
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_ADD_CLIENT_DETAILS", lang)),
                KeyboardButton(strings.get_string("BTN_SKIP_CLIENT_DETAILS", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def client_detail_skip_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Skip + Cancel keyboard reused for every optional client-detail step
    (phone / address / bank / VAT).
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_SKIP_DETAIL", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def save_client_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_SAVE_CLIENT", lang))],
            [KeyboardButton(strings.get_string("BTN_SKIP_SAVE", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_date_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_TODAY", lang)),
                KeyboardButton(strings.get_string("BTN_YESTERDAY", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_PICK_DATE", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_item_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.get_string("BTN_CANCEL", lang))]],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard(
    currency: str = "EUR", lang: str = "en", vat_rate: float = 0.0,
) -> ReplyKeyboardMarkup:
    change_currency_label = (
        f"{strings.get_string('BTN_CHANGE_CURRENCY', lang)} ({currency})"
    )
    vat_label = (
        f"{strings.get_string('BTN_SET_VAT', lang)} ({_fmt_rate(vat_rate)}%)"
    )
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_ADD_ANOTHER", lang))],
            [KeyboardButton(strings.get_string("BTN_CREATE_INVOICE_CONFIRM", lang))],
            [
                KeyboardButton(strings.get_string("BTN_DUE_DATE", lang)),
                KeyboardButton(vat_label),
            ],
            [
                KeyboardButton(change_currency_label),
                KeyboardButton(strings.get_string("BTN_SAVE_CLIENT", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard_saved(
    currency: str = "EUR", lang: str = "en", vat_rate: float = 0.0,
) -> ReplyKeyboardMarkup:
    change_currency_label = (
        f"{strings.get_string('BTN_CHANGE_CURRENCY', lang)} ({currency})"
    )
    vat_label = (
        f"{strings.get_string('BTN_SET_VAT', lang)} ({_fmt_rate(vat_rate)}%)"
    )
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_ADD_ANOTHER", lang))],
            [KeyboardButton(strings.get_string("BTN_CREATE_INVOICE_CONFIRM", lang))],
            [
                KeyboardButton(strings.get_string("BTN_DUE_DATE", lang)),
                KeyboardButton(vat_label),
            ],
            [
                KeyboardButton(change_currency_label),
                KeyboardButton(strings.get_string("CLIENT_SAVED_INLINE", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
    )


def currency_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_CURRENCY_EUR", lang)),
                KeyboardButton(strings.get_string("BTN_CURRENCY_USD", lang)),
            ],
            [
                KeyboardButton(strings.get_string("BTN_CURRENCY_KZT", lang)),
                KeyboardButton(strings.get_string("BTN_CURRENCY_OTHER", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def currency_picker_keyboard(
    for_onboarding: bool = False, lang: str = "en",
) -> ReplyKeyboardMarkup:
    """Currency picker keyboard.

    Reused by two flows:
        - invoice flow: shown when changing per-invoice currency.
          Bottom row is BTN_BACK so the user can return to the invoice
          summary without choosing.
        - onboarding (for_onboarding=True): bottom row is BTN_CANCEL,
          matching the rest of the onboarding flow's escape behavior.
    """
    last_row = (
        [KeyboardButton(strings.get_string("BTN_CANCEL", lang))]
        if for_onboarding
        else [KeyboardButton(strings.get_string("BTN_BACK", lang))]
    )
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_CURRENCY_EUR", lang)),
                KeyboardButton(strings.get_string("BTN_CURRENCY_USD", lang)),
            ],
            [
                KeyboardButton(strings.get_string("BTN_CURRENCY_RUB", lang)),
                KeyboardButton(strings.get_string("BTN_CURRENCY_KZT", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CURRENCY_OTHER", lang))],
            last_row,
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def invoice_after_pdf_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_CREATE_ANOTHER", lang))],
            [KeyboardButton(strings.get_string("BTN_ALL_DONE", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def due_date_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Keyboard shown when the user taps 'Set due date' in the invoice flow."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_DUE_NET30", lang)),
                KeyboardButton(strings.get_string("BTN_DUE_NET15", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_DUE_ON_RECEIPT", lang))],
            [KeyboardButton(strings.get_string("BTN_DUE_CUSTOM", lang))],
            [KeyboardButton(strings.get_string("BTN_BACK", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def track_invoices_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Reply keyboard shown beneath the invoice tracking list."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_MARK_AS_PAID", lang))],
            [KeyboardButton(strings.get_string("BTN_BACK_TO_MENU", lang))],
        ],
        resize_keyboard=True,
    )


def language_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Language picker shown once at onboarding (Feature 2)."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_LANG_EN", lang))],
            [KeyboardButton(strings.get_string("BTN_LANG_RU", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Backward-compatibility aliases for handlers.py
# ---------------------------------------------------------------------------

CALNS = CAL_NS
CALFLOWINVOICEDATE = CAL_FLOW_INVOICE_DATE
CALFLOWDUEDATE = CAL_FLOW_DUE_DATE
CALACTIONDAY = CAL_ACTION_DAY
CALACTIONPREV = CAL_ACTION_PREV
CALACTIONNEXT = CAL_ACTION_NEXT
CALACTIONNOOP = CAL_ACTION_NOOP
CALACTIONCANCEL = CAL_ACTION_CANCEL

calendarkeyboard = calendar_keyboard
mainmenukeyboard = main_menu_keyboard
onboardingreferenceskeyboard = onboarding_references_keyboard
emailkeyboard = email_keyboard
vatkeyboard = vat_keyboard
phonekeyboard = phone_keyboard
invoiceclientkeyboard = invoice_client_keyboard
clientdetailschoicekeyboard = client_details_choice_keyboard
clientdetailskipkeyboard = client_detail_skip_keyboard
saveclientkeyboard = save_client_keyboard
invoicedatekeyboard = invoice_date_keyboard
invoiceitemkeyboard = invoice_item_keyboard
invoiceafteritemkeyboard = invoice_after_item_keyboard
invoiceafteritemkeyboardsaved = invoice_after_item_keyboard_saved
currencykeyboard = currency_keyboard
currencypickerkeyboard = currency_picker_keyboard
invoiceafterpdfkeyboard = invoice_after_pdf_keyboard
duedatekeyboard = due_date_keyboard
trackinvoiceskeyboard = track_invoices_keyboard
profileeditkeyboard = profile_edit_keyboard
languagekeyboard = language_keyboard

# =============================================================================
# === RECEIPTS — REPLY + INLINE ===============================================
# =============================================================================

# Payment-method callback wire format (Feature 2):
#   markpaid:<number>        -> tapped an unpaid invoice (now opens method picker)
#   paymethod:<key>:<number> -> chose a method for invoice <number>
#   paymethod:other:<number> -> chose "Other" (bot then asks for free text)
CB_PAYMETHOD = "paymethod"            # appended :<key>:<number>
CB_TRACK_VIEW_PAID = "trackpaid:view"
CB_TRACK_VIEW_OPEN = "trackpaid:open"

# Canonical (callback_key -> strings.py constant) map. Single source of truth
# so handlers and keyboards never drift. "other" is handled specially.
PAYMENT_METHODS = [
    ("bank_transfer", "PM_BANK_TRANSFER"),
    ("credit_card", "PM_CREDIT_CARD"),
    ("cash", "PM_CASH"),
    ("paypal", "PM_PAYPAL"),
    ("stripe", "PM_STRIPE"),
    ("other", "PM_OTHER"),
]


def payment_method_inline_keyboard(
    invoice_number: int, lang: str = "en"
) -> InlineKeyboardMarkup:
    """Feature 2 — inline payment-method picker shown after tapping an
    unpaid invoice. callback_data = paymethod:<key>:<invoice_number>."""
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for key, str_key in PAYMENT_METHODS:
        pair.append(
            InlineKeyboardButton(
                strings.get_string(str_key, lang),
                callback_data=f"{CB_PAYMETHOD}:{key}:{invoice_number}",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append([
        InlineKeyboardButton(
            strings.get_string("BTN_BACK_TO_MENU", lang),
            callback_data="markpaid:cancel",
        )
    ])
    return InlineKeyboardMarkup(rows)


def payment_method_reply_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Feature 1 — reply-keyboard payment-method picker for the standalone
    receipt flow."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("PM_BANK_TRANSFER", lang)),
                KeyboardButton(strings.get_string("PM_CREDIT_CARD", lang)),
            ],
            [
                KeyboardButton(strings.get_string("PM_CASH", lang)),
                KeyboardButton(strings.get_string("PM_PAYPAL", lang)),
            ],
            [
                KeyboardButton(strings.get_string("PM_STRIPE", lang)),
                KeyboardButton(strings.get_string("PM_OTHER", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def receipt_bill_to_keyboard(
    saved_clients: list[dict] | None = None, lang: str = "en"
) -> ReplyKeyboardMarkup:
    """Pick a saved client or type a name (mirrors invoice_client_keyboard)."""
    rows: list[list[KeyboardButton]] = []
    for entry in (saved_clients or [])[:3]:
        name = (entry.get("name") if isinstance(entry, dict) else str(entry)).strip()
        if name:
            rows.append([KeyboardButton(name)])
    rows.append([KeyboardButton(strings.get_string("BTN_CANCEL", lang))])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


def receipt_skip_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Skip + Cancel for every optional receipt field."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_RCP_SKIP", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def receipt_date_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Today / Yesterday / Cancel — reuses existing date string constants."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_TODAY", lang)),
                KeyboardButton(strings.get_string("BTN_YESTERDAY", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def receipt_after_item_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_RCP_ADD_ANOTHER", lang))],
            [KeyboardButton(strings.get_string("BTN_RCP_DONE_ITEMS", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
    )


def receipt_amount_paid_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_RCP_FULL_TOTAL", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def track_open_list_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Feature 3 — reply keyboard under the (now open-only) tracking list."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_MARK_AS_PAID", lang))],
            [KeyboardButton(strings.get_string("BTN_VIEW_PAID", lang))],
            [KeyboardButton(strings.get_string("BTN_BACK_TO_MENU", lang))],
        ],
        resize_keyboard=True,
    )

# =============================================================================
# === QUOTES (Goal 1) =========================================================
# =============================================================================

# Per-quote inline action callbacks. Wire format:
#   quote:view:<number>      open a quote's action menu
#   quote:send:<number>      (re)generate + send the quote PDF
#   quote:convert:<number>   convert to invoice
#   quote:accept:<number>    mark as accepted
#   quote:delete:<number>    delete the quote
#   quote:list               back to the quotes list
CB_QUOTE_VIEW = "quote:view"
CB_QUOTE_SEND = "quote:send"
CB_QUOTE_CONVERT = "quote:convert"
CB_QUOTE_ACCEPT = "quote:accept"
CB_QUOTE_DELETE = "quote:delete"
CB_QUOTE_EDIT = "quote:edit"
CB_QUOTE_LIST = "quote:list"


def quote_date_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Today / Yesterday / Pick a date — mirrors invoice_date_keyboard."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_TODAY", lang)),
                KeyboardButton(strings.get_string("BTN_YESTERDAY", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_PICK_DATE", lang))],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def quote_item_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(strings.get_string("BTN_CANCEL", lang))]],
        resize_keyboard=True,
    )


def quote_after_item_keyboard(
    currency: str = "EUR", lang: str = "en", vat_rate: float = 0.0,
    client_saved: bool = False,
) -> ReplyKeyboardMarkup:
    """'What's next' keyboard for the quote flow (parallels the invoice one)."""
    change_currency_label = (
        f"{strings.get_string('BTN_CHANGE_CURRENCY', lang)} ({currency})"
    )
    vat_label = f"{strings.get_string('BTN_SET_VAT', lang)} ({_fmt_rate(vat_rate)}%)"
    save_label = (
        strings.get_string("CLIENT_SAVED_INLINE", lang)
        if client_saved
        else strings.get_string("BTN_SAVE_CLIENT", lang)
    )
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.get_string("BTN_ADD_ANOTHER", lang))],
            [KeyboardButton(strings.get_string("BTN_CREATE_QUOTE_CONFIRM", lang))],
            [
                KeyboardButton(strings.get_string("BTN_QUOTE_SET_VALID", lang)),
                KeyboardButton(vat_label),
            ],
            [
                KeyboardButton(change_currency_label),
                KeyboardButton(save_label),
            ],
            [KeyboardButton(strings.get_string("BTN_CANCEL", lang))],
        ],
        resize_keyboard=True,
    )


def quote_valid_until_keyboard(lang: str = "en") -> ReplyKeyboardMarkup:
    """Valid-until picker shown in the quote flow."""
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.get_string("BTN_QUOTE_VALID_14", lang)),
                KeyboardButton(strings.get_string("BTN_QUOTE_VALID_30", lang)),
            ],
            [KeyboardButton(strings.get_string("BTN_QUOTE_VALID_60", lang))],
            [KeyboardButton(strings.get_string("BTN_QUOTE_NO_VALID", lang))],
            [KeyboardButton(strings.get_string("BTN_QUOTE_VALID_CUSTOM", lang))],
            [KeyboardButton(strings.get_string("BTN_BACK", lang))],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def quotes_list_keyboard(
    quotes: list[dict], lang: str = "en",
) -> InlineKeyboardMarkup:
    """Inline list of quotes; each row opens that quote's action menu."""
    rows: list[list[InlineKeyboardButton]] = []
    for q in quotes:
        number = int(q.get("number", 0))
        client = (q.get("client_name") or "\u2014").strip() or "\u2014"
        if len(client) > 18:
            client = client[:17].rstrip() + "\u2026"
        currency = (q.get("currency") or "EUR").upper()
        amount = float(q.get("amount", 0))
        status = str(q.get("status", "Pending"))
        label = f"Q-{number:04d} \u00b7 {client} \u00b7 {amount:,.2f} {currency} \u00b7 {status}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"{CB_QUOTE_VIEW}:{number}")])
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("\u2014", callback_data=CB_QUOTE_LIST)]])


def quote_view_keyboard(
    number: int, status: str, lang: str = "en",
) -> InlineKeyboardMarkup:
    """Per-quote action menu. The Convert button is hidden once the quote
    has already been converted (terminal state)."""
    converted = str(status) == "Converted"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_SEND", lang),
            callback_data=f"{CB_QUOTE_SEND}:{number}")],
    ]
    if not converted:
        rows.append([InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_CONVERT", lang),
            callback_data=f"{CB_QUOTE_CONVERT}:{number}")])
        rows.append([InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_MARK_ACCEPTED", lang),
            callback_data=f"{CB_QUOTE_ACCEPT}:{number}")])
        rows.append([InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_EDIT", lang),
            callback_data=f"{CB_QUOTE_EDIT}:{number}")])
    rows.append([
        InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_DELETE", lang),
            callback_data=f"{CB_QUOTE_DELETE}:{number}"),
    ])
    rows.append([
        InlineKeyboardButton(
            strings.get_string("BTN_QUOTE_BACK", lang),
            callback_data=CB_QUOTE_LIST),
    ])
    return InlineKeyboardMarkup(rows)
