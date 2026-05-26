"""ConversationHandler flow logic for the Telegram Invoice Bot.

Onboarding, invoice creation, profile editing, and the
/start /cancel /help command handlers all live in this module.
Persistence, PDF generation, keyboards, and user-facing strings live
in their respective frozen modules and are imported, never re-defined.

Public entry point used by main.py:
    register_handlers(application)
"""

from __future__ import annotations

import calendar as _cal
import functools
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
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
ONBOARD_EMAIL = 104
ONBOARD_VAT = 105                # Optional VAT after email

# --- INVOICE group ---
INV_CLIENT = 200
INV_DATE = 201
INV_CALENDAR = 202
INV_ITEM_NAME = 203
INV_ITEM_PRICE = 204
INV_ADD_MORE = 205
INV_AFTER_PDF = 206
INV_CURRENCY = 208
INV_CURRENCY_CUSTOM = 209
INV_DUE_DATE = 210
INV_DUE_DATE_CALENDAR = 211
# Optional client-details sub-flow after the client name
INV_CLIENT_DETAILS_CHOICE = 212
INV_CLIENT_PHONE = 213
INV_CLIENT_ADDRESS = 214
INV_CLIENT_BANK = 215
INV_CLIENT_VAT = 216

# --- PROFILE_EDIT group ---
PE_MENU = 300
PE_NAME = 301
PE_PHONE = 302
PE_ACCOUNT = 303
PE_REFERENCES = 304
PE_EMAIL = 305
PE_VAT = 306

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


# Currency rendering (chat-side)
_CURRENCY_SYMBOLS = {
    "EUR": "\u20ac",
    "USD": "$",
    "KZT": "\u20b8",
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


def _three_months_ago(today: date) -> date:
    """Return the date exactly 3 calendar months before *today* (Feb-29-safe)."""
    m = today.month - 3
    y = today.year
    if m < 1:
        m += 12
        y -= 1
    try:
        return today.replace(year=y, month=m)
    except ValueError:
        return today.replace(year=y, month=m, day=_cal.monthrange(y, m)[1])


def _three_months_ahead(today: date) -> date:
    """Return the date exactly 3 calendar months after *today* (Feb-29-safe)."""
    m = today.month + 3
    y = today.year
    if m > 12:
        m -= 12
        y += 1
    try:
        return today.replace(year=y, month=m)
    except ValueError:
        return today.replace(year=y, month=m, day=_cal.monthrange(y, m)[1])


def _cal_bounds() -> tuple[date, date]:
    """Return (min_date, max_date) for both invoice and due date calendars."""
    today = date.today()
    return _three_months_ago(today), _three_months_ahead(today)


def _is_valid_calendar_date(d: date) -> bool:
    """Return True if *d* falls within the +/- 3 month window from today."""
    min_date, max_date = _cal_bounds()
    return min_date <= d <= max_date


_CURRENCY_TOKENS = ("\u20ac", "$", "\u00a3", "\u20b8", "\u20bd", "EUR", "USD", "GBP", "KZT", "RUB")


def _parse_price(text: str) -> float:
    """Parse a price string into a positive float.

    Accepts integers ("150"), dot-decimals ("49.99"), and comma-decimals
    ("49,99" — common in Europe). Strips surrounding currency tokens
    and spaces. Result is rounded to 2 decimal places.
    """
    cleaned = text.strip()
    for sym in _CURRENCY_TOKENS:
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        raise ValueError("not_number")
    cleaned = cleaned.replace(",", ".")
    if cleaned.startswith("-"):
        raise ValueError("zero_negative")
    if cleaned.count(".") > 1:
        raise ValueError("not_number")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError("not_number") from exc
    if value <= 0:
        raise ValueError("zero_negative")
    return round(value, 2)


def _format_invoice_summary(
    items: list[dict[str, Any]], currency: str = "EUR"
) -> str:
    """Render the running invoice summary block (header + lines + total)."""
    lines: list[str] = [strings.CURRENT_INVOICE_HEADER, ""]
    display_items = items
    if len(items) > 20:
        display_items = items[-15:]
        lines.append(f"[Showing last 15 items of {len(items)}]")
        lines.append("")
    for item in display_items:
        lines.append(f"{item['name']} \u2014 {_format_money(float(item['price']), currency)}")
    total = sum(float(item["price"]) for item in items)
    lines.append("")
    lines.append(f"{strings.TOTAL_LABEL} {_format_money(total, currency)}")
    return "\n".join(lines)


def _render_profile_summary(profile: dict[str, Any]) -> str:
    """Render a profile block for both the post-onboarding confirmation
    and the profile-edit screen."""
    email_value = (profile.get("email") or "").strip() or "\u2014"
    vat_value = (profile.get("vat_number") or "").strip() or "\u2014"
    return (
        f"{strings.PROFILE_HEADER}\n"
        f"{strings.ORGANIZATION_LABEL} {profile.get('org_name', '')}\n"
        f"{strings.PHONE_LABEL} {profile.get('phone', '')}\n"
        f"{strings.EMAIL_LABEL} {email_value}\n"
        f"{strings.VAT_LABEL} {vat_value}\n"
        f"{strings.ACCOUNT_LABEL} {profile.get('iban', '')}\n"
        f"{strings.REFERENCES_LABEL} {profile.get('reference_style', '')}"
    )


def _label_word(label: str) -> str:
    """'Organization:' -> 'Organization' (for FIELD_UPDATED interpolation)."""
    return label.rstrip(":").strip()


_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _is_valid_email(text: str) -> bool:
    """Return True if *text* looks like a plausible email address."""
    return bool(_EMAIL_REGEX.match(text.strip()))


def _new_invoice_draft() -> dict[str, Any]:
    return {
        "client_name": None,
        "date": None,
        "items": [],
        "pending_item_name": None,
        "currency": "EUR",
        "client_saved": False,
        "client_details": {
            "phone": None,
            "address": None,
            "bank": None,
            "vat": None,
        },
    }


def _after_item_keyboard(draft: dict[str, Any]):
    """Pick the right 'what's next' keyboard based on draft state."""
    currency = (draft or {}).get("currency", "EUR")
    if (draft or {}).get("client_saved"):
        return keyboards.invoice_after_item_keyboard_saved(currency=currency)
    return keyboards.invoice_after_item_keyboard(currency=currency)


# =============================================================================
# === CALENDAR CALLBACK MACHINERY =============================================
# =============================================================================

@dataclass(frozen=True)
class _CalCallback:
    flow: str
    action: str
    year: int | None = None
    month: int | None = None
    day: int | None = None


def _parse_cal_callback(data: str | None) -> _CalCallback | None:
    """Parse an inline-calendar callback string. Returns None on any
    malformed input — never raises.
    """
    if not data:
        return None
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != keyboards.CAL_NS:
        return None

    flow = parts[1]
    action = parts[2]

    if flow not in (keyboards.CAL_FLOW_INVOICE_DATE, keyboards.CAL_FLOW_DUE_DATE):
        return None

    if action in (keyboards.CAL_ACTION_NOOP, keyboards.CAL_ACTION_CANCEL):
        return _CalCallback(flow=flow, action=action)

    if action in (keyboards.CAL_ACTION_PREV, keyboards.CAL_ACTION_NEXT):
        if len(parts) < 5:
            return None
        try:
            y = int(parts[3])
            m = int(parts[4])
            if not (1 <= m <= 12):
                return None
            return _CalCallback(flow=flow, action=action, year=y, month=m)
        except ValueError:
            return None

    if action == keyboards.CAL_ACTION_DAY:
        if len(parts) < 6:
            return None
        try:
            y = int(parts[3])
            m = int(parts[4])
            d = int(parts[5])
            date(y, m, d)
            return _CalCallback(flow=flow, action=action, year=y, month=m, day=d)
        except ValueError:
            return None

    return None


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, _cal.monthrange(year, month)[1])


