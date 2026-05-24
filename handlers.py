"""ConversationHandler flow logic for the Telegram Invoice Bot.

Onboarding, invoice creation, profile editing, and the
/start /cancel /help command handlers all live in this module.
Persistence, PDF generation, keyboards, and user-facing strings live
in their respective frozen modules and are imported, never re-defined.

Public entry point used by main.py:
    register_handlers(application)
"""

from __future__ import annotations

import functools
import logging
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from telegram import ForceReply, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import keyboards
import pdf_generator
import profile_manager
import strings

logger = logging.getLogger(__name__)


# =============================================================================
# === STATES ==================================================================
# =============================================================================
# Three separate integer ranges so the groups never collide in log output.

# --- ONBOARDING group ---
ONBOARD_ORG = 100
ONBOARD_PHONE = 101
ONBOARD_ACCOUNT = 102
ONBOARD_REFERENCES = 103

# --- INVOICE group ---
INV_CLIENT = 200
INV_DATE = 201
INV_CALENDAR = 202
INV_ITEM_NAME = 203
INV_ITEM_PRICE = 204
INV_ADD_MORE = 205
INV_AFTER_PDF = 206
# 207 reserved for a future flow step.
INV_CURRENCY = 208            # picking from the currency keyboard
INV_CURRENCY_CUSTOM = 209     # typing a free-form currency code

# --- PROFILE_EDIT group ---
PE_MENU = 300
PE_NAME = 301
PE_PHONE = 302
PE_ACCOUNT = 303
PE_REFERENCES = 304


# =============================================================================
# === HELPERS =================================================================
# =============================================================================

def _handler_safe(func):
    """Wrap a handler so any uncaught exception is logged and a friendly
    message is sent to the user; the conversation is then ended."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception:
            logger.exception("Unhandled error in handler %s", func.__name__)
            try:
                chat = update.effective_chat if update else None
                user = update.effective_user if update else None
                if chat is not None:
                    has_prof = bool(
                        user is not None
                        and profile_manager.has_profile(user.id)
                    )
                    reply_markup = (
                        keyboards.main_menu_keyboard()
                        if has_prof
                        else ReplyKeyboardRemove()
                    )
                    await chat.send_message(
                        strings.RESTARTED, reply_markup=reply_markup
                    )
            except Exception:
                logger.exception("Failed sending error message to user")
            return ConversationHandler.END

    return wrapper


def _exact(text: str) -> str:
    """Regex matching exactly `text` (used for reply-keyboard buttons)."""
    return f"^{re.escape(text)}$"


# ─── Currency rendering (chat-side) ──────────────────────────────────────────
# Same lookup table semantics as pdf_generator._format_money: recognised
# symbol → "<sym>amount"; otherwise "<CODE> amount". Mirrored here so the
# in-chat invoice summary always matches the PDF.
_CURRENCY_SYMBOLS = {
    "EUR": "€",
    "USD": "$",
    "KZT": "₸",   # rendered fine in chat (UTF-8); PDF uses code fallback.
}


def _format_money(amount: float | int, currency: str = "EUR") -> str:
    """Format an amount with the given currency for chat messages."""
    code = (currency or "EUR").upper()
    symbol = _CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{code} {amount:,.2f}"


# Maps a currency reply-keyboard button label to its ISO code.
_CURRENCY_BUTTON_CODES = {
    strings.BTN_CURRENCY_EUR: "EUR",
    strings.BTN_CURRENCY_USD: "USD",
    strings.BTN_CURRENCY_KZT: "KZT",
}


def _twelve_months_ago(today: date) -> date:
    """Return the date 12 calendar months before today (Feb-29-safe)."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def _is_valid_invoice_date(d: date) -> bool:
    """Allowed range: last 12 months up to and including today."""
    today = date.today()
    return _twelve_months_ago(today) <= d <= today


_CURRENCY_TOKENS = ("€", "$", "£", "₸", "₽", "EUR", "USD", "GBP", "KZT", "RUB")


def _parse_price(text: str) -> int:
    """Parse a price string into a positive integer.

    Raises ValueError with a code in args[0]:
        "decimal"        → user gave a non-integer number
        "zero_negative"  → user gave 0 or a negative
        "not_number"     → unparseable
    """
    cleaned = text.strip()
    for sym in _CURRENCY_TOKENS:
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        raise ValueError("not_number")
    if "." in cleaned or "," in cleaned:
        raise ValueError("decimal")
    if cleaned.startswith("-"):
        raise ValueError("zero_negative")
    if not cleaned.isdigit():
        raise ValueError("not_number")
    value = int(cleaned)
    if value <= 0:
        raise ValueError("zero_negative")
    return value


