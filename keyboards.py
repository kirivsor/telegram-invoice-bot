"""Keyboard builder functions for the Telegram Invoice Bot.

Every function here returns either a ReplyKeyboardMarkup (for the main
conversational flows) or an InlineKeyboardMarkup (for profile editing
and the calendar picker). All button labels come from strings.py.

Callback-data tokens for inline keyboards are defined at the top of
this module so handlers.py can match against them without duplicating
the literal strings.
"""

import calendar as _calendar

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import strings


# ─── Callback-data tokens for inline keyboards ──────────────────────────────
# These are the callback_data strings emitted by the inline keyboards
# below. handlers.py will match against them. Compound tokens append
# additional ':'-separated fields (year, month, day).

CB_EDIT_NAME = "edit:name"
CB_EDIT_PHONE = "edit:phone"
CB_EDIT_ACCOUNT = "edit:account"
CB_EDIT_REFERENCES = "edit:references"
CB_EDIT_DONE = "edit:done"

CB_CAL_PREV = "cal:prev"        # full form: cal:prev:{year}:{month}
CB_CAL_NEXT = "cal:next"        # full form: cal:next:{year}:{month}
CB_CAL_DAY = "cal:day"          # full form: cal:day:{year}:{month}:{day}
CB_CAL_IGNORE = "cal:ignore"    # non-interactive cells (headers, blanks)
CB_CAL_CANCEL = "cal:cancel"    # cancel button inside the calendar


# ─── Reply keyboards ─────────────────────────────────────────────────────────

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu shown after onboarding and between actions.

    Layout:
        Row 1: [🧾 Create invoice]
        Row 2: [✏️ Edit profile] [❓ Help]
    """
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


def onboarding_references_keyboard() -> ReplyKeyboardMarkup:
    """Reference-section choice during onboarding (step 5).

    Layout:
        Row 1: [Standard Form] [None needed]
    """
    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(strings.BTN_REF_STANDARD),
                KeyboardButton(strings.BTN_REF_NONE),
            ],
        ],
        resize_keyboard=True,
    )


def invoice_client_keyboard() -> ReplyKeyboardMarkup:
    """Shown when asking for the invoice's client name.

    Layout:
        Row 1: [⛔️ No name]
        Row 2: [❌ Cancel]
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_NO_NAME)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def invoice_date_keyboard() -> ReplyKeyboardMarkup:
    """Shown when asking for the invoice date.

    Layout:
        Row 1: [📅 Today] [📅 Yesterday]
        Row 2: [📆 Pick a date]
        Row 3: [❌ Cancel]
    """
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
    )


def invoice_item_keyboard() -> ReplyKeyboardMarkup:
    """Shown while the user is entering item name / price.

    Layout:
        Row 1: [❌ Cancel]
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def invoice_after_item_keyboard() -> ReplyKeyboardMarkup:
    """Shown after a line item has been added.

    Layout:
        Row 1: [➕ Add another]
        Row 2: [✅ Create invoice]
        Row 3: [❌ Cancel]
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_ADD_ANOTHER)],
            [KeyboardButton(strings.BTN_CREATE_INVOICE_CONFIRM)],
            [KeyboardButton(strings.BTN_CANCEL)],
        ],
        resize_keyboard=True,
    )


def invoice_after_pdf_keyboard() -> ReplyKeyboardMarkup:
    """Shown after the PDF has been delivered to the user.

    Layout:
        Row 1: [🧾 Create another]
        Row 2: [✅ All done]
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(strings.BTN_CREATE_ANOTHER)],
            [KeyboardButton(strings.BTN_ALL_DONE)],
        ],
        resize_keyboard=True,
    )


# ─── Inline keyboards ────────────────────────────────────────────────────────

def profile_edit_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard shown on the profile-edit screen.

    Layout:
        Row 1: [✏️ Name]    [✏️ Phone]
        Row 2: [✏️ Account] [✏️ References]
        Row 3: [✅ Done]
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    strings.BTN_EDIT_NAME, callback_data=CB_EDIT_NAME
                ),
                InlineKeyboardButton(
                    strings.BTN_EDIT_PHONE, callback_data=CB_EDIT_PHONE
                ),
            ],
            [
                InlineKeyboardButton(
                    strings.BTN_EDIT_ACCOUNT, callback_data=CB_EDIT_ACCOUNT
                ),
                InlineKeyboardButton(
                    strings.BTN_EDIT_REFERENCES,
                    callback_data=CB_EDIT_REFERENCES,
                ),
            ],
            [
                InlineKeyboardButton(
                    strings.BTN_DONE, callback_data=CB_EDIT_DONE
                ),
            ],
        ]
    )


def calendar_keyboard(year: int, month: int) -> InlineKeyboardMarkup:
    """Inline date-picker keyboard for the given year/month.

    Layout:
        Row 1:    [◀️] [Month Year] [▶️]
        Row 2:    Mon Tue Wed Thu Fri Sat Sun   (non-interactive)
        Rows 3+:  date-number buttons (blanks rendered as space)
        Last:     [❌ Cancel]

    Callback-data formats:
        cal:prev:{year}:{month}        navigate to previous month
        cal:next:{year}:{month}        navigate to next month
        cal:day:{year}:{month}:{day}   user picked a day
        cal:ignore                     non-interactive cell
        cal:cancel                     user pressed Cancel
    """
    month_name = _calendar.month_name[month]

    # Navigation row
    nav_row = [
        InlineKeyboardButton(
            "◀️", callback_data=f"{CB_CAL_PREV}:{year}:{month}"
        ),
        InlineKeyboardButton(
            f"{month_name} {year}", callback_data=CB_CAL_IGNORE
        ),
        InlineKeyboardButton(
            "▶️", callback_data=f"{CB_CAL_NEXT}:{year}:{month}"
        ),
    ]

    # Day-of-week header row (non-interactive)
    dow_row = [
        InlineKeyboardButton(label, callback_data=CB_CAL_IGNORE)
        for label in strings.DOW_HEADERS
    ]

    # Date grid (Monday-first)
    cal = _calendar.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)

    rows: list[list[InlineKeyboardButton]] = [nav_row, dow_row]
    for week in weeks:
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(
                    InlineKeyboardButton(" ", callback_data=CB_CAL_IGNORE)
                )
            else:
                row.append(
                    InlineKeyboardButton(
                        str(day),
                        callback_data=f"{CB_CAL_DAY}:{year}:{month}:{day}",
                    )
                )
        rows.append(row)

    # Cancel row
    rows.append(
        [InlineKeyboardButton(strings.BTN_CANCEL, callback_data=CB_CAL_CANCEL)]
    )

    return InlineKeyboardMarkup(rows)