def _first_day_of_month(year: int, month: int) -> date:
    return date(year, month, 1)


async def _safe_ack(query, text: str | None = None, *, alert: bool = False) -> None:
    """Best-effort callback ack. Telegram will ignore expired callbacks
    quietly; we don't want any of that bubbling up."""
    try:
        await query.answer(text=text or "", show_alert=alert)
    except Exception:
        logger.debug("query.answer() failed (probably expired); ignoring.")


async def _safe_delete(message) -> None:
    """Best-effort message delete. Useful for tearing down stale UI."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        logger.debug("message.delete() failed; ignoring.")


async def _render_calendar(
    query, year: int, month: int, *, flow: str
) -> None:
    """Re-render the calendar message in place for the given flow."""
    min_date, max_date = _cal_bounds()
    try:
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                year, month,
                flow=flow,
                min_date=min_date, max_date=max_date,
            )
        )
    except Exception:
        logger.exception(
            "Failed to re-render calendar (flow=%s, %d-%02d)", flow, year, month
        )


async def _calendar_callback_dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    expected_flow: str,
    state_on_continue: int,
) -> int:
    """The one and only place that reacts to a calendar callback."""
    query = update.callback_query
    if query is None:
        return state_on_continue

    cb = _parse_cal_callback(query.data)

    if cb is None:
        logger.warning(
            "Malformed calendar callback: data=%r (expected_flow=%s)",
            query.data, expected_flow,
        )
        await _safe_ack(
            query,
            "This calendar is no longer active. Please start again.",
        )
        await _safe_delete(query.message)
        return state_on_continue

    if cb.flow != expected_flow:
        logger.warning(
            "Calendar flow mismatch: payload_flow=%s expected_flow=%s data=%r",
            cb.flow, expected_flow, query.data,
        )
        await _safe_ack(
            query,
            "This calendar is no longer active. Please start again.",
        )
        await _safe_delete(query.message)
        return state_on_continue

    await _safe_ack(query)

    if cb.action == keyboards.CAL_ACTION_NOOP:
        return state_on_continue

    if cb.action == keyboards.CAL_ACTION_CANCEL:
        return await _invoice_cancel_from_callback(update, context)

    min_date, max_date = _cal_bounds()

    if cb.action == keyboards.CAL_ACTION_PREV:
        assert cb.year is not None and cb.month is not None
        new_year, new_month = _prev_month(cb.year, cb.month)
        if _last_day_of_month(new_year, new_month) < min_date:
            await _safe_ack(query, "Already at the earliest month.")
            return state_on_continue
        await _render_calendar(query, new_year, new_month, flow=expected_flow)
        return state_on_continue

    if cb.action == keyboards.CAL_ACTION_NEXT:
        assert cb.year is not None and cb.month is not None
        new_year, new_month = _next_month(cb.year, cb.month)
        if _first_day_of_month(new_year, new_month) > max_date:
            await _safe_ack(query, "Already at the latest month.")
            return state_on_continue
        await _render_calendar(query, new_year, new_month, flow=expected_flow)
        return state_on_continue

    if cb.action == keyboards.CAL_ACTION_DAY:
        assert cb.year is not None and cb.month is not None and cb.day is not None
        selected = date(cb.year, cb.month, cb.day)

        if not _is_valid_calendar_date(selected):
            await _safe_ack(query, "Date out of allowed range.", alert=True)
            return state_on_continue

        draft = context.user_data.setdefault("invoice", _new_invoice_draft())

        if expected_flow == keyboards.CAL_FLOW_INVOICE_DATE:
            draft["date"] = selected
            logger.info(
                "Invoice date selected: %s (user_id=%s)",
                selected.isoformat(),
                update.effective_user.id if update.effective_user else "?",
            )
            await _safe_delete(query.message)
            return await _ask_item_name(update, context)

        if expected_flow == keyboards.CAL_FLOW_DUE_DATE:
            draft["due_date"] = selected
            logger.info(
                "Due date selected: %s (user_id=%s)",
                selected.isoformat(),
                update.effective_user.id if update.effective_user else "?",
            )
            await _safe_delete(query.message)
            items = draft.get("items", [])
            currency = draft.get("currency", "EUR")
            summary = _format_invoice_summary(items, currency)
            await update.effective_chat.send_message(
                f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
                reply_markup=_after_item_keyboard(draft),
            )
            return INV_ADD_MORE

    logger.warning(
        "Unhandled calendar action=%r flow=%s", cb.action, expected_flow,
    )
    return state_on_continue


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
    await msg.reply_text(
        strings.ASK_EMAIL,
        reply_markup=keyboards.email_keyboard(),
        parse_mode="Markdown",
    )
    return ONBOARD_EMAIL


@_handler_safe
async def onboard_email(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_INVALID_EMAIL,
                reply_markup=keyboards.email_keyboard(),
            )
        return ONBOARD_EMAIL

    text = msg.text.strip()

    if text == strings.BTN_SKIP_EMAIL:
        context.user_data.setdefault("onboarding", {})["email"] = ""
        await msg.reply_text(
            strings.ASK_VAT,
            reply_markup=keyboards.vat_keyboard(),
            parse_mode="Markdown",
        )
        return ONBOARD_VAT

    if not _is_valid_email(text):
        await msg.reply_text(
            strings.ERR_INVALID_EMAIL,
            reply_markup=keyboards.email_keyboard(),
        )
        return ONBOARD_EMAIL

    context.user_data.setdefault("onboarding", {})["email"] = text
    await msg.reply_text(
        strings.ASK_VAT,
        reply_markup=keyboards.vat_keyboard(),
        parse_mode="Markdown",
    )
    return ONBOARD_VAT


@_handler_safe
async def onboard_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_INVALID_VAT,
                reply_markup=keyboards.vat_keyboard(),
            )
        return ONBOARD_VAT

    text = msg.text.strip()

    if text == strings.BTN_SKIP_VAT:
        context.user_data.setdefault("onboarding", {})["vat_number"] = ""
        await msg.reply_text(
            strings.ASK_ACCOUNT, reply_markup=ReplyKeyboardRemove()
        )
        return ONBOARD_ACCOUNT

    if len(text) < 3 or len(text) > 20:
        await msg.reply_text(
            strings.ERR_INVALID_VAT,
            reply_markup=keyboards.vat_keyboard(),
        )
        return ONBOARD_VAT

    context.user_data.setdefault("onboarding", {})["vat_number"] = text
    await msg.reply_text(
        strings.ASK_ACCOUNT, reply_markup=ReplyKeyboardRemove()
    )
    return ONBOARD_ACCOUNT


@_handler_safe
async def onboard_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
            email=draft.get("email", ""),
            vat_number=draft.get("vat_number", ""),
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

    email_value = (draft.get("email") or "").strip()
    vat_value = (draft.get("vat_number") or "").strip()
    email_line = f"{strings.EMAIL_LABEL} {email_value}\n" if email_value else ""
    vat_line = f"{strings.VAT_LABEL} {vat_value}\n" if vat_value else ""
    confirmation = (
        f"{strings.PROFILE_CREATED_HEADER}\n\n"
        f"{strings.PROFILE_DETAILS_LABEL}\n"
        f"{strings.ORGANIZATION_LABEL} {draft['org_name']}\n"
        f"{strings.PHONE_LABEL} {draft['phone']}\n"
        f"{email_line}"
        f"{vat_line}"
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
    """Fallback for /cancel and /start while mid-onboarding."""
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
    """Invoice entry point — initialise draft, seed default currency,
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