def _format_invoice_summary(
    items: list[dict[str, Any]], currency: str = "EUR"
) -> str:
    """Render the running invoice summary block (header + lines + total).

    Spec edge case 11: after 20 items, show only the last 15 with a marker.
    """
    lines: list[str] = [strings.CURRENT_INVOICE_HEADER, ""]
    display_items = items
    if len(items) > 20:
        display_items = items[-15:]
        lines.append(f"[Showing last 15 items of {len(items)}]")
        lines.append("")
    for item in display_items:
        lines.append(f"{item['name']} — {_format_money(item['price'], currency)}")
    total = sum(int(item["price"]) for item in items)
    lines.append("")
    lines.append(f"{strings.TOTAL_LABEL} {_format_money(total, currency)}")
    return "\n".join(lines)


def _render_profile_summary(profile: dict[str, Any]) -> str:
    """Render a profile block for both the post-onboarding confirmation
    and the profile-edit screen."""
    return (
        f"{strings.PROFILE_HEADER}\n"
        f"{strings.ORGANIZATION_LABEL} {profile.get('org_name', '')}\n"
        f"{strings.PHONE_LABEL} {profile.get('phone', '')}\n"
        f"{strings.ACCOUNT_LABEL} {profile.get('iban', '')}\n"
        f"{strings.REFERENCES_LABEL} {profile.get('reference_style', '')}"
    )


def _label_word(label: str) -> str:
    """'Organization:' → 'Organization' (for FIELD_UPDATED interpolation)."""
    return label.rstrip(":").strip()


def _new_invoice_draft() -> dict[str, Any]:
    return {
        "client_name": None,
        "date": None,
        "items": [],
        "pending_item_name": None,
        "currency": "EUR",  # overwritten by INV_CURRENCY before PDF generation
    }


# =============================================================================
# === ONBOARDING FLOW =========================================================
# =============================================================================