async def _ask_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send the date prompt and move into INV_DATE."""
    chat = update.effective_chat
    await chat.send_message(
        strings.ASK_DATE,
        reply_markup=keyboards.invoice_date_keyboard(),
    )
    return INV_DATE


def _client_details_for_pdf(draft: dict[str, Any]) -> dict[str, Any] | None:
    details = (draft or {}).get("client_details") or {}
    if any((v or "").strip() if isinstance(v, str) else False for v in details.values()):
        return details
    return None


async def _generate_and_send_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
    due_date_value = draft.get("due_date")
    client_details = _client_details_for_pdf(draft)

    try:
        pdf_path: Path = pdf_generator.generate_invoice_pdf(
            invoice_number=next_number,
            invoice_date=invoice_date_value,
            client_name=client_name,
            items=items,
            profile=profile,
            currency=currency,
            due_date=due_date_value,
            client_details=client_details,
        )
    except Exception:
        logger.exception("PDF generation failed for user_id=%s", user_id)
        await _safe_delete(status_msg)
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

    await _safe_delete(status_msg)

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

    try:
        total_amount = float(sum(float(i.get("price", 0)) for i in items))
        reference = None
        ref_style = str(profile.get("reference_style", "")).strip().lower()
        if ref_style == "standard":
            reference = f"INV-{committed_number:05d}"
        record = {
            "number": int(committed_number),
            "client_name": client_name or None,
            "amount": total_amount,
            "currency": currency,
            "invoice_date": invoice_date_value.strftime("%d.%m.%Y"),
            "due_date": (
                due_date_value
                if isinstance(due_date_value, str)
                else (due_date_value.strftime("%d.%m.%Y") if due_date_value else None)
            ),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "paid": False,
            "reference": reference,
        }
        profile_manager.record_invoice(user_id, record)
    except Exception:
        logger.exception(
            "Could not record invoice #%05d to tracking history for user_id=%s",
            committed_number, user_id,
        )

    # Bug 2 — Skip the intermediate "All done / Create another" menu;
    # return straight to the main menu so the bot is immediately usable.
    # invoice_after_pdf is now unreachable through this path but left in
    # the codebase as defensive dead code (stale keyboards from previous
    # sessions still work).
    context.user_data.pop("invoice", None)
    profile_after = profile_manager.get_profile(user_id) or {}
    await chat.send_message(
        strings.WELCOME_BACK.format(org_name=profile_after.get("org_name", "")),
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


@_handler_safe
async def invoice_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.BTN_BACK:
        items = draft.get("items", [])
        currency = draft.get("currency", "EUR")
        summary = _format_invoice_summary(items, currency)
        await msg.reply_text(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=_after_item_keyboard(draft),
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

    draft["currency"] = code
    items = draft.get("items", [])
    summary = _format_invoice_summary(items, code)
    await msg.reply_text(
        f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_currency_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_CURRENCY)
        return INV_CURRENCY_CUSTOM

    raw = msg.text.strip()
    if raw == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    text = raw.upper()
    if not (2 <= len(text) <= 4) or not text.isalpha():
        await msg.reply_text(strings.ERR_INVALID_CURRENCY)
        return INV_CURRENCY_CUSTOM

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["currency"] = text
    items = draft.get("items", [])
    summary = _format_invoice_summary(items, text)
    await msg.reply_text(
        f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return INV_CLIENT

    text = msg.text

    if text.strip() == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text.strip() == strings.BTN_NO_NAME:
        context.user_data.setdefault("invoice", _new_invoice_draft())["client_name"] = None
        return await _ask_date(update, context)

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

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["client_name"] = stripped

    # Bug 3 — If the typed/tapped name matches a saved client, auto-populate
    # client_details from the saved record and skip the details sub-flow
    # entirely. Case-insensitive match.
    user_id = update.effective_user.id
    saved = profile_manager.get_saved_client_by_name(user_id, stripped)
    if saved is not None:
        draft["client_details"] = {
            "phone": saved.get("phone"),
            "address": saved.get("address"),
            "bank": saved.get("bank"),
            "vat": saved.get("vat"),
        }
        # Already in saved list — surface the "Client saved" indicator
        # on the after-item keyboard instead of the Save Client prompt.
        draft["client_saved"] = True
        return await _ask_date(update, context)

    await msg.reply_text(
        strings.ASK_CLIENT_DETAILS_CHOICE,
        reply_markup=keyboards.client_details_choice_keyboard(),
    )
    return INV_CLIENT_DETAILS_CHOICE


# --- optional client-details sub-flow --------------------------------------

@_handler_safe
async def invoice_client_details_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.client_details_choice_keyboard(),
            )
        return INV_CLIENT_DETAILS_CHOICE

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_ADD_CLIENT_DETAILS:
        await msg.reply_text(
            strings.ASK_CLIENT_PHONE,
            reply_markup=keyboards.client_detail_skip_keyboard(),
            parse_mode="Markdown",
        )
        return INV_CLIENT_PHONE

    if text == strings.BTN_SKIP_CLIENT_DETAILS:
        return await _ask_date(update, context)

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.client_details_choice_keyboard(),
    )
    return INV_CLIENT_DETAILS_CHOICE


def _save_client_detail(
    context: ContextTypes.DEFAULT_TYPE, key: str, value: str | None
) -> None:
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    details = draft.setdefault(
        "client_details",
        {"phone": None, "address": None, "bank": None, "vat": None},
    )
    details[key] = value


@_handler_safe
async def invoice_client_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
        return INV_CLIENT_PHONE

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_SKIP_DETAIL:
        _save_client_detail(context, "phone", None)
    else:
        if len(text) < 3 or len(text) > 30:
            await msg.reply_text(
                strings.ERR_INVALID_PHONE,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
            return INV_CLIENT_PHONE
        _save_client_detail(context, "phone", text)

    await msg.reply_text(
        strings.ASK_CLIENT_ADDRESS,
        reply_markup=keyboards.client_detail_skip_keyboard(),
        parse_mode="Markdown",
    )
    return INV_CLIENT_ADDRESS


@_handler_safe
async def invoice_client_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
        return INV_CLIENT_ADDRESS

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_SKIP_DETAIL:
        _save_client_detail(context, "address", None)
    else:
        if len(text) < 3 or len(text) > 200:
            await msg.reply_text(
                strings.ERR_LONG_TEXT.format(n=200) if len(text) > 200 else strings.ERR_SHORT_TEXT,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
            return INV_CLIENT_ADDRESS
        _save_client_detail(context, "address", text)

    await msg.reply_text(
        strings.ASK_CLIENT_BANK,
        reply_markup=keyboards.client_detail_skip_keyboard(),
        parse_mode="Markdown",
    )
    return INV_CLIENT_BANK


@_handler_safe
async def invoice_client_bank(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
        return INV_CLIENT_BANK

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_SKIP_DETAIL:
        _save_client_detail(context, "bank", None)
    else:
        if len(text) < 5 or len(text) > 40:
            await msg.reply_text(
                strings.ERR_INVALID_ACCOUNT,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
            return INV_CLIENT_BANK
        _save_client_detail(context, "bank", text)

    await msg.reply_text(
        strings.ASK_CLIENT_VAT,
        reply_markup=keyboards.client_detail_skip_keyboard(),
        parse_mode="Markdown",
    )
    return INV_CLIENT_VAT


@_handler_safe
async def invoice_client_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
        return INV_CLIENT_VAT

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_SKIP_DETAIL:
        _save_client_detail(context, "vat", None)
    else:
        if len(text) < 3 or len(text) > 20:
            await msg.reply_text(
                strings.ERR_INVALID_VAT,
                reply_markup=keyboards.client_detail_skip_keyboard(),
            )
            return INV_CLIENT_VAT
        _save_client_detail(context, "vat", text)

    return await _ask_date(update, context)


# ---------------------------------------------------------------------------

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
        context.user_data.setdefault("invoice", _new_invoice_draft())["date"] = today
        return await _ask_item_name(update, context)

    if text == strings.BTN_YESTERDAY:
        context.user_data.setdefault("invoice", _new_invoice_draft())["date"] = today - timedelta(days=1)
        return await _ask_item_name(update, context)

    if text == strings.BTN_PICK_DATE:
        min_date, max_date = _cal_bounds()
        await msg.reply_text(
            strings.CALENDAR_PROMPT,
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_INVOICE_DATE,
                min_date=min_date, max_date=max_date,
            ),
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
    """Callback handler for the invoice ISSUE-date inline calendar."""
    return await _calendar_callback_dispatch(
        update, context,
        expected_flow=keyboards.CAL_FLOW_INVOICE_DATE,
        state_on_continue=INV_CALENDAR,
    )


# =============================================================================
# === ITEM ENTRY ==============================================================
# =============================================================================

async def _ask_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return INV_ITEM_NAME

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return INV_ITEM_NAME
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return INV_ITEM_NAME

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["pending_item_name"] = text
    # Bug 1 — Format ASK_ITEM_PRICE with the just-captured item name so
    # the user sees the actual name (bold) instead of the literal
    # placeholder "{item_name}". parse_mode="Markdown" is required for
    # the surrounding asterisks to render as bold.
    await msg.reply_text(
        strings.ASK_ITEM_PRICE.format(item_name=text),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return INV_ITEM_PRICE


@_handler_safe
async def invoice_item_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_PRICE)
        return INV_ITEM_PRICE

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    try:
        price = _parse_price(text)
    except ValueError as exc:
        err_code = exc.args[0] if exc.args else "not_number"
        if err_code == "zero_negative":
            await msg.reply_text(strings.ERR_ZERO_NEGATIVE_PRICE)
        else:
            await msg.reply_text(strings.ERR_INVALID_PRICE)
        return INV_ITEM_PRICE

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    item_name = draft.pop("pending_item_name", None) or "Item"
    draft.setdefault("items", []).append({"name": item_name, "price": price})

    currency = draft.get("currency", "EUR")
    summary = _format_invoice_summary(draft["items"], currency)
    await msg.reply_text(
        f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            draft = context.user_data.get("invoice", {})
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=_after_item_keyboard(draft),
            )
        return INV_ADD_MORE

    text = msg.text.strip()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_ADD_ANOTHER:
        return await _ask_item_name(update, context)

    if text == strings.BTN_CREATE_INVOICE_CONFIRM:
        return await _generate_and_send_pdf(update, context)

    if text == strings.BTN_DUE_DATE:
        await msg.reply_text(
            strings.ASK_DUE_DATE,
            reply_markup=keyboards.due_date_keyboard(),
        )
        return INV_DUE_DATE

    if text.startswith(strings.BTN_CHANGE_CURRENCY):
        await msg.reply_text(
            strings.ASK_CURRENCY,
            reply_markup=keyboards.currency_picker_keyboard(),
        )
        return INV_CURRENCY

    if text in (strings.BTN_SAVE_CLIENT, strings.CLIENT_SAVED_INLINE):
        client_name = draft.get("client_name")
        if client_name:
            user_id = update.effective_user.id
            # Bug 3 — Persist the full client record (name + details),
            # not just the name. Whatever the user entered through the
            # client-details sub-flow rides along with the save.
            cd = draft.get("client_details") or {}
            try:
                profile_manager.save_client(
                    user_id,
                    client_name,
                    phone=cd.get("phone"),
                    address=cd.get("address"),
                    bank=cd.get("bank"),
                    vat=cd.get("vat"),
                )
                draft["client_saved"] = True
                await msg.reply_text(
                    strings.CLIENT_SAVED,
                    reply_markup=_after_item_keyboard(draft),
                )
            except Exception:
                logger.exception("Failed to save client for user_id=%s", user_id)
                await msg.reply_text(strings.ERR_PDF_FAILURE)
        return INV_ADD_MORE

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


# =============================================================================
# === DUE DATE ================================================================
# =============================================================================

@_handler_safe
async def invoice_due_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.due_date_keyboard(),
            )
        return INV_DUE_DATE

    text = msg.text.strip()
    today = date.today()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    async def _back_to_summary() -> int:
        items = draft.get("items", [])
        currency = draft.get("currency", "EUR")
        summary = _format_invoice_summary(items, currency)
        await msg.reply_text(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=_after_item_keyboard(draft),
        )
        return INV_ADD_MORE

    if text == strings.BTN_BACK:
        return await _back_to_summary()

    if text == strings.BTN_DUE_NET30:
        draft["due_date"] = today + timedelta(days=30)
        return await _back_to_summary()

    if text == strings.BTN_DUE_NET15:
        draft["due_date"] = today + timedelta(days=14)
        return await _back_to_summary()

    if text == strings.BTN_DUE_ON_RECEIPT:
        draft["due_date"] = "On receipt"
        return await _back_to_summary()

    if text == strings.BTN_DUE_CUSTOM:
        min_date, max_date = _cal_bounds()
        await msg.reply_text(
            strings.CALENDAR_PROMPT,
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_DUE_DATE,
                min_date=min_date, max_date=max_date,
            ),
        )
        return INV_DUE_DATE_CALENDAR

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.due_date_keyboard(),
    )
    return INV_DUE_DATE


@_handler_safe
async def invoice_due_date_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Callback handler for the invoice DUE-date inline calendar."""
    return await _calendar_callback_dispatch(
        update, context,
        expected_flow=keyboards.CAL_FLOW_DUE_DATE,
        state_on_continue=INV_DUE_DATE_CALENDAR,
    )


# =============================================================================
# === AFTER-PDF MENU ==========================================================
# =============================================================================
# Bug 2 — As of this fix, the normal post-PDF flow returns directly to
# the main menu (see _generate_and_send_pdf). This handler is kept for
# safety: if some user has a stale "All done / Create another" keyboard
# from a previous session, tapping it still routes correctly.

@_handler_safe
async def invoice_after_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.invoice_after_pdf_keyboard(),
            )
        return INV_AFTER_PDF

    text = msg.text.strip()

    if text == strings.BTN_CREATE_ANOTHER:
        return await invoice_start_entry(update, context)

    if text in (strings.BTN_ALL_DONE, strings.BTN_CANCEL):
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.invoice_after_pdf_keyboard(),
    )
    return INV_AFTER_PDF


# =============================================================================
# === CANCEL HELPERS ==========================================================
# =============================================================================

@_handler_safe
async def invoice_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel the current invoice flow and return to main menu."""
    context.user_data.pop("invoice", None)
    await update.effective_chat.send_message(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


async def _invoice_cancel_from_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel helper for inline-keyboard (callback query) contexts."""
    context.user_data.pop("invoice", None)
    await _safe_delete(update.callback_query.message if update.callback_query else None)
    await update.effective_chat.send_message(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


# =============================================================================
# === ORPHAN CALENDAR CALLBACK ================================================
# =============================================================================

@_handler_safe
async def orphan_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Global fallback for calendar callbacks whose conversation state
    has gone away (e.g. the user /cancel'd while the inline keyboard
    was still visible). Acks Telegram and tears down the stale UI.
    """
    query = update.callback_query
    if query is None:
        return
    logger.info(
        "Orphan calendar callback: data=%r user_id=%s",
        query.data,
        update.effective_user.id if update.effective_user else "?",
    )
    await _safe_ack(
        query,
        "This calendar has expired. Tap a button below to start again.",
    )
    await _safe_delete(query.message)


# =============================================================================
# === PROFILE EDIT FLOW =======================================================
# =============================================================================

@_handler_safe
async def profile_edit_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
        parse_mode="Markdown",
    )
    return PE_MENU


@_handler_safe
async def profile_edit_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.profile_edit_keyboard(),
            )
        return PE_MENU

    text = msg.text.strip()

    if text == strings.BTN_CANCEL:
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    field_map = {
        strings.BTN_EDIT_ORG: (PE_NAME, strings.ASK_ORG),
        strings.BTN_EDIT_PHONE: (PE_PHONE, strings.ASK_PHONE),
        strings.BTN_EDIT_EMAIL: (PE_EMAIL, strings.ASK_EMAIL),
        strings.BTN_EDIT_VAT: (PE_VAT, strings.ASK_VAT),
        strings.BTN_EDIT_ACCOUNT: (PE_ACCOUNT, strings.ASK_ACCOUNT),
        strings.BTN_EDIT_REFERENCES: (PE_REFERENCES, strings.ASK_REFERENCES),
    }

    entry = field_map.get(text)
    if entry is None:
        await msg.reply_text(
            strings.ERR_WRONG_BUTTON,
            reply_markup=keyboards.profile_edit_keyboard(),
        )
        return PE_MENU

    next_state, prompt = entry
    if next_state == PE_EMAIL:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.email_keyboard(),
            parse_mode="Markdown",
        )
    elif next_state == PE_VAT:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.vat_keyboard(),
            parse_mode="Markdown",
        )
    elif next_state == PE_REFERENCES:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.onboarding_references_keyboard(),
        )
    else:
        await msg.reply_text(prompt, reply_markup=ReplyKeyboardRemove())
    return next_state


@_handler_safe
async def profile_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return PE_NAME

    text = msg.text.strip()
    if len(text) < 2 or len(text) > 100:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=100) if len(text) > 100 else strings.ERR_SHORT_TEXT)
        return PE_NAME

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, org_name=text)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.ORGANIZATION_LABEL), value=text),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_INVALID_PHONE)
        return PE_PHONE

    text = msg.text.strip()
    if len(text) < 3 or len(text) > 30:
        await msg.reply_text(strings.ERR_INVALID_PHONE)
        return PE_PHONE

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, phone=text)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.PHONE_LABEL), value=text),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_email(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_INVALID_EMAIL,
                reply_markup=keyboards.email_keyboard(),
            )
        return PE_EMAIL

    text = msg.text.strip()
    if text == strings.BTN_SKIP_EMAIL:
        user_id = update.effective_user.id
        profile_manager.update_profile(user_id, email="")
        await msg.reply_text(
            strings.FIELD_UPDATED.format(field=_label_word(strings.EMAIL_LABEL), value="(removed)"),
            reply_markup=keyboards.profile_edit_keyboard(),
        )
        return PE_MENU

    if not _is_valid_email(text):
        await msg.reply_text(
            strings.ERR_INVALID_EMAIL,
            reply_markup=keyboards.email_keyboard(),
        )
        return PE_EMAIL

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, email=text)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.EMAIL_LABEL), value=text),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_INVALID_VAT,
                reply_markup=keyboards.vat_keyboard(),
            )
        return PE_VAT

    text = msg.text.strip()
    if text == strings.BTN_SKIP_VAT:
        user_id = update.effective_user.id
        profile_manager.update_profile(user_id, vat_number="")
        await msg.reply_text(
            strings.FIELD_UPDATED.format(field=_label_word(strings.VAT_LABEL), value="(removed)"),
            reply_markup=keyboards.profile_edit_keyboard(),
        )
        return PE_MENU

    if len(text) < 3 or len(text) > 20:
        await msg.reply_text(
            strings.ERR_INVALID_VAT,
            reply_markup=keyboards.vat_keyboard(),
        )
        return PE_VAT

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, vat_number=text)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.VAT_LABEL), value=text),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
    profile_manager.update_profile(user_id, iban=text)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.ACCOUNT_LABEL), value=text),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_references(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
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
    profile_manager.update_profile(user_id, reference_style=reference_style)
    await msg.reply_text(
        strings.FIELD_UPDATED.format(field=_label_word(strings.REFERENCES_LABEL), value=reference_style),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


# =============================================================================
# === TRACK INVOICES ==========================================================
# =============================================================================

@_handler_safe
async def track_invoices_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user_id = update.effective_user.id
    invoices = profile_manager.get_invoices(user_id)

    if not invoices:
        await update.message.reply_text(
            strings.NO_INVOICES_YET,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    lines: list[str] = [strings.INVOICE_LIST_HEADER, ""]
    for inv in invoices:
        status = "\u2705" if inv.get("paid") else "\u23f3"
        number = f"#{inv.get('number', 0):05d}"
        client = inv.get("client_name") or strings.NO_CLIENT_LABEL
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        ref = inv.get("reference") or "\u2014"
        inv_date = inv.get("invoice_date") or "\u2014"
        due = inv.get("due_date") or "\u2014"
        lines.append(
            f"{status} {number} | {client}\n"
            f"   {amount}  |  {strings.REF_LABEL} {ref}\n"
            f"   {strings.DATE_LABEL} {inv_date}  |  {strings.DUE_LABEL} {due}"
        )
        lines.append("")

    if lines and lines[-1] == "":
        lines.pop()

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboards.track_invoices_keyboard(),
    )
    return ConversationHandler.END


@_handler_safe
async def track_invoices_mark_paid_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user_id = update.effective_user.id
    invoices = profile_manager.get_invoices(user_id)
    unpaid = [inv for inv in invoices if not inv.get("paid")]

    if not unpaid:
        await update.message.reply_text(
            strings.ALL_INVOICES_PAID,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    buttons: list[list[InlineKeyboardButton]] = []
    for inv in unpaid:
        number = inv.get("number", 0)
        client = inv.get("client_name") or strings.NO_CLIENT_LABEL
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        label = f"#{number:05d} \u00b7 {client} \u00b7 {amount}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"markpaid:{number}")
        ])
    buttons.append([InlineKeyboardButton(strings.BTN_BACK_TO_MENU, callback_data="markpaid:cancel")])

    await update.message.reply_text(
        strings.SELECT_INVOICE_TO_MARK,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


async def track_mark_paid_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data == "markpaid:cancel":
        await _safe_delete(query.message)
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await update.effective_chat.send_message(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return

    parts = data.split(":", 1)
    if len(parts) != 2:
        return
    try:
        invoice_number = int(parts[1])
    except ValueError:
        return

    user_id = update.effective_user.id
    try:
        profile_manager.mark_invoice_paid(user_id, invoice_number)
    except Exception:
        logger.exception(
            "Failed to mark invoice #%05d paid for user_id=%s",
            invoice_number, user_id,
        )
        await query.answer("Could not mark as paid. Please try again.", show_alert=True)
        return

    invoices = profile_manager.get_invoices(user_id)
    unpaid = [inv for inv in invoices if not inv.get("paid")]

    if not unpaid:
        await _safe_delete(query.message)
        await update.effective_chat.send_message(
            strings.ALL_INVOICES_PAID,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return

    buttons: list[list[InlineKeyboardButton]] = []
    for inv in unpaid:
        number = inv.get("number", 0)
        client = inv.get("client_name") or strings.NO_CLIENT_LABEL
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        label = f"#{number:05d} \u00b7 {client} \u00b7 {amount}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"markpaid:{number}")
        ])
    buttons.append([InlineKeyboardButton(strings.BTN_BACK_TO_MENU, callback_data="markpaid:cancel")])

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        pass

    await query.answer(strings.INVOICE_MARKED_PAID.format(number=f"{invoice_number:05d}"), show_alert=False)


# =============================================================================
# === FALLBACK ================================================================
# =============================================================================

@_handler_safe
async def fallback_any_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Catch-all for messages outside any active conversation."""
    user_id = update.effective_user.id
    if profile_manager.has_profile(user_id):
        profile = profile_manager.get_profile(user_id) or {}
        await update.message.reply_text(
            strings.WELCOME_BACK.format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(),
        )
    else:
        await update.message.reply_text(
            strings.PROMPT_START,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )


# =============================================================================
# === HELP ====================================================================
# =============================================================================

@_handler_safe
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.message.reply_text(
        strings.HELP_TEXT,
        parse_mode="Markdown",
        reply_markup=(
            keyboards.main_menu_keyboard()
            if profile_manager.has_profile(update.effective_user.id)
            else ReplyKeyboardRemove()
        ),
    )


# =============================================================================
# === REGISTER ALL HANDLERS ===================================================
# =============================================================================

def register_handlers(application: Application) -> None:
    """Attach every handler to *application*. Called once from main.py."""

    onboarding_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ONBOARD_ORG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_org),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_phone),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_email),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_vat),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_ACCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_account),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_REFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_references),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", onboard_cancel_or_restart),
            CommandHandler("start", onboard_cancel_or_restart),
        ],
        allow_reentry=True,
    )

    invoice_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(_exact(strings.BTN_CREATE_INVOICE)), invoice_start_entry),
        ],
        states={
            INV_CLIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client),
            ],
            INV_CLIENT_DETAILS_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_details_choice),
            ],
            INV_CLIENT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_phone),
            ],
            INV_CLIENT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_address),
            ],
            INV_CLIENT_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_bank),
            ],
            INV_CLIENT_VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_vat),
            ],
            INV_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_date),
            ],
            INV_CALENDAR: [
                CallbackQueryHandler(
                    invoice_calendar_callback,
                    pattern=rf"^{keyboards.CAL_NS}:",
                ),
            ],
            INV_ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_name),
            ],
            INV_ITEM_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_price),
            ],
            INV_ADD_MORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_add_more),
            ],
            INV_CURRENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency),
            ],
            INV_CURRENCY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency_custom),
            ],
            INV_DUE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_due_date),
            ],
            INV_DUE_DATE_CALENDAR: [
                CallbackQueryHandler(
                    invoice_due_date_calendar_callback,
                    pattern=rf"^{keyboards.CAL_NS}:",
                ),
            ],
            INV_AFTER_PDF: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_after_pdf),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", invoice_cancel),
            CommandHandler("start", invoice_cancel),
        ],
        allow_reentry=True,
    )

    profile_edit_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(_exact(strings.BTN_EDIT_PROFILE)), profile_edit_entry),
        ],
        states={
            PE_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_menu),
            ],
            PE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_name),
            ],
            PE_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_phone),
            ],
            PE_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_email),
            ],
            PE_VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_vat),
            ],
            PE_ACCOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_account),
            ],
            PE_REFERENCES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_references),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", profile_edit_entry),
            CommandHandler("start", profile_edit_entry),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(
        MessageHandler(
            filters.Regex(_exact(strings.BTN_TRACK_INVOICES)),
            track_invoices_entry,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(_exact(strings.BTN_MARK_AS_PAID)),
            track_invoices_mark_paid_entry,
        )
    )
    application.add_handler(
        CallbackQueryHandler(track_mark_paid_callback, pattern=r"^markpaid:")
    )

    application.add_handler(onboarding_conv)
    application.add_handler(invoice_conv)
    application.add_handler(profile_edit_conv)

    application.add_handler(
        CallbackQueryHandler(
            orphan_calendar_callback,
            pattern=rf"^{keyboards.CAL_NS}:",
        )
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_any_message)
    )

    logger.info("All handlers registered successfully.")