@_handler_safe
async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/start — onboarding entry point or main menu for returning users."""
    user_id = update.effective_user.id

    if profile_manager.has_profile(user_id):
        profile = profile_manager.get_profile(user_id) or {}
        await update.message.reply_text(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    context.user_data["onboarding"] = {}
    await update.message.reply_text(
        f"{strings.WELCOME}\n\n{strings.PROFILE_INTRO}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(strings.ASK_ORG)
    return ONBOARD_ORG


@_handler_safe
async def onboard_org(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Onboarding step 2 — receive organization name."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return ONBOARD_ORG

    text = msg.text
    stripped = text.strip()
    if not stripped:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_ORG
    if len(text) < 2:
        await msg.reply_text(strings.ERR_SHORT_TEXT)
        return ONBOARD_ORG
    if len(text) > 100:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=100))
        return ONBOARD_ORG

    context.user_data.setdefault("onboarding", {})["org_name"] = stripped
    await msg.reply_text(strings.ASK_PHONE)
    return ONBOARD_PHONE


@_handler_safe
async def onboard_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Onboarding step 3 — receive phone number."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_PHONE)
        return ONBOARD_PHONE

    text = msg.text
    if len(text) < 3 or len(text) > 30:
        await msg.reply_text(strings.ERR_INVALID_PHONE)
        return ONBOARD_PHONE

    context.user_data.setdefault("onboarding", {})["phone"] = text
    await msg.reply_text(strings.ASK_ACCOUNT)
    return ONBOARD_ACCOUNT


@_handler_safe
async def onboard_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Onboarding step 4 — receive bank account / IBAN."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_ACCOUNT)
        return ONBOARD_ACCOUNT

    text = msg.text.strip()
    if len(text) < 5 or len(text) > 40:
        await msg.reply_text(strings.ERR_INVALID_ACCOUNT)
        return ONBOARD_ACCOUNT

    context.user_data.setdefault("onboarding", {})["iban"] = text
    await msg.reply_text(
        strings.ASK_REFERENCES,
        reply_markup=keyboards.onboarding_references_keyboard(),
    )
    return ONBOARD_REFERENCES


@_handler_safe
async def onboard_references(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Onboarding step 5 — receive reference choice and persist the profile."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.onboarding_references_keyboard(),
            )
        return ONBOARD_REFERENCES

    text = msg.text.strip()
    if text == strings.BTN_REF_STANDARD:
        reference_style = "Standard"
    elif text == strings.BTN_REF_NONE:
        reference_style = "None"
    else:
        await msg.reply_text(
            strings.ERR_WRONG_BUTTON,
            reply_markup=keyboards.onboarding_references_keyboard(),
        )
        return ONBOARD_REFERENCES

    draft = context.user_data.get("onboarding", {})
    user_id = update.effective_user.id

    try:
        profile_manager.create_profile(
            user_id,
            org_name=draft["org_name"],
            phone=draft["phone"],
            iban=draft["iban"],
            reference_style=reference_style,
        )
    except (KeyError, OSError):
        logger.exception(
            "Failed to persist new profile for user_id=%s", user_id
        )
        await msg.reply_text(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        context.user_data.pop("onboarding", None)
        return ConversationHandler.END

    confirmation = (
        f"{strings.PROFILE_CREATED_HEADER}\n\n"
        f"{strings.PROFILE_DETAILS_LABEL}\n"
        f"{strings.ORGANIZATION_LABEL} {draft['org_name']}\n"
        f"{strings.PHONE_LABEL} {draft['phone']}\n"
        f"{strings.ACCOUNT_LABEL} {draft['iban']}\n"
        f"{strings.REFERENCES_LABEL} {reference_style}\n\n"
        f"{strings.EDIT_HINT}"
    )
    await msg.reply_text(
        confirmation, reply_markup=keyboards.main_menu_keyboard()
    )
    context.user_data.pop("onboarding", None)
    return ConversationHandler.END


@_handler_safe
async def onboard_cancel_or_restart(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Fallback for /cancel and /start while mid-onboarding.

    Per spec Flow 5 (and edge case 1), the user must complete the
    profile to use the bot — so we restart at step 1.
    """
    context.user_data["onboarding"] = {}
    await update.message.reply_text(
        strings.MID_FLOW_RESTART_PROMPT,
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(strings.ASK_ORG)
    return ONBOARD_ORG


# =============================================================================
# === INVOICE FLOW ============================================================
# =============================================================================

@_handler_safe
async def invoice_start_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice entry point — initialise draft, seed default currency silently,
    then ask for the client name.
    """
    user_id = update.effective_user.id
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    profile = profile_manager.get_profile(user_id) or {}
    default_currency = str(
        profile.get("currency") or profile_manager.CURRENCY_DEFAULT
    ).strip().upper() or profile_manager.CURRENCY_DEFAULT

    context.user_data["invoice"] = _new_invoice_draft()
    context.user_data["invoice"]["currency"] = default_currency

    saved_clients = profile_manager.get_saved_clients(user_id)
    await update.message.reply_text(
        strings.ASK_CLIENT,
        reply_markup=keyboards.invoice_client_keyboard(saved_clients=saved_clients),
    )
    return INV_CLIENT


# Backwards-compatible alias.
invoice_start = invoice_start_entry


async def _ask_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send the client-name prompt and move into INV_CLIENT."""
    user_id = update.effective_user.id
    saved_clients = profile_manager.get_saved_clients(user_id)
    chat = update.effective_chat
    await chat.send_message(
        strings.ASK_CLIENT,
        reply_markup=keyboards.invoice_client_keyboard(saved_clients=saved_clients),
    )
    return INV_CLIENT


async def _generate_and_send_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Generate the invoice PDF, deliver it to the user, persist the currency
    default, then show the after-PDF menu.
    """
    chat = update.effective_chat
    user_id = update.effective_user.id
    draft = context.user_data.get("invoice", {})
    items = draft.get("items", [])

    if not items:
        await chat.send_message(
            "Please add at least one item.",
            reply_markup=keyboards.invoice_item_keyboard(),
        )
        return INV_ITEM_NAME

    profile = profile_manager.get_profile(user_id)
    if not profile:
        await chat.send_message(strings.ERR_PDF_FAILURE)
        context.user_data.pop("invoice", None)
        await chat.send_message(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    status_msg = await chat.send_message(strings.GENERATING_PDF)

    next_number = int(profile.get("last_invoice_number", 0)) + 1
    invoice_date_value: date = draft["date"]
    client_name = draft.get("client_name")
    currency = str(draft.get("currency") or "EUR").upper()

    try:
        pdf_path: Path = pdf_generator.generate_invoice_pdf(
            invoice_number=next_number,
            invoice_date=invoice_date_value,
            client_name=client_name,
            items=items,
            profile=profile,
            currency=currency,
        )
    except Exception:
        logger.exception("PDF generation failed for user_id=%s", user_id)
        try:
            await status_msg.delete()
        except Exception:
            pass
        await chat.send_message(
            strings.ERR_PDF_FAILURE,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        context.user_data.pop("invoice", None)
        return ConversationHandler.END

    try:
        committed_number = profile_manager.increment_invoice_number(user_id)
    except Exception:
        logger.exception(
            "Counter increment failed after successful PDF for user_id=%s",
            user_id,
        )
        committed_number = next_number

    try:
        await status_msg.delete()
    except Exception:
        pass

    caption = (
        f"{strings.INVOICE_DONE.format(number=f'{committed_number:05d}')}\n\n"
        f"{strings.STORAGE_HINT}"
    )

    try:
        with pdf_path.open("rb") as fh:
            await chat.send_document(
                document=fh,
                filename=pdf_path.name,
                caption=caption,
            )
    except Exception:
        logger.exception("Failed to deliver PDF to user_id=%s", user_id)
        await chat.send_message(
            strings.ERR_PDF_FAILURE,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        context.user_data.pop("invoice", None)
        return ConversationHandler.END

    try:
        profile_manager.update_default_currency(user_id, currency)
    except Exception:
        logger.exception(
            "Could not persist default currency=%s for user_id=%s",
            currency, user_id,
        )

    context.user_data.pop("invoice", None)
    await chat.send_message(
        strings.WHATS_NEXT_PROMPT,
        reply_markup=keyboards.invoice_after_pdf_keyboard(),
    )
    return INV_AFTER_PDF


@_handler_safe
async def invoice_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice — pick a currency from the reply keyboard.

    After storing the new currency code the user is returned to
    INV_ADD_MORE with a refreshed invoice summary and updated keyboard.
    """
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.currency_picker_keyboard(),
            )
        return INV_CURRENCY

    text = msg.text.strip()

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    # Back — return to the What's next menu without changing currency.
    if text == strings.BTN_BACK:
        currency = context.user_data["invoice"].get("currency", "EUR")
        items = context.user_data["invoice"].get("items", [])
        summary = _format_invoice_summary(items, currency)
        await msg.reply_text(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=keyboards.invoice_after_item_keyboard(currency=currency),
        )
        return INV_ADD_MORE

    if text == strings.BTN_CURRENCY_OTHER:
        await msg.reply_text(
            strings.ASK_CURRENCY_CUSTOM,
            reply_markup=ForceReply(selective=True),
        )
        return INV_CURRENCY_CUSTOM

    code = _CURRENCY_BUTTON_CODES.get(text)
    if code is None:
        await msg.reply_text(
            strings.ERR_WRONG_BUTTON,
            reply_markup=keyboards.currency_picker_keyboard(),
        )
        return INV_CURRENCY

    # Store the new currency and return to What's next.
    context.user_data["invoice"]["currency"] = code
    items = context.user_data["invoice"].get("items", [])
    summary = _format_invoice_summary(items, code)
    await msg.reply_text(
        f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=keyboards.invoice_after_item_keyboard(currency=code),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_currency_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice — receive a free-form 2-4 letter currency code."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_CURRENCY)
        return INV_CURRENCY_CUSTOM

    text = msg.text.strip().upper()
    if text == strings.BTN_CANCEL.upper():
        return await invoice_cancel(update, context)

    if not (2 <= len(text) <= 4) or not text.isalpha():
        await msg.reply_text(strings.ERR_INVALID_CURRENCY)
        return INV_CURRENCY_CUSTOM

    # Store the custom currency and return to What's next.
    context.user_data["invoice"]["currency"] = text
    items = context.user_data["invoice"].get("items", [])
    summary = _format_invoice_summary(items, text)
    await msg.reply_text(
        f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=keyboards.invoice_after_item_keyboard(currency=text),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 1 — receive client name (or 'No name')."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return INV_CLIENT

    text = msg.text

    if text.strip() == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text.strip() == strings.BTN_NO_NAME:
        context.user_data["invoice"]["client_name"] = None
        await msg.reply_text(
            strings.ASK_DATE,
            reply_markup=keyboards.invoice_date_keyboard(),
        )
        return INV_DATE

    stripped = text.strip()
    if not stripped:
        await msg.reply_text(strings.ERR_EMPTY)
        return INV_CLIENT
    if len(text) < 2:
        await msg.reply_text(strings.ERR_SHORT_TEXT)
        return INV_CLIENT
    if len(text) > 100:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=100))
        return INV_CLIENT

    context.user_data["invoice"]["client_name"] = stripped
    await msg.reply_text(
        strings.ASK_DATE,
        reply_markup=keyboards.invoice_date_keyboard(),
    )
    return INV_DATE


@_handler_safe
async def invoice_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 2 — Today / Yesterday / Pick a date."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.invoice_date_keyboard(),
            )
        return INV_DATE

    text = msg.text.strip()
    today = date.today()

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_TODAY:
        context.user_data["invoice"]["date"] = today
        return await _ask_item_name(update, context)

    if text == strings.BTN_YESTERDAY:
        context.user_data["invoice"]["date"] = today - timedelta(days=1)
        return await _ask_item_name(update, context)

    if text == strings.BTN_PICK_DATE:
        await msg.reply_text(
            strings.CALENDAR_PROMPT,
            reply_markup=keyboards.calendar_keyboard(today.year, today.month),
        )
        return INV_CALENDAR

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.invoice_date_keyboard(),
    )
    return INV_DATE


@_handler_safe
async def invoice_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 2b — handle every inline-calendar callback."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    action = ":".join(parts[:2])

    today = date.today()
    twelve_back = _twelve_months_ago(today)

    if data == keyboards.CB_CAL_IGNORE:
        return INV_CALENDAR

    if data == keyboards.CB_CAL_CANCEL:
        return await _invoice_cancel_from_callback(update, context)

    if action == keyboards.CB_CAL_PREV and len(parts) >= 4:
        year, month = int(parts[2]), int(parts[3])
        new_month, new_year = month - 1, year
        if new_month < 1:
            new_month, new_year = 12, year - 1
        if new_month == 12:
            last_of_new = date(new_year + 1, 1, 1) - timedelta(days=1)
        else:
            last_of_new = date(new_year, new_month + 1, 1) - timedelta(days=1)
        if last_of_new < twelve_back:
            return INV_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(new_year, new_month)
        )
        return INV_CALENDAR

    if action == keyboards.CB_CAL_NEXT and len(parts) >= 4:
        year, month = int(parts[2]), int(parts[3])
        new_month, new_year = month + 1, year
        if new_month > 12:
            new_month, new_year = 1, year + 1
        if date(new_year, new_month, 1) > today:
            return INV_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(new_year, new_month)
        )
        return INV_CALENDAR

    if action == keyboards.CB_CAL_DAY and len(parts) >= 5:
        year, month, day = int(parts[2]), int(parts[3]), int(parts[4])
        try:
            selected = date(year, month, day)
        except ValueError:
            return INV_CALENDAR
        if not _is_valid_invoice_date(selected):
            return INV_CALENDAR
        context.user_data["invoice"]["date"] = selected
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        return await _ask_item_name(update, context)

    return INV_CALENDAR


@_handler_safe
async def invoice_calendar_text_fallback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Catch text typed while the inline calendar is on screen."""
    msg = update.message
    text = (msg.text or "").strip() if msg else ""
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)
    if msg is not None:
        await msg.reply_text(strings.ERR_WRONG_BUTTON)
    return INV_CALENDAR


async def _ask_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send the item-name prompt and move into INV_ITEM_NAME."""
    chat = update.effective_chat
    await chat.send_message(
        strings.ASK_ITEM_NAME,
        reply_markup=keyboards.invoice_item_keyboard(),
    )
    return INV_ITEM_NAME


@_handler_safe
async def invoice_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 3 — receive an item name."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return INV_ITEM_NAME

    text = msg.text
    stripped = text.strip()

    if stripped == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if not stripped:
        await msg.reply_text(strings.ERR_EMPTY)
        return INV_ITEM_NAME
    if len(text) < 2:
        await msg.reply_text(strings.ERR_SHORT_TEXT)
        return INV_ITEM_NAME
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return INV_ITEM_NAME

    context.user_data["invoice"]["pending_item_name"] = stripped
    await msg.reply_text(
        strings.ASK_ITEM_PRICE.format(item_name=stripped),
        reply_markup=keyboards.invoice_item_keyboard(),
    )
    return INV_ITEM_PRICE


@_handler_safe
async def invoice_item_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 4 — receive item price; append item; show summary."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_PRICE)
        return INV_ITEM_PRICE

    text = msg.text
    if text.strip() == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    try:
        price = _parse_price(msg.text)
    except ValueError as exc:
        code = exc.args[0] if exc.args else "not_number"
        if code == "decimal":
            await msg.reply_text(strings.ERR_DECIMAL_PRICE)
        elif code == "zero_negative":
            await msg.reply_text(strings.ERR_ZERO_NEGATIVE_PRICE)
        else:
            await msg.reply_text(strings.ERR_INVALID_PRICE)
        return INV_ITEM_PRICE

    draft = context.user_data["invoice"]
    name = draft.pop("pending_item_name")
    draft["items"].append({"name": name, "price": price})

    currency = draft.get("currency", "EUR")
    added_line = (
        f"{strings.ITEM_ADDED_PREFIX}{name} — {_format_money(price, currency)}"
    )
    summary = _format_invoice_summary(draft["items"], currency)
    await msg.reply_text(
        f"{added_line}\n\n{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=keyboards.invoice_after_item_keyboard(currency=currency),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 5 — hub after each item is added.

    Handles: add another, create invoice, change currency, save client, cancel.
    """
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            currency = context.user_data.get("invoice", {}).get("currency", "EUR")
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.invoice_after_item_keyboard(currency=currency),
            )
        return INV_ADD_MORE

    text = msg.text.strip()
    user_id = update.effective_user.id

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_ADD_ANOTHER:
        return await _ask_item_name(update, context)

    if text == strings.BTN_CREATE_INVOICE_CONFIRM:
        return await _generate_and_send_pdf(update, context)

    # Change currency — button label includes the code, so use startswith.
    if text.startswith(strings.BTN_CHANGE_CURRENCY):
        await msg.reply_text(
            strings.ASK_CURRENCY,
            reply_markup=keyboards.currency_picker_keyboard(),
        )
        return INV_CURRENCY

    # Save client inline.
    if text == strings.BTN_SAVE_CLIENT:
        client_name = context.user_data["invoice"].get("client_name")
        if client_name:
            try:
                profile_manager.save_client(user_id, client_name)
            except Exception:
                logger.exception(
                    "Could not save client name for user_id=%s", user_id
                )
        currency = context.user_data["invoice"].get("currency", "EUR")
        summary = _format_invoice_summary(
            context.user_data["invoice"]["items"], currency
        )
        await msg.reply_text(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=keyboards.invoice_after_item_keyboard_saved(currency=currency),
        )
        return INV_ADD_MORE

    # CLIENT_SAVED_INLINE button — already saved; treat as no-op, re-show menu.
    if text == strings.CLIENT_SAVED_INLINE:
        currency = context.user_data["invoice"].get("currency", "EUR")
        summary = _format_invoice_summary(
            context.user_data["invoice"]["items"], currency
        )
        await msg.reply_text(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=keyboards.invoice_after_item_keyboard_saved(currency=currency),
        )
        return INV_ADD_MORE

    currency = context.user_data.get("invoice", {}).get("currency", "EUR")
    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.invoice_after_item_keyboard(currency=currency),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_after_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step after PDF — Create another / All done / anything else."""
    msg = update.message
    text = (msg.text or "").strip() if msg else ""

    if text == strings.BTN_CREATE_ANOTHER:
        return await invoice_start_entry(update, context)

    if text == strings.BTN_ALL_DONE:
        await update.effective_chat.send_message(
            strings.BACK_TO_MAIN_MENU,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        strings.BACK_TO_MAIN_MENU,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


@_handler_safe
async def invoice_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/cancel or [❌ Cancel] during invoice flow."""
    context.user_data.pop("invoice", None)
    await update.message.reply_text(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


async def _invoice_cancel_from_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel coming from the inline calendar's Cancel button."""
    query = update.callback_query
    context.user_data.pop("invoice", None)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await update.effective_chat.send_message(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


# =============================================================================
# === PROFILE EDITING FLOW ====================================================
# =============================================================================

@_handler_safe
async def profile_show(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Show current profile + inline edit menu (Flow 4 step 1)."""
    user_id = update.effective_user.id
    profile = profile_manager.get_profile(user_id)
    if not profile:
        await update.message.reply_text(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    summary = _render_profile_summary(profile)
    await update.message.reply_text(
        f"{summary}\n\n{strings.EDIT_PROMPT}",
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Route the inline edit-menu callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data == keyboards.CB_EDIT_DONE:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await update.effective_chat.send_message(
            strings.BACK_TO_MAIN_MENU,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    if data == keyboards.CB_EDIT_NAME:
        await update.effective_chat.send_message(strings.ASK_ORG)
        return PE_NAME
    if data == keyboards.CB_EDIT_PHONE:
        await update.effective_chat.send_message(strings.ASK_PHONE)
        return PE_PHONE
    if data == keyboards.CB_EDIT_ACCOUNT:
        await update.effective_chat.send_message(strings.ASK_ACCOUNT)
        return PE_ACCOUNT
    if data == keyboards.CB_EDIT_REFERENCES:
        await update.effective_chat.send_message(
            strings.ASK_REFERENCES,
            reply_markup=keyboards.onboarding_references_keyboard(),
        )
        return PE_REFERENCES

    return PE_MENU


@_handler_safe
async def profile_menu_text_fallback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Catch stray text while the inline edit menu is active."""
    msg = update.message
    text = (msg.text or "").strip() if msg else ""
    if text == strings.BTN_CANCEL:
        return await profile_cancel(update, context)

    user_id = update.effective_user.id
    profile = profile_manager.get_profile(user_id)
    if profile is None:
        return ConversationHandler.END

    await update.effective_chat.send_message(
        f"{_render_profile_summary(profile)}\n\n{strings.EDIT_PROMPT}",
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


async def _persist_profile_field(
    update: Update,
    user_id: int,
    field_label: str,
    **fields: Any,
) -> dict[str, Any] | None:
    """Update one or more profile fields and emit FIELD_UPDATED."""
    try:
        profile = profile_manager.update_profile(user_id, **fields)
    except (KeyError, OSError):
        logger.exception(
            "Failed to update profile (%s) for user_id=%s",
            fields, user_id,
        )
        await update.effective_chat.send_message(strings.ERR_PDF_FAILURE)
        return None

    await update.effective_chat.send_message(
        strings.FIELD_UPDATED.format(field=field_label)
    )
    return profile


async def _re_show_profile_menu(
    update: Update, profile: dict[str, Any]
) -> int:
    """Re-show the profile + inline menu after a successful edit."""
    await update.effective_chat.send_message(
        f"{_render_profile_summary(profile)}\n\n{strings.EDIT_PROMPT}",
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive a new organization name."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return PE_NAME

    text = msg.text
    stripped = text.strip()
    if not stripped:
        await msg.reply_text(strings.ERR_EMPTY)
        return PE_NAME
    if len(text) < 2:
        await msg.reply_text(strings.ERR_SHORT_TEXT)
        return PE_NAME
    if len(text) > 100:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=100))
        return PE_NAME

    user_id = update.effective_user.id
    profile = await _persist_profile_field(
        update, user_id, _label_word(strings.ORGANIZATION_LABEL),
        org_name=stripped,
    )
    if profile is None:
        return ConversationHandler.END
    return await _re_show_profile_menu(update, profile)


@_handler_safe
async def profile_edit_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive a new phone number."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_PHONE)
        return PE_PHONE

    text = msg.text
    if len(text) < 3 or len(text) > 30:
        await msg.reply_text(strings.ERR_INVALID_PHONE)
        return PE_PHONE

    user_id = update.effective_user.id
    profile = await _persist_profile_field(
        update, user_id, _label_word(strings.PHONE_LABEL),
        phone=text,
    )
    if profile is None:
        return ConversationHandler.END
    return await _re_show_profile_menu(update, profile)


@_handler_safe
async def profile_edit_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive a new IBAN / account number."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_ACCOUNT)
        return PE_ACCOUNT

    text = msg.text.strip()
    if len(text) < 5 or len(text) > 40:
        await msg.reply_text(strings.ERR_INVALID_ACCOUNT)
        return PE_ACCOUNT

    user_id = update.effective_user.id
    profile = await _persist_profile_field(
        update, user_id, _label_word(strings.ACCOUNT_LABEL),
        iban=text,
    )
    if profile is None:
        return ConversationHandler.END
    return await _re_show_profile_menu(update, profile)


@_handler_safe
async def profile_edit_references(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Receive a new reference style choice."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.onboarding_references_keyboard(),
            )
        return PE_REFERENCES

    text = msg.text.strip()
    if text == strings.BTN_REF_STANDARD:
        reference_style = "Standard"
    elif text == strings.BTN_REF_NONE:
        reference_style = "None"
    else:
        await msg.reply_text(
            strings.ERR_WRONG_BUTTON,
            reply_markup=keyboards.onboarding_references_keyboard(),
        )
        return PE_REFERENCES

    user_id = update.effective_user.id
    profile = await _persist_profile_field(
        update, user_id, _label_word(strings.REFERENCES_LABEL),
        reference_style=reference_style,
    )
    if profile is None:
        return ConversationHandler.END
    return await _re_show_profile_menu(update, profile)


@_handler_safe
async def profile_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/cancel mid-profile-edit."""
    user_id = update.effective_user.id
    profile = profile_manager.get_profile(user_id)

    await update.message.reply_text(strings.EDIT_CANCELLED)

    if profile is None:
        await update.message.reply_text(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    await update.effective_chat.send_message(
        f"{_render_profile_summary(profile)}\n\n{strings.EDIT_PROMPT}",
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_start_fallback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/start received mid-profile-edit — cancel edit, go to main menu."""
    user_id = update.effective_user.id
    profile = profile_manager.get_profile(user_id)
    org_name = profile.get("org_name", "") if profile else ""

    await update.message.reply_text(strings.EDIT_CANCELLED)
    await update.message.reply_text(
        strings.WELCOME_BACK.format(org_name=org_name),
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


# =============================================================================
# === STANDALONE COMMANDS =====================================================
# =============================================================================

@_handler_safe
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/help or ❓ Help button."""
    user_id = update.effective_user.id
    has_prof = profile_manager.has_profile(user_id)
    reply_markup = (
        keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove()
    )
    await update.message.reply_text(strings.HELP_TEXT, reply_markup=reply_markup)


@_handler_safe
async def cancel_command_global(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/cancel outside any active conversation."""
    user_id = update.effective_user.id
    has_prof = profile_manager.has_profile(user_id)
    reply_markup = (
        keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove()
    )
    await update.message.reply_text(
        strings.NOTHING_TO_CANCEL, reply_markup=reply_markup
    )


@_handler_safe
async def unknown_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Catch-all for unexpected text messages at the top level."""
    user_id = update.effective_user.id
    if profile_manager.has_profile(user_id):
        profile = profile_manager.get_profile(user_id) or {}
        await update.message.reply_text(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            f"{strings.RESTARTED}\n\nSend /start to begin.",
            reply_markup=ReplyKeyboardRemove(),
        )


# =============================================================================
# === HANDLER REGISTRATION ====================================================
# =============================================================================

def register_handlers(application: Application) -> None:
    """Attach all handlers to the Application instance.

    Invoice ConversationHandler state flow:
        INV_CLIENT(200) → INV_DATE(201) → INV_CALENDAR(202)
        → INV_ITEM_NAME(203) → INV_ITEM_PRICE(204) → INV_ADD_MORE(205)
        → INV_CURRENCY(208) [sub-step] → INV_CURRENCY_CUSTOM(209)
        → INV_AFTER_PDF(206)

    ConversationHandler states dict keys (9 states):
        INV_CLIENT, INV_DATE, INV_CALENDAR, INV_ITEM_NAME, INV_ITEM_PRICE,
        INV_ADD_MORE, INV_CURRENCY, INV_CURRENCY_CUSTOM, INV_AFTER_PDF
    """

    onboarding_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ONBOARD_ORG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_org),
                MessageHandler(~filters.TEXT, onboard_org),
            ],
            ONBOARD_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_phone),
                MessageHandler(~filters.TEXT, onboard_phone),
            ],
            ONBOARD_ACCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_account),
                MessageHandler(~filters.TEXT, onboard_account),
            ],
            ONBOARD_REFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_references),
                MessageHandler(~filters.TEXT, onboard_references),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", onboard_cancel_or_restart),
            CommandHandler("start", onboard_cancel_or_restart),
        ],
        name="onboarding",
        persistent=False,
    )

    invoice_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(_exact(strings.BTN_CREATE_INVOICE)),
                invoice_start_entry,
            ),
            MessageHandler(
                filters.Regex(_exact(strings.BTN_CREATE_ANOTHER)),
                invoice_start_entry,
            ),
        ],
        states={
            INV_CLIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client),
                MessageHandler(~filters.TEXT, invoice_client),
            ],
            INV_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_date),
                MessageHandler(~filters.TEXT, invoice_date),
            ],
            INV_CALENDAR: [
                CallbackQueryHandler(invoice_calendar_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_calendar_text_fallback),
            ],
            INV_ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_name),
                MessageHandler(~filters.TEXT, invoice_item_name),
            ],
            INV_ITEM_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_price),
                MessageHandler(~filters.TEXT, invoice_item_price),
            ],
            INV_ADD_MORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_add_more),
                MessageHandler(~filters.TEXT, invoice_add_more),
            ],
            INV_CURRENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency),
                MessageHandler(~filters.TEXT, invoice_currency),
            ],
            INV_CURRENCY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency_custom),
                MessageHandler(~filters.TEXT, invoice_currency_custom),
            ],
            INV_AFTER_PDF: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_after_pdf),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", invoice_cancel),
            CommandHandler("start", invoice_cancel),
        ],
        name="invoice",
        persistent=False,
    )

    profile_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(_exact(strings.BTN_EDIT_PROFILE)),
                profile_show,
            ),
            CommandHandler("profile", profile_show),
        ],
        states={
            PE_MENU: [
                CallbackQueryHandler(profile_menu_callback),
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_menu_text_fallback),
            ],
            PE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_name),
                MessageHandler(~filters.TEXT, profile_edit_name),
            ],
            PE_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_phone),
                MessageHandler(~filters.TEXT, profile_edit_phone),
            ],
            PE_ACCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_account),
                MessageHandler(~filters.TEXT, profile_edit_account),
            ],
            PE_REFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_references),
                MessageHandler(~filters.TEXT, profile_edit_references),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", profile_cancel),
            CommandHandler("start", profile_start_fallback),
        ],
        name="profile_edit",
        persistent=False,
    )

    application.add_handler(onboarding_conv)
    application.add_handler(invoice_conv)
    application.add_handler(profile_conv)

    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_command_global))
    application.add_handler(
        MessageHandler(
            filters.Regex(_exact(strings.BTN_HELP)),
            help_command,
        )
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler)
    )

    logger.info("All handlers registered successfully.")
    logger.info(
        "Invoice ConversationHandler states: %s",
        list(invoice_conv.states.keys()),
    )
