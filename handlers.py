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


def _s(key: str, context, user_id: int) -> str:
    return strings.get_string(key, _get_lang(context, user_id))


logger = logging.getLogger(__name__)


# =============================================================================
# === STATES ==================================================================
# =============================================================================
# Three separate integer ranges so the groups never collide in log output.

# --- ONBOARDING group ---
ONBOARD_LANGUAGE = 106            # Feature 2 — language picker (first step)
ONBOARD_ORG = 100
ONBOARD_PHONE = 101
ONBOARD_ACCOUNT = 102
ONBOARD_REFERENCES = 103
ONBOARD_EMAIL = 104
ONBOARD_VAT = 105                # Optional VAT after email
ONBOARD_CURRENCY = 107            # Feature 3 — default currency picker
ONBOARD_VAT_RATE = 108            # Goal 2 — default VAT rate (after references)

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
INV_VAT_RATE = 217               # Goal 2 — per-invoice VAT override (after items)
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
PE_VAT_RATE = 307                # Goal 2 — edit default VAT rate

# --- RECEIPT group (Feature 1) ---
RCP_BILL_TO = 400
RCP_CLIENT_ADDRESS = 401
RCP_CLIENT_EMAIL = 402
RCP_INVOICE_REF = 403
RCP_DATE_PAID = 404
RCP_ITEM_DESC = 405
RCP_ITEM_QTY = 406
RCP_ITEM_PRICE = 407
RCP_ITEM_VAT = 408
RCP_ADD_MORE = 409
RCP_AMOUNT_PAID = 410
RCP_PAYMENT_METHOD = 411
RCP_PAYMENT_OTHER = 412
RCP_PAYMENT_DATE = 413

# --- QUOTE group (Goal 1) ---
QTE_CLIENT = 500
QTE_CLIENT_DETAILS_CHOICE = 501
QTE_CLIENT_PHONE = 502
QTE_CLIENT_ADDRESS = 503
QTE_CLIENT_BANK = 504
QTE_CLIENT_VAT = 505
QTE_DATE = 506
QTE_CALENDAR = 507
QTE_ITEM_NAME = 508
QTE_ITEM_PRICE = 509
QTE_ADD_MORE = 510
QTE_CURRENCY = 511
QTE_CURRENCY_CUSTOM = 512
QTE_VALID_UNTIL = 513
QTE_VALID_CALENDAR = 514
QTE_VAT_RATE = 515

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
                    lang = _get_lang(context, user.id) if user is not None else "en"
                    reply_markup = (
                        keyboards.main_menu_keyboard(lang=lang)
                        if has_prof
                        else ReplyKeyboardRemove()
                    )
                    await chat.send_message(
                        strings.get_string("RESTARTED", lang),
                        reply_markup=reply_markup,
                    )
            except Exception:
                logger.exception("Failed sending error message to user")
            return ConversationHandler.END

    return wrapper


def _exact(text: str) -> str:
    """Regex matching exactly `text` (used for reply-keyboard buttons)."""
    return f"^{re.escape(text)}$"


def _bilingual_regex(key: str) -> "re.Pattern[str]":
    """Compile a regex that matches the given string key in BOTH languages."""
    en = strings.get_string(key, "en")
    ru = strings.get_string(key, "ru") or en
    return re.compile(r"^(?:" + re.escape(en) + r"|" + re.escape(ru) + r")$")


def _get_lang(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    """Return the active language code ('en' or 'ru') for this user.

    Checks the in-progress onboarding draft first (so the language
    picked on the first step is honored before the profile is saved),
    then falls back to the persisted profile, then to 'en'.
    """
    try:
        ob_lang = (context.user_data.get("onboarding") or {}).get("language") \
            if context is not None and context.user_data is not None else None
    except Exception:
        ob_lang = None
    if ob_lang in ("en", "ru"):
        return ob_lang
    profile = profile_manager.get_profile(user_id)
    lang = (profile or {}).get("language", "en")
    return lang if lang in ("en", "ru") else "en"


# Currency rendering (chat-side)
_CURRENCY_SYMBOLS = {
    "EUR": "\u20ac",
    "USD": "$",
    "KZT": "\u20b8",
    "RUB": "\u20bd",
}


def _format_money(amount: float | int, currency: str = "EUR") -> str:
    """Format an amount with the given currency for chat messages."""
    code = (currency or "EUR").upper()
    symbol = _CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol}{amount:,.2f}"
    return f"{code} {amount:,.2f}"


# Maps a currency reply-keyboard button label to its ISO code.
# Built at import time so BOTH the English and Russian button labels
# resolve to the same ISO code — the user can be on either UI language
# and tap the same button.
_CURRENCY_BUTTON_CODES = {}
for _lang in ("en", "ru"):
    _CURRENCY_BUTTON_CODES[strings.get_string("BTN_CURRENCY_EUR", _lang)] = "EUR"
    _CURRENCY_BUTTON_CODES[strings.get_string("BTN_CURRENCY_USD", _lang)] = "USD"
    _CURRENCY_BUTTON_CODES[strings.get_string("BTN_CURRENCY_KZT", _lang)] = "KZT"
    _CURRENCY_BUTTON_CODES[strings.get_string("BTN_CURRENCY_RUB", _lang)] = "RUB"


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


def _parse_vat_rate_input(text: str) -> float:
    """Parse a VAT-rate string into a float percentage in [0, 100].

    Accepts "21", "21%", "5.5", "5,5". Raises ValueError("range") if out
    of bounds, ValueError("not_number") if unparseable.
    """
    cleaned = text.strip().replace("%", "").replace(" ", "").replace(",", ".")
    if not cleaned:
        raise ValueError("not_number")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError("not_number") from exc
    if value < 0 or value > 100:
        raise ValueError("range")
    return round(value, 2)


def _fmt_rate(rate: float | int) -> str:
    """Render a VAT percentage without a trailing .0 (mirrors keyboards._fmt_rate)."""
    try:
        return f"{float(rate):g}"
    except (TypeError, ValueError):
        return "0"


def _format_invoice_summary(
    items: list[dict[str, Any]], currency: str = "EUR", lang: str = "en",
) -> str:
    """Render the running invoice summary block (header + lines + total)."""
    lines: list[str] = [strings.get_string("CURRENT_INVOICE_HEADER", lang), ""]
    display_items = items
    if len(items) > 20:
        display_items = items[-15:]
        lines.append(f"[Showing last 15 items of {len(items)}]")
        lines.append("")
    for item in display_items:
        lines.append(f"{item['name']} \u2014 {_format_money(float(item['price']), currency)}")
    total = sum(float(item["price"]) for item in items)
    lines.append("")
    lines.append(f"{strings.get_string('TOTAL_LABEL', lang)} {_format_money(total, currency)}")
    return "\n".join(lines)


def _render_profile_summary(profile: dict[str, Any], lang: str = "en") -> str:
    """Render a profile block for both the post-onboarding confirmation
    and the profile-edit screen."""
    email_value = (profile.get("email") or "").strip() or "\u2014"
    vat_value = (profile.get("vat_number") or "").strip() or "\u2014"
    vat_rate_value = _fmt_rate(profile.get("default_vat_rate", 0.0) or 0.0)
    return (
        f"{strings.get_string('PROFILE_HEADER', lang)}\n"
        f"{strings.get_string('ORGANIZATION_LABEL', lang)} {profile.get('org_name', '')}\n"
        f"{strings.get_string('PHONE_LABEL', lang)} {profile.get('phone', '')}\n"
        f"{strings.get_string('EMAIL_LABEL', lang)} {email_value}\n"
        f"{strings.get_string('VAT_LABEL', lang)} {vat_value}\n"
        f"{strings.get_string('ACCOUNT_LABEL', lang)} {profile.get('iban', '')}\n"
        f"{strings.get_string('REFERENCES_LABEL', lang)} {profile.get('reference_style', '')}\n"
        f"{strings.get_string('VAT_RATE_LABEL', lang)} {vat_rate_value}%"
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
        "vat_rate": 0.0,
        "client_saved": False,
        "client_details": {
            "phone": None,
            "address": None,
            "bank": None,
            "vat": None,
        },
    }


def _after_item_keyboard(draft: dict[str, Any], lang: str = "en"):
    """Pick the right 'what's next' keyboard based on draft state."""
    currency = (draft or {}).get("currency", "EUR")
    vat_rate = float((draft or {}).get("vat_rate", 0.0) or 0.0)
    if (draft or {}).get("client_saved"):
        return keyboards.invoice_after_item_keyboard_saved(
            currency=currency, lang=lang, vat_rate=vat_rate,
        )
    return keyboards.invoice_after_item_keyboard(
        currency=currency, lang=lang, vat_rate=vat_rate,
    )


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

    if flow not in (keyboards.CAL_FLOW_INVOICE_DATE, keyboards.CAL_FLOW_DUE_DATE,
                    keyboards.CAL_FLOW_QUOTE_DATE, keyboards.CAL_FLOW_QUOTE_VALID):
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
    query, year: int, month: int, *, flow: str, lang: str = "en",
) -> None:
    """Re-render the calendar message in place for the given flow."""
    min_date, max_date = _cal_bounds()
    try:
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                year, month,
                flow=flow,
                lang=lang,
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

    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"

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
        await _render_calendar(query, new_year, new_month, flow=expected_flow, lang=lang)
        return state_on_continue

    if cb.action == keyboards.CAL_ACTION_NEXT:
        assert cb.year is not None and cb.month is not None
        new_year, new_month = _next_month(cb.year, cb.month)
        if _first_day_of_month(new_year, new_month) > max_date:
            await _safe_ack(query, "Already at the latest month.")
            return state_on_continue
        await _render_calendar(query, new_year, new_month, flow=expected_flow, lang=lang)
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
            summary = _format_invoice_summary(items, currency, lang=lang)
            await update.effective_chat.send_message(
                f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
                reply_markup=_after_item_keyboard(draft, lang=lang),
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
        lang = _get_lang(context, user_id)
        await update.message.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    context.user_data["onboarding"] = {}
    # At this point we have no language yet — show the bilingual
    # welcome in English (default) then the language picker.
    await update.message.reply_text(
        f"{strings.get_string('WELCOME', 'en')}\n\n{strings.get_string('PROFILE_INTRO', 'en')}",
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        "\U0001f310 Please choose your language / Пожалуйста, выберите язык:",
        reply_markup=keyboards.language_keyboard(),
    )
    return ONBOARD_LANGUAGE


@_handler_safe
async def onboard_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle the language selection step."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                "\U0001f310 Please choose your language / Пожалуйста, выберите язык:",
                reply_markup=keyboards.language_keyboard(),
            )
        return ONBOARD_LANGUAGE

    text = msg.text.strip()

    if text == strings.get_string("BTN_LANG_RU", "ru") or text == strings.get_string("BTN_LANG_RU", "en"):
        lang = "ru"
    elif text == strings.get_string("BTN_LANG_EN", "en") or text == strings.get_string("BTN_LANG_EN", "ru"):
        lang = "en"
    else:
        await msg.reply_text(
            "\U0001f310 Please choose your language / Пожалуйста, выберите язык:",
            reply_markup=keyboards.language_keyboard(),
        )
        return ONBOARD_LANGUAGE

    context.user_data.setdefault("onboarding", {})["language"] = lang
    await msg.reply_text(
        strings.get_string("ASK_ORG", lang),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_ORG


@_handler_safe
async def onboard_org(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return ONBOARD_ORG

    text = msg.text
    stripped = text.strip()
    if not stripped:
        await msg.reply_text(strings.get_string("ERR_EMPTY", lang))
        return ONBOARD_ORG
    if len(text) < 2:
        await msg.reply_text(strings.get_string("ERR_SHORT_TEXT", lang))
        return ONBOARD_ORG
    if len(text) > 100:
        await msg.reply_text(strings.get_string("ERR_LONG_TEXT", lang).format(n=100))
        return ONBOARD_ORG

    context.user_data.setdefault("onboarding", {})["org_name"] = stripped
    await msg.reply_text(
        strings.get_string("ASK_PHONE", lang),
        reply_markup=keyboards.phone_keyboard(lang=lang),
    )
    return ONBOARD_PHONE


@_handler_safe
async def onboard_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)

    # Accept a Telegram-shared contact in place of typed text.
    if msg is not None and msg.contact is not None:
        phone = msg.contact.phone_number or ""
        text = phone
    elif msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_PHONE", lang),
                reply_markup=keyboards.phone_keyboard(lang=lang),
            )
        return ONBOARD_PHONE
    else:
        text = msg.text

    if text == strings.get_string("BTN_CANCEL", lang):
        return await onboard_cancel_or_restart(update, context)

    if len(text) < 3 or len(text) > 30:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_PHONE", lang),
            reply_markup=keyboards.phone_keyboard(lang=lang),
        )
        return ONBOARD_PHONE

    context.user_data.setdefault("onboarding", {})["phone"] = text
    await msg.reply_text(
        strings.get_string("ASK_EMAIL", lang),
        reply_markup=keyboards.email_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return ONBOARD_EMAIL


@_handler_safe
async def onboard_email(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_EMAIL", lang),
                reply_markup=keyboards.email_keyboard(lang=lang),
            )
        return ONBOARD_EMAIL

    text = msg.text.strip()

    if text == strings.get_string("BTN_SKIP_EMAIL", lang):
        context.user_data.setdefault("onboarding", {})["email"] = ""
        await msg.reply_text(
            strings.get_string("ASK_VAT", lang),
            reply_markup=keyboards.vat_keyboard(lang=lang),
            parse_mode="Markdown",
        )
        return ONBOARD_VAT

    if not _is_valid_email(text):
        await msg.reply_text(
            strings.get_string("ERR_INVALID_EMAIL", lang),
            reply_markup=keyboards.email_keyboard(lang=lang),
        )
        return ONBOARD_EMAIL

    context.user_data.setdefault("onboarding", {})["email"] = text
    await msg.reply_text(
        strings.get_string("ASK_VAT", lang),
        reply_markup=keyboards.vat_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return ONBOARD_VAT


@_handler_safe
async def onboard_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT", lang),
                reply_markup=keyboards.vat_keyboard(lang=lang),
            )
        return ONBOARD_VAT

    text = msg.text.strip()

    if text == strings.get_string("BTN_SKIP_VAT", lang):
        context.user_data.setdefault("onboarding", {})["vat_number"] = ""
        await msg.reply_text(
            strings.get_string("ASK_ACCOUNT", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ONBOARD_ACCOUNT

    if len(text) < 3 or len(text) > 20:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_VAT", lang),
            reply_markup=keyboards.vat_keyboard(lang=lang),
        )
        return ONBOARD_VAT

    context.user_data.setdefault("onboarding", {})["vat_number"] = text
    await msg.reply_text(
        strings.get_string("ASK_ACCOUNT", lang),
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_ACCOUNT


@_handler_safe
async def onboard_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_ACCOUNT", lang))
        return ONBOARD_ACCOUNT

    text = msg.text.strip()
    if len(text) < 5 or len(text) > 40:
        await msg.reply_text(strings.get_string("ERR_INVALID_ACCOUNT", lang))
        return ONBOARD_ACCOUNT

    context.user_data.setdefault("onboarding", {})["iban"] = text
    await msg.reply_text(
        strings.get_string("ASK_REFERENCES", lang),
        reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
    )
    return ONBOARD_REFERENCES


@_handler_safe
async def onboard_references(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
            )
        return ONBOARD_REFERENCES

    text = msg.text.strip()
    if text == strings.get_string("BTN_REF_STANDARD", lang):
        reference_style = "Standard"
    elif text == strings.get_string("BTN_REF_NONE", lang):
        reference_style = "None"
    else:
        await msg.reply_text(
            strings.get_string("ERR_WRONG_BUTTON", lang),
            reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
        )
        return ONBOARD_REFERENCES

    # Stash the choice in the draft and move on to the default VAT rate.
    # Profile creation happens at the end of the currency step.
    context.user_data.setdefault("onboarding", {})["reference_style"] = reference_style

    await msg.reply_text(
        strings.get_string("ASK_VAT_RATE", lang),
        reply_markup=keyboards.vat_rate_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return ONBOARD_VAT_RATE


@_handler_safe
async def onboard_vat_rate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Onboarding — capture the default VAT rate, then ask for currency."""
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT_RATE", lang),
                reply_markup=keyboards.vat_rate_keyboard(lang=lang),
            )
        return ONBOARD_VAT_RATE

    text = msg.text.strip()
    draft = context.user_data.setdefault("onboarding", {})

    if text == strings.get_string("BTN_CANCEL", lang):
        return await onboard_cancel_or_restart(update, context)

    if text == strings.get_string("BTN_VAT_RATE_SKIP", lang):
        draft["default_vat_rate"] = 0.0
    else:
        try:
            draft["default_vat_rate"] = _parse_vat_rate_input(text)
        except ValueError:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT_RATE", lang),
                reply_markup=keyboards.vat_rate_keyboard(lang=lang),
            )
            return ONBOARD_VAT_RATE

    await msg.reply_text(
        strings.get_string("ASK_CURRENCY_BASE", lang),
        reply_markup=keyboards.currency_picker_keyboard(for_onboarding=True, lang=lang),
    )
    return ONBOARD_CURRENCY


@_handler_safe
async def onboard_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_CURRENCY", lang),
                reply_markup=keyboards.currency_picker_keyboard(for_onboarding=True, lang=lang),
            )
        return ONBOARD_CURRENCY

    text = msg.text.strip()
    draft = context.user_data.setdefault("onboarding", {})

    # Cancel during onboarding -> restart the whole flow (consistent
    # with onboard_cancel_or_restart elsewhere).
    if text == strings.get_string("BTN_CANCEL", lang):
        return await onboard_cancel_or_restart(update, context)

    # 'Other' tap -> prompt for a typed code; stay in the same state.
    # ERR_INVALID_CURRENCY already reads as a useful prompt ("Please
    # enter a 2-4 letter currency code, e.g. CHF").
    if text == strings.get_string("BTN_CURRENCY_OTHER", lang):
        await msg.reply_text(
            strings.get_string("ASK_CURRENCY_CUSTOM", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ONBOARD_CURRENCY

    # Quick-pick: map a button label to an ISO code.
    code = _CURRENCY_BUTTON_CODES.get(text)

    # Otherwise treat the message as a custom 2-4 letter code (this
    # branch handles whatever the user types after tapping 'Other').
    if code is None:
        upper = text.upper()
        if 2 <= len(upper) <= 4 and upper.isalpha():
            code = upper

    if code is None:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_CURRENCY", lang),
            reply_markup=keyboards.currency_picker_keyboard(for_onboarding=True, lang=lang),
        )
        return ONBOARD_CURRENCY

    draft["currency"] = code

    # === Persist the profile ===
    user_id = update.effective_user.id
    reference_style = draft.get("reference_style", "Standard")
    vat_rate = float(draft.get("default_vat_rate", 0.0) or 0.0)
    try:
        profile_manager.create_profile(
            user_id,
            org_name=draft["org_name"],
            phone=draft["phone"],
            iban=draft["iban"],
            reference_style=reference_style,
            email=draft.get("email", ""),
            vat_number=draft.get("vat_number", ""),
            currency=code,
            language=draft.get("language", "en"),
            default_vat_rate=vat_rate,
        )
    except (KeyError, OSError):
        logger.exception(
            "Failed to persist new profile for user_id=%s", user_id
        )
        await msg.reply_text(
            strings.get_string("RESTARTED", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        context.user_data.pop("onboarding", None)
        return ConversationHandler.END

    # Build the confirmation message — same shape as the old
    # onboard_references summary, plus a Currency line.
    email_value = (draft.get("email") or "").strip()
    vat_value = (draft.get("vat_number") or "").strip()
    email_line = (
        f"{strings.get_string('EMAIL_LABEL', lang)} {email_value}\n"
        if email_value else ""
    )
    vat_line = (
        f"{strings.get_string('VAT_LABEL', lang)} {vat_value}\n"
        if vat_value else ""
    )
    confirmation = (
        f"{strings.get_string('PROFILE_CREATED_HEADER', lang)}\n\n"
        f"{strings.get_string('PROFILE_DETAILS_LABEL', lang)}\n"
        f"{strings.get_string('ORGANIZATION_LABEL', lang)} {draft['org_name']}\n"
        f"{strings.get_string('PHONE_LABEL', lang)} {draft['phone']}\n"
        f"{email_line}"
        f"{vat_line}"
        f"{strings.get_string('ACCOUNT_LABEL', lang)} {draft['iban']}\n"
        f"{strings.get_string('REFERENCES_LABEL', lang)} {reference_style}\n"
        f"{strings.get_string('CURRENCY_LABEL', lang)} {code}\n"
        f"{strings.get_string('VAT_RATE_LABEL', lang)} {_fmt_rate(vat_rate)}%\n\n"
        f"{strings.get_string('EDIT_HINT', lang)}"
    )
    await msg.reply_text(
        confirmation,
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
    )
    context.user_data.pop("onboarding", None)
    return ConversationHandler.END


@_handler_safe
async def onboard_cancel_or_restart(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Fallback for /cancel and /start while mid-onboarding."""
    lang = _get_lang(context, update.effective_user.id)
    context.user_data["onboarding"] = {}
    await update.message.reply_text(
        strings.get_string("MID_FLOW_RESTART_PROMPT", lang),
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        "\U0001f310 Please choose your language / Пожалуйста, выберите язык:",
        reply_markup=keyboards.language_keyboard(),
    )
    return ONBOARD_LANGUAGE


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
    lang = _get_lang(context, user_id)
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.get_string("RESTARTED", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    profile = profile_manager.get_profile(user_id) or {}
    default_currency = str(
        profile.get("currency") or profile_manager.CURRENCY_DEFAULT
    ).strip().upper() or profile_manager.CURRENCY_DEFAULT

    context.user_data["invoice"] = _new_invoice_draft()
    context.user_data["invoice"]["currency"] = default_currency
    context.user_data["invoice"]["vat_rate"] = float(
        profile.get("default_vat_rate", 0.0) or 0.0
    )

    saved_clients = profile_manager.get_saved_clients(user_id)
    await update.message.reply_text(
        strings.get_string("ASK_CLIENT", lang),
        reply_markup=keyboards.invoice_client_keyboard(
            saved_clients=saved_clients, lang=lang,
        ),
    )
    return INV_CLIENT


# Backwards-compatible alias.
invoice_start = invoice_start_entry


async def _ask_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send the date prompt and move into INV_DATE."""
    chat = update.effective_chat
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    await chat.send_message(
        strings.get_string("ASK_DATE", lang),
        reply_markup=keyboards.invoice_date_keyboard(lang=lang),
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
    lang = _get_lang(context, user_id)
    draft = context.user_data.get("invoice", {})
    items = draft.get("items", [])

    if not items:
        await chat.send_message(
            "Please add at least one item.",
            reply_markup=keyboards.invoice_item_keyboard(lang=lang),
        )
        return INV_ITEM_NAME

    profile = profile_manager.get_profile(user_id)
    if not profile:
        await chat.send_message(strings.get_string("ERR_PDF_FAILURE", lang))
        context.user_data.pop("invoice", None)
        await chat.send_message(
            strings.get_string("RESTARTED", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    status_msg = await chat.send_message(strings.get_string("GENERATING_PDF", lang))

    next_number = int(profile.get("last_invoice_number", 0)) + 1
    invoice_date_value: date = draft["date"]
    client_name = draft.get("client_name")
    currency = str(draft.get("currency") or "EUR").upper()
    due_date_value = draft.get("due_date")
    client_details = _client_details_for_pdf(draft)
    vat_rate_pct = float(draft.get("vat_rate", 0.0) or 0.0)
    # PDF's _draw_totals expects the rate as a decimal (0.21 == 21%).
    tax_rate_decimal = (vat_rate_pct / 100.0) if vat_rate_pct > 0 else None

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
            tax_rate=tax_rate_decimal,
        )
    except Exception:
        logger.exception("PDF generation failed for user_id=%s", user_id)
        await _safe_delete(status_msg)
        await chat.send_message(
            strings.get_string("ERR_PDF_FAILURE", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
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
        f"{strings.get_string('INVOICE_DONE', lang).format(number=f'{committed_number:05d}')}\n\n"
        f"{strings.get_string('STORAGE_HINT', lang)}"
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
            strings.get_string("ERR_PDF_FAILURE", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
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
                due_date_value if isinstance(due_date_value, str)
                else (due_date_value.strftime("%d.%m.%Y") if due_date_value else None)
            ),
            "sent_at": datetime.now().isoformat(timespec="seconds"),
            "paid": False,
            "reference": reference,
            # --- added for auto-receipts (Feature 2) ---
            "items": [dict(i) for i in items],          # [{"name","price"}, ...]
            "tax_rate": vat_rate_pct if vat_rate_pct > 0 else None,  # stored as percentage
            "client_details": client_details or None,   # {"phone","address","bank","vat"}
        }
        profile_manager.record_invoice(user_id, record)
    except Exception:
        logger.exception(
            "Could not record invoice #%05d to tracking history for user_id=%s",
            committed_number, user_id,
        )

    # If this invoice was created by converting a quote, stamp the invoice
    # number back onto that quote's record (it was already marked Converted
    # at conversion time, so this just records the link).
    from_quote = draft.get("from_quote_number")
    if from_quote is not None:
        try:
            quotes = profile_manager.get_quotes(user_id)
            for _q in quotes:
                if int(_q.get("number", -1)) == int(from_quote):
                    _q["converted_invoice_number"] = int(committed_number)
                    break
            profile_manager.update_profile(user_id, quotes=quotes)
        except Exception:
            logger.exception("Could not stamp invoice # onto quote Q-%s", from_quote)

    # Bug 2 — Skip the intermediate "All done / Create another" menu;
    # return straight to the main menu so the bot is immediately usable.
    context.user_data.pop("invoice", None)
    profile_after = profile_manager.get_profile(user_id) or {}
    await chat.send_message(
        strings.get_string("WELCOME_BACK", lang).format(
            org_name=profile_after.get("org_name", "")
        ),
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
    )
    return ConversationHandler.END


@_handler_safe
async def invoice_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return INV_CLIENT

    text = msg.text

    if text.strip() == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text.strip() == strings.get_string("BTN_NO_NAME", lang):
        context.user_data.setdefault("invoice", _new_invoice_draft())["client_name"] = None
        return await _ask_date(update, context)

    stripped = text.strip()
    if not stripped:
        await msg.reply_text(strings.get_string("ERR_EMPTY", lang))
        return INV_CLIENT
    if len(text) < 2:
        await msg.reply_text(strings.get_string("ERR_SHORT_TEXT", lang))
        return INV_CLIENT
    if len(text) > 100:
        await msg.reply_text(strings.get_string("ERR_LONG_TEXT", lang).format(n=100))
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
        strings.get_string("ASK_CLIENT_DETAILS_CHOICE", lang),
        reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
    )
    return INV_CLIENT_DETAILS_CHOICE


# --- optional client-details sub-flow --------------------------------------

@_handler_safe
async def invoice_client_details_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
            )
        return INV_CLIENT_DETAILS_CHOICE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_ADD_CLIENT_DETAILS", lang):
        await msg.reply_text(
            strings.get_string("ASK_CLIENT_PHONE", lang),
            reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            parse_mode="Markdown",
        )
        return INV_CLIENT_PHONE

    if text == strings.get_string("BTN_SKIP_CLIENT_DETAILS", lang):
        return await _ask_date(update, context)

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
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
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return INV_CLIENT_PHONE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_client_detail(context, "phone", None)
    else:
        if len(text) < 3 or len(text) > 30:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_PHONE", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return INV_CLIENT_PHONE
        _save_client_detail(context, "phone", text)

    await msg.reply_text(
        strings.get_string("ASK_CLIENT_ADDRESS", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return INV_CLIENT_ADDRESS


@_handler_safe
async def invoice_client_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return INV_CLIENT_ADDRESS

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_client_detail(context, "address", None)
    else:
        if len(text) < 3 or len(text) > 200:
            await msg.reply_text(
                strings.get_string("ERR_LONG_TEXT", lang).format(n=200)
                if len(text) > 200
                else strings.get_string("ERR_SHORT_TEXT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return INV_CLIENT_ADDRESS
        _save_client_detail(context, "address", text)

    await msg.reply_text(
        strings.get_string("ASK_CLIENT_BANK", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return INV_CLIENT_BANK


@_handler_safe
async def invoice_client_bank(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return INV_CLIENT_BANK

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_client_detail(context, "bank", None)
    else:
        if len(text) < 5 or len(text) > 40:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_ACCOUNT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return INV_CLIENT_BANK
        _save_client_detail(context, "bank", text)

    await msg.reply_text(
        strings.get_string("ASK_CLIENT_VAT", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return INV_CLIENT_VAT


@_handler_safe
async def invoice_client_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return INV_CLIENT_VAT

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_client_detail(context, "vat", None)
    else:
        if len(text) < 3 or len(text) > 20:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
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
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.invoice_date_keyboard(lang=lang),
            )
        return INV_DATE

    text = msg.text.strip()
    today = date.today()

    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_TODAY", lang):
        context.user_data.setdefault("invoice", _new_invoice_draft())["date"] = today
        return await _ask_item_name(update, context)

    if text == strings.get_string("BTN_YESTERDAY", lang):
        context.user_data.setdefault("invoice", _new_invoice_draft())["date"] = today - timedelta(days=1)
        return await _ask_item_name(update, context)

    if text == strings.get_string("BTN_PICK_DATE", lang):
        min_date, max_date = _cal_bounds()
        await msg.reply_text(
            strings.get_string("CALENDAR_PROMPT", lang),
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_INVOICE_DATE,
                lang=lang,
                min_date=min_date, max_date=max_date,
            ),
        )
        return INV_CALENDAR

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.invoice_date_keyboard(lang=lang),
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
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    await chat.send_message(
        strings.get_string("ASK_ITEM_NAME", lang),
        reply_markup=keyboards.invoice_item_keyboard(lang=lang),
    )
    return INV_ITEM_NAME


@_handler_safe
async def invoice_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return INV_ITEM_NAME

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if not text:
        await msg.reply_text(strings.get_string("ERR_EMPTY", lang))
        return INV_ITEM_NAME
    if len(text) > 200:
        await msg.reply_text(strings.get_string("ERR_LONG_TEXT", lang).format(n=200))
        return INV_ITEM_NAME

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["pending_item_name"] = text
    # Bug 1 — Format ASK_ITEM_PRICE with the just-captured item name so
    # the user sees the actual name (bold) instead of the literal
    # placeholder "{item_name}". parse_mode="Markdown" is required for
    # the surrounding asterisks to render as bold.
    await msg.reply_text(
        strings.get_string("ASK_ITEM_PRICE", lang).format(item_name=text),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return INV_ITEM_PRICE


@_handler_safe
async def invoice_item_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_PRICE", lang))
        return INV_ITEM_PRICE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    try:
        price = _parse_price(text)
    except ValueError as exc:
        err_code = exc.args[0] if exc.args else "not_number"
        if err_code == "zero_negative":
            await msg.reply_text(strings.get_string("ERR_ZERO_NEGATIVE_PRICE", lang))
        else:
            await msg.reply_text(strings.get_string("ERR_INVALID_PRICE", lang))
        return INV_ITEM_PRICE

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    item_name = draft.pop("pending_item_name", None) or "Item"
    draft.setdefault("items", []).append({"name": item_name, "price": price})

    currency = draft.get("currency", "EUR")
    summary = _format_invoice_summary(draft["items"], currency, lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            draft = context.user_data.get("invoice", {})
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=_after_item_keyboard(draft, lang=lang),
            )
        return INV_ADD_MORE

    text = msg.text.strip()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    if text == strings.get_string("BTN_ADD_ANOTHER", lang):
        return await _ask_item_name(update, context)

    if text == strings.get_string("BTN_CREATE_INVOICE_CONFIRM", lang):
        return await _generate_and_send_pdf(update, context)

    if text == strings.get_string("BTN_DUE_DATE", lang):
        await msg.reply_text(
            strings.get_string("ASK_DUE_DATE", lang),
            reply_markup=keyboards.due_date_keyboard(lang=lang),
        )
        return INV_DUE_DATE

    # The change-currency button label is prefix + " (CURRENCY)" so we
    # match against the localized prefix in either language.
    if text.startswith(strings.get_string("BTN_CHANGE_CURRENCY", lang)):
        await msg.reply_text(
            strings.get_string("ASK_CURRENCY", lang),
            reply_markup=keyboards.currency_picker_keyboard(lang=lang),
        )
        return INV_CURRENCY

    # The VAT button label is prefix + " (N%)"; match the localized prefix.
    if text.startswith(strings.get_string("BTN_SET_VAT", lang)):
        await msg.reply_text(
            strings.get_string("ASK_INVOICE_VAT_RATE", lang),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
        return INV_VAT_RATE

    if text in (
        strings.get_string("BTN_SAVE_CLIENT", lang),
        strings.get_string("CLIENT_SAVED_INLINE", lang),
    ):
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
                    strings.get_string("CLIENT_SAVED", lang),
                    reply_markup=_after_item_keyboard(draft, lang=lang),
                )
            except Exception:
                logger.exception("Failed to save client for user_id=%s", user_id)
                await msg.reply_text(strings.get_string("ERR_PDF_FAILURE", lang))
        return INV_ADD_MORE

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


# =============================================================================
# === DUE DATE ================================================================
# =============================================================================

@_handler_safe
async def invoice_vat_rate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Per-invoice VAT override entered from the after-items screen."""
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_VAT_RATE", lang))
        return INV_VAT_RATE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    try:
        rate = _parse_vat_rate_input(text)
    except ValueError:
        await msg.reply_text(strings.get_string("ERR_INVALID_VAT_RATE", lang))
        return INV_VAT_RATE

    draft["vat_rate"] = rate

    currency = draft.get("currency", "EUR")
    summary = _format_invoice_summary(draft.get("items", []), currency, lang=lang)
    await msg.reply_text(
        strings.get_string("INVOICE_VAT_SET", lang).format(rate=_fmt_rate(rate)),
    )
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_due_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.due_date_keyboard(lang=lang),
            )
        return INV_DUE_DATE

    text = msg.text.strip()
    today = date.today()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    async def _back_to_summary() -> int:
        items = draft.get("items", [])
        currency = draft.get("currency", "EUR")
        summary = _format_invoice_summary(items, currency, lang=lang)
        await msg.reply_text(
            f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
            reply_markup=_after_item_keyboard(draft, lang=lang),
        )
        return INV_ADD_MORE

    if text == strings.get_string("BTN_BACK", lang):
        return await _back_to_summary()

    if text == strings.get_string("BTN_DUE_NET30", lang):
        draft["due_date"] = today + timedelta(days=30)
        return await _back_to_summary()

    if text == strings.get_string("BTN_DUE_NET15", lang):
        draft["due_date"] = today + timedelta(days=14)
        return await _back_to_summary()

    if text == strings.get_string("BTN_DUE_ON_RECEIPT", lang):
        draft["due_date"] = "On receipt"
        return await _back_to_summary()

    if text == strings.get_string("BTN_DUE_CUSTOM", lang):
        min_date, max_date = _cal_bounds()
        await msg.reply_text(
            strings.get_string("CALENDAR_PROMPT", lang),
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_DUE_DATE,
                lang=lang,
                min_date=min_date, max_date=max_date,
            ),
        )
        return INV_DUE_DATE_CALENDAR

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.due_date_keyboard(lang=lang),
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
# === CURRENCY ================================================================
# =============================================================================

@_handler_safe
async def invoice_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.currency_picker_keyboard(lang=lang),
            )
        return INV_CURRENCY

    text = msg.text.strip()

    if text == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.get_string("BTN_BACK", lang):
        items = draft.get("items", [])
        currency = draft.get("currency", "EUR")
        summary = _format_invoice_summary(items, currency, lang=lang)
        await msg.reply_text(
            f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
            reply_markup=_after_item_keyboard(draft, lang=lang),
        )
        return INV_ADD_MORE

    if text == strings.get_string("BTN_CURRENCY_OTHER", lang):
        await msg.reply_text(
            strings.get_string("ASK_CURRENCY_CUSTOM", lang),
            reply_markup=ForceReply(selective=True),
        )
        return INV_CURRENCY_CUSTOM

    code = _CURRENCY_BUTTON_CODES.get(text)
    if code is None:
        await msg.reply_text(
            strings.get_string("ERR_WRONG_BUTTON", lang),
            reply_markup=keyboards.currency_picker_keyboard(lang=lang),
        )
        return INV_CURRENCY

    draft["currency"] = code
    items = draft.get("items", [])
    summary = _format_invoice_summary(items, code, lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_currency_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_CURRENCY", lang))
        return INV_CURRENCY_CUSTOM

    raw = msg.text.strip()
    if raw == strings.get_string("BTN_CANCEL", lang):
        return await invoice_cancel(update, context)

    text = raw.upper()
    if not (2 <= len(text) <= 4) or not text.isalpha():
        await msg.reply_text(strings.get_string("ERR_INVALID_CURRENCY", lang))
        return INV_CURRENCY_CUSTOM

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["currency"] = text
    items = draft.get("items", [])
    summary = _format_invoice_summary(items, text, lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


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
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.invoice_after_pdf_keyboard(lang=lang),
            )
        return INV_AFTER_PDF

    text = msg.text.strip()

    if text == strings.get_string("BTN_CREATE_ANOTHER", lang):
        return await invoice_start_entry(update, context)

    if text in (
        strings.get_string("BTN_ALL_DONE", lang),
        strings.get_string("BTN_CANCEL", lang),
    ):
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.invoice_after_pdf_keyboard(lang=lang),
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
    lang = _get_lang(context, update.effective_user.id)
    context.user_data.pop("invoice", None)
    await update.effective_chat.send_message(
        strings.get_string("INVOICE_CANCELLED", lang),
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
    )
    return ConversationHandler.END


async def _invoice_cancel_from_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel helper for inline-keyboard (callback query) contexts."""
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    context.user_data.pop("invoice", None)
    await _safe_delete(update.callback_query.message if update.callback_query else None)
    await update.effective_chat.send_message(
        strings.get_string("INVOICE_CANCELLED", lang),
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
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
    lang = _get_lang(context, user_id)
    profile = profile_manager.get_profile(user_id)
    if not profile:
        await update.message.reply_text(
            strings.get_string("RESTARTED", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    summary = _render_profile_summary(profile, lang=lang)
    await update.message.reply_text(
        f"{summary}\n\n{strings.get_string('EDIT_PROMPT', lang)}",
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return PE_MENU


@_handler_safe
async def profile_edit_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.profile_edit_keyboard(lang=lang),
            )
        return PE_MENU

    text = msg.text.strip()

    if text == strings.get_string("BTN_CANCEL", lang):
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    field_map = {
        strings.get_string("BTN_EDIT_ORG", lang): (PE_NAME, strings.get_string("ASK_ORG", lang)),
        strings.get_string("BTN_EDIT_PHONE", lang): (PE_PHONE, strings.get_string("ASK_PHONE", lang)),
        strings.get_string("BTN_EDIT_EMAIL", lang): (PE_EMAIL, strings.get_string("ASK_EMAIL", lang)),
        strings.get_string("BTN_EDIT_VAT", lang): (PE_VAT, strings.get_string("ASK_VAT", lang)),
        strings.get_string("BTN_EDIT_ACCOUNT", lang): (PE_ACCOUNT, strings.get_string("ASK_ACCOUNT", lang)),
        strings.get_string("BTN_EDIT_REFERENCES", lang): (PE_REFERENCES, strings.get_string("ASK_REFERENCES", lang)),
        strings.get_string("BTN_EDIT_VAT_RATE", lang): (PE_VAT_RATE, strings.get_string("ASK_VAT_RATE", lang)),
    }

    entry = field_map.get(text)
    if entry is None:
        await msg.reply_text(
            strings.get_string("ERR_WRONG_BUTTON", lang),
            reply_markup=keyboards.profile_edit_keyboard(lang=lang),
        )
        return PE_MENU

    next_state, prompt = entry
    if next_state == PE_EMAIL:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.email_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    elif next_state == PE_VAT:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.vat_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    elif next_state == PE_PHONE:
        # Rule 3 — Profile phone edit gets the same Share-contact + Cancel
        # keyboard as the onboarding phone step.
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.phone_keyboard(lang=lang),
        )
    elif next_state == PE_REFERENCES:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
        )
    elif next_state == PE_VAT_RATE:
        await msg.reply_text(
            prompt,
            reply_markup=keyboards.vat_rate_keyboard(lang=lang),
            parse_mode="Markdown",
        )
    else:
        await msg.reply_text(prompt, reply_markup=ReplyKeyboardRemove())
    return next_state


@_handler_safe
async def profile_edit_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return PE_NAME

    text = msg.text.strip()
    if len(text) < 2 or len(text) > 100:
        await msg.reply_text(
            strings.get_string("ERR_LONG_TEXT", lang).format(n=100)
            if len(text) > 100
            else strings.get_string("ERR_SHORT_TEXT", lang)
        )
        return PE_NAME

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, org_name=text)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("ORGANIZATION_LABEL", lang)),
            value=text,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)

    # Rule 3 — Accept a Telegram-shared contact in place of typed text,
    # exactly as if the user had typed their number.
    if msg is not None and msg.contact is not None:
        phone = msg.contact.phone_number or ""
        text = phone
    elif msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_PHONE", lang),
                reply_markup=keyboards.phone_keyboard(lang=lang),
            )
        return PE_PHONE
    else:
        text = msg.text.strip()

    if text == strings.get_string("BTN_CANCEL", lang):
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    if len(text) < 3 or len(text) > 30:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_PHONE", lang),
            reply_markup=keyboards.phone_keyboard(lang=lang),
        )
        return PE_PHONE

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, phone=text)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("PHONE_LABEL", lang)),
            value=text,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_email(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_EMAIL", lang),
                reply_markup=keyboards.email_keyboard(lang=lang),
            )
        return PE_EMAIL

    text = msg.text.strip()
    if text == strings.get_string("BTN_SKIP_EMAIL", lang):
        user_id = update.effective_user.id
        profile_manager.update_profile(user_id, email="")
        await msg.reply_text(
            strings.get_string("FIELD_UPDATED", lang).format(
                field=_label_word(strings.get_string("EMAIL_LABEL", lang)),
                value="(removed)",
            ),
            reply_markup=keyboards.profile_edit_keyboard(lang=lang),
        )
        return PE_MENU

    if not _is_valid_email(text):
        await msg.reply_text(
            strings.get_string("ERR_INVALID_EMAIL", lang),
            reply_markup=keyboards.email_keyboard(lang=lang),
        )
        return PE_EMAIL

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, email=text)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("EMAIL_LABEL", lang)),
            value=text,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT", lang),
                reply_markup=keyboards.vat_keyboard(lang=lang),
            )
        return PE_VAT

    text = msg.text.strip()
    if text == strings.get_string("BTN_SKIP_VAT", lang):
        user_id = update.effective_user.id
        profile_manager.update_profile(user_id, vat_number="")
        await msg.reply_text(
            strings.get_string("FIELD_UPDATED", lang).format(
                field=_label_word(strings.get_string("VAT_LABEL", lang)),
                value="(removed)",
            ),
            reply_markup=keyboards.profile_edit_keyboard(lang=lang),
        )
        return PE_MENU

    if len(text) < 3 or len(text) > 20:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_VAT", lang),
            reply_markup=keyboards.vat_keyboard(lang=lang),
        )
        return PE_VAT

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, vat_number=text)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("VAT_LABEL", lang)),
            value=text,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_account(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_ACCOUNT", lang))
        return PE_ACCOUNT

    text = msg.text.strip()
    if len(text) < 5 or len(text) > 40:
        await msg.reply_text(strings.get_string("ERR_INVALID_ACCOUNT", lang))
        return PE_ACCOUNT

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, iban=text)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("ACCOUNT_LABEL", lang)),
            value=text,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_references(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
            )
        return PE_REFERENCES

    text = msg.text.strip()
    if text == strings.get_string("BTN_REF_STANDARD", lang):
        reference_style = "Standard"
    elif text == strings.get_string("BTN_REF_NONE", lang):
        reference_style = "None"
    else:
        await msg.reply_text(
            strings.get_string("ERR_WRONG_BUTTON", lang),
            reply_markup=keyboards.onboarding_references_keyboard(lang=lang),
        )
        return PE_REFERENCES

    user_id = update.effective_user.id
    profile_manager.update_profile(user_id, reference_style=reference_style)
    await msg.reply_text(
        strings.get_string("FIELD_UPDATED", lang).format(
            field=_label_word(strings.get_string("REFERENCES_LABEL", lang)),
            value=reference_style,
        ),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_vat_rate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Profile edit — update the default VAT rate."""
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT_RATE", lang),
                reply_markup=keyboards.vat_rate_keyboard(lang=lang),
            )
        return PE_VAT_RATE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        # Same cancel-from-edit behaviour as profile_edit_menu.
        profile = profile_manager.get_profile(update.effective_user.id) or {}
        await msg.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    if text == strings.get_string("BTN_VAT_RATE_SKIP", lang):
        rate = 0.0
    else:
        try:
            rate = _parse_vat_rate_input(text)
        except ValueError:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT_RATE", lang),
                reply_markup=keyboards.vat_rate_keyboard(lang=lang),
            )
            return PE_VAT_RATE

    user_id = update.effective_user.id
    profile_manager.update_default_vat_rate(user_id, rate)
    await msg.reply_text(
        strings.get_string("VAT_RATE_SET", lang).format(rate=_fmt_rate(rate)),
        reply_markup=keyboards.profile_edit_keyboard(lang=lang),
    )
    return PE_MENU

@_handler_safe
async def track_invoices_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    invoices = profile_manager.get_invoices(user_id)
    open_invoices = [inv for inv in invoices if not inv.get("paid")]  # pending/overdue

    if not invoices:
        await update.message.reply_text(strings.get_string("NO_INVOICES_YET", lang),
                                        reply_markup=keyboards.main_menu_keyboard(lang=lang))
        return ConversationHandler.END

    if not open_invoices:
        # Everything is paid — offer the historical view instead of an empty list.
        await update.message.reply_text(
            strings.get_string("ALL_INVOICES_PAID", lang),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                strings.get_string("BTN_VIEW_PAID", lang),
                callback_data=keyboards.CB_TRACK_VIEW_PAID)]]))
        return ConversationHandler.END

    lines = [strings.get_string("INVOICE_LIST_HEADER", lang), ""]
    for inv in open_invoices:
        number = f"#{inv.get('number', 0):05d}"
        client = inv.get("client_name") or strings.get_string("NO_CLIENT_LABEL", lang)
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        ref = inv.get("reference") or "\u2014"
        inv_date = inv.get("invoice_date") or "\u2014"
        due = inv.get("due_date") or "\u2014"
        lines.append(
            f"\u23f3 {number} | {client}\n"
            f"   {amount}  |  {strings.get_string('REF_LABEL', lang)} {ref}\n"
            f"   {strings.get_string('DATE_LABEL', lang)} {inv_date}  |  "
            f"{strings.get_string('DUE_LABEL', lang)} {due}")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()

    await update.message.reply_text(
        "\n".join(lines), reply_markup=keyboards.track_open_list_keyboard(lang=lang))
    return ConversationHandler.END


@_handler_safe
async def track_invoices_mark_paid_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    invoices = profile_manager.get_invoices(user_id)
    unpaid = [inv for inv in invoices if not inv.get("paid")]

    if not unpaid:
        await update.message.reply_text(
            strings.get_string("ALL_INVOICES_PAID", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return ConversationHandler.END

    buttons: list[list[InlineKeyboardButton]] = []
    for inv in unpaid:
        number = inv.get("number", 0)
        client = inv.get("client_name") or strings.get_string("NO_CLIENT_LABEL", lang)
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        label = f"#{number:05d} \u00b7 {client} \u00b7 {amount}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"markpaid:{number}")
        ])
    buttons.append([
        InlineKeyboardButton(
            strings.get_string("BTN_BACK_TO_MENU", lang),
            callback_data="markpaid:cancel",
        )
    ])

    await update.message.reply_text(
        strings.get_string("SELECT_INVOICE_TO_MARK", lang),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


async def track_mark_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id) if update.effective_user else "en"
    data = query.data or ""

    if data == "markpaid:cancel":
        await _safe_delete(query.message)
        profile = profile_manager.get_profile(user_id) or {}
        await update.effective_chat.send_message(
            strings.get_string("WELCOME_BACK", lang).format(org_name=profile.get("org_name", "")),
            reply_markup=keyboards.main_menu_keyboard(lang=lang))
        return

    parts = data.split(":", 1)
    if len(parts) != 2:
        return
    try:
        invoice_number = int(parts[1])
    except ValueError:
        return

    # Feature 2: ask HOW it was paid before flipping the flag.
    try:
        await query.edit_message_text(
            strings.get_string("TRACK_ASK_PAYMENT_METHOD", lang),
            reply_markup=keyboards.payment_method_inline_keyboard(invoice_number, lang=lang))
    except Exception:
        await update.effective_chat.send_message(
            strings.get_string("TRACK_ASK_PAYMENT_METHOD", lang),
            reply_markup=keyboards.payment_method_inline_keyboard(invoice_number, lang=lang))


async def track_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles paymethod:<key>:<invoice_number> (Feature 2)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id) if update.effective_user else "en"

    try:
        _, key, num = (query.data or "").split(":", 2)
        invoice_number = int(num)
    except (ValueError, AttributeError):
        return

    if key == "other":
        # No ConversationHandler here — stash and capture in fallback_any_message.
        context.user_data["awaiting_pm_text"] = invoice_number
        try:
            await query.edit_message_text(strings.get_string("RCP_ASK_PAYMENT_OTHER", lang))
        except Exception:
            await update.effective_chat.send_message(
                strings.get_string("RCP_ASK_PAYMENT_OTHER", lang))
        return

    await _safe_delete(query.message)
    await _complete_invoice_payment(update, context, invoice_number, _pm_label(key, lang))


async def _complete_invoice_payment(update, context, invoice_number: int, method_label: str) -> None:
    """Mark paid, generate the auto-receipt, send it. Shared by callback + Other-text."""
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id) if update.effective_user else "en"
    chat = update.effective_chat
    today_str = date.today().strftime("%d.%m.%Y")

    profile_manager.mark_invoice_paid(
        user_id, invoice_number, payment_method=method_label, payment_date=today_str)

    inv = next((i for i in profile_manager.get_invoices(user_id)
                if int(i.get("number", -1)) == invoice_number), None)
    if inv is None:
        await chat.send_message(strings.get_string("ALL_INVOICES_PAID", lang),
                                reply_markup=keyboards.main_menu_keyboard(lang=lang))
        return

    status = await chat.send_message(strings.get_string("TRACK_RECEIPT_GENERATING", lang))
    profile = profile_manager.get_profile(user_id) or {}
    try:
        rcp_number = profile_manager.increment_receipt_number(user_id)
        pdf_path = pdf_generator.generate_receipt_pdf(
            receipt_number=rcp_number,
            date_paid=date.today(),
            profile=profile,
            bill_to={
                "name": inv.get("client_name"),
                "address": (inv.get("client_details") or {}).get("address"),
                "email": (inv.get("client_details") or {}).get("email"),
            },
            items=_invoice_items_to_receipt_items(inv),
            payment_method=method_label,
            payment_date=date.today(),
            currency=str(inv.get("currency", "EUR")),
            invoice_number=invoice_number,
            amount_paid=float(inv.get("amount", 0) or 0),
        )
        await _safe_delete(status)
        with pdf_path.open("rb") as fh:
            await chat.send_document(
                document=fh, filename=pdf_path.name,
                caption=strings.get_string("TRACK_RECEIPT_SENT", lang).format(
                    number=f"RCP-{rcp_number:05d}", invoice=f"{invoice_number:05d}"))
    except Exception:
        logger.exception("Auto-receipt failed for invoice #%05d user_id=%s",
                         invoice_number, user_id)
        await _safe_delete(status)
        await chat.send_message(strings.get_string("TRACK_RECEIPT_FAILED", lang))

    await chat.send_message(
        strings.get_string("WELCOME_BACK", lang).format(org_name=profile.get("org_name", "")),
        reply_markup=keyboards.main_menu_keyboard(lang=lang))

@_handler_safe
async def track_view_paid_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered by the 'View paid invoices' reply button (MessageHandler)."""
    await _render_paid_list(update.effective_chat,
                            update.effective_user.id, context)


async def track_view_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Triggered by the inline 'View paid invoices' button (trackpaid:view)."""
    query = update.callback_query
    await query.answer()
    await _safe_delete(query.message)
    await _render_paid_list(update.effective_chat, update.effective_user.id, context)


async def _render_paid_list(chat, user_id: int, context) -> None:
    lang = _get_lang(context, user_id)
    paid = [inv for inv in profile_manager.get_invoices(user_id) if inv.get("paid")]
    if not paid:
        await chat.send_message(strings.get_string("TRACK_NO_PAID", lang),
                                reply_markup=keyboards.main_menu_keyboard(lang=lang))
        return
    lines = [strings.get_string("TRACK_PAID_HEADER", lang), ""]
    for inv in paid:
        number = f"#{inv.get('number', 0):05d}"
        client = inv.get("client_name") or strings.get_string("NO_CLIENT_LABEL", lang)
        amount = _format_money(float(inv.get("amount", 0)), str(inv.get("currency", "EUR")))
        method = inv.get("payment_method") or "\u2014"
        pdate = inv.get("payment_date") or "\u2014"
        lines.append(f"\u2705 {number} | {client} | {amount}\n   {method} \u00b7 {pdate}")
        lines.append("")
    if lines and lines[-1] == "":
        lines.pop()
    await chat.send_message("\n".join(lines), parse_mode="Markdown",
                            reply_markup=keyboards.main_menu_keyboard(lang=lang))

# =============================================================================
# === FALLBACK ================================================================
# =============================================================================

# Feature 2 — capture the free-text payment method after "Other".
    pending = context.user_data.pop("awaiting_pm_text", None)
    if pending is not None and update.message and update.message.text:
        method = update.message.text.strip() or strings.get_string("PM_OTHER", lang)
        await _complete_invoice_payment(update, context, int(pending), method)
        return

@_handler_safe
async def fallback_any_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Catch-all for messages outside any active conversation."""
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    if profile_manager.has_profile(user_id):
        profile = profile_manager.get_profile(user_id) or {}
        await update.message.reply_text(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
    else:
        await update.message.reply_text(
            strings.get_string("PROMPT_START", lang),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )


# =============================================================================
# === HELP ====================================================================
# =============================================================================

async def _send_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Send the formatted help message with a 'Back to Menu' inline button.

    Shared by the /help command and the ❓ Help reply-keyboard button so
    the two never drift. The reply keyboard (main menu) stays in place
    underneath; the inline button is a convenience that re-shows the
    welcome/menu when tapped.
    """
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    has_prof = profile_manager.has_profile(user_id)

    inline_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton(
            strings.get_string("BTN_HELP_BACK_TO_MENU", lang),
            callback_data=strings.CB_HELP_BACK_TO_MENU,
        )]]
    )

    # First message carries the help text + inline "Back to Menu" button.
    await update.message.reply_text(
        strings.get_string("HELP_TEXT", lang),
        parse_mode="Markdown",
        reply_markup=inline_markup,
    )

    # Make sure the user still has the main-menu reply keyboard available.
    # (An inline keyboard alone can't replace the reply keyboard.)
    if not has_prof:
        await update.message.reply_text(
            strings.get_string("PROMPT_START", lang),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )


@_handler_safe
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/help command — shows the help screen."""
    await _send_help(update, context)


@_handler_safe
async def help_button(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """❓ Help reply-keyboard button — shows the help screen.

    Previously there was no handler bound to this button, so taps fell
    through to fallback_any_message and only re-showed the menu. This
    binds the button to the same help renderer as /help.
    """
    await _send_help(update, context)


@_handler_safe
async def help_back_to_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Inline 'Back to Menu' button beneath the help message."""
    query = update.callback_query
    await _safe_ack(query)
    await _safe_delete(query.message)

    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    chat = update.effective_chat
    if profile_manager.has_profile(user_id):
        profile = profile_manager.get_profile(user_id) or {}
        await chat.send_message(
            strings.get_string("WELCOME_BACK", lang).format(
                org_name=profile.get("org_name", "")
            ),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
    else:
        await chat.send_message(
            strings.get_string("PROMPT_START", lang),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )


# =============================================================================
# === QUOTES (Goal 1) =========================================================
# =============================================================================
#
# A full parallel document type. The creation flow mirrors the invoice
# flow (client + optional details, date, items, currency, VAT, valid-
# until) and reuses every shared helper. Saved quotes live in the user's
# profile and are managed from the "My quotes" screen, where each quote
# can be sent, converted to an invoice, marked accepted, edited, or
# deleted.


def _new_quote_draft() -> dict[str, Any]:
    return {
        "client_name": None,
        "date": None,
        "items": [],
        "pending_item_name": None,
        "currency": "EUR",
        "vat_rate": 0.0,
        "valid_until": None,
        "client_saved": False,
        "client_details": {
            "phone": None,
            "address": None,
            "bank": None,
            "vat": None,
        },
        # When set, this quote draft originated from "Edit" on an existing
        # quote; on create we update that quote in place instead of
        # allocating a new number.
        "editing_number": None,
    }


def _quote_after_item_keyboard(draft: dict[str, Any], lang: str = "en"):
    return keyboards.quote_after_item_keyboard(
        currency=(draft or {}).get("currency", "EUR"),
        lang=lang,
        vat_rate=float((draft or {}).get("vat_rate", 0.0) or 0.0),
        client_saved=bool((draft or {}).get("client_saved")),
    )


def _format_quote_summary(
    items: list[dict[str, Any]], currency: str = "EUR", lang: str = "en",
) -> str:
    lines: list[str] = [strings.get_string("QUOTE_CURRENT_HEADER", lang), ""]
    display_items = items
    if len(items) > 20:
        display_items = items[-15:]
        lines.append(f"[Showing last 15 items of {len(items)}]")
        lines.append("")
    for item in display_items:
        lines.append(
            f"{item['name']} \u2014 {_format_money(float(item['price']), currency)}"
        )
    total = sum(float(item["price"]) for item in items)
    lines.append("")
    lines.append(
        f"{strings.get_string('TOTAL_LABEL', lang)} {_format_money(total, currency)}"
    )
    return "\n".join(lines)


@_handler_safe
async def quote_start_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Quote entry point — initialise draft, seed currency + default VAT."""
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.get_string("RESTARTED", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END

    profile = profile_manager.get_profile(user_id) or {}
    default_currency = str(
        profile.get("currency") or profile_manager.CURRENCY_DEFAULT
    ).strip().upper() or profile_manager.CURRENCY_DEFAULT

    draft = _new_quote_draft()
    draft["currency"] = default_currency
    draft["vat_rate"] = float(profile.get("default_vat_rate", 0.0) or 0.0)
    context.user_data["quote"] = draft

    await update.message.reply_text(
        strings.get_string("QUOTE_ASK_CLIENT", lang),
        reply_markup=keyboards.invoice_client_keyboard(
            saved_clients=profile_manager.get_saved_clients(user_id), lang=lang,
        ),
    )
    return QTE_CLIENT


@_handler_safe
async def quote_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    lang = _get_lang(context, update.effective_user.id)
    context.user_data.pop("quote", None)
    profile = profile_manager.get_profile(update.effective_user.id) or {}
    await update.effective_chat.send_message(
        strings.get_string("QUOTE_CANCELLED", lang),
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
    )
    return ConversationHandler.END


async def _quote_ask_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    await update.effective_chat.send_message(
        strings.get_string("QUOTE_ASK_DATE", lang),
        reply_markup=keyboards.quote_date_keyboard(lang=lang),
    )
    return QTE_DATE


@_handler_safe
async def quote_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return QTE_CLIENT

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)

    if text == strings.get_string("BTN_NO_NAME", lang):
        context.user_data.setdefault("quote", _new_quote_draft())["client_name"] = None
        return await _quote_ask_date(update, context)

    if len(text) < 2:
        await msg.reply_text(strings.get_string("ERR_SHORT_TEXT", lang))
        return QTE_CLIENT
    if len(text) > 100:
        await msg.reply_text(strings.get_string("ERR_LONG_TEXT", lang).format(n=100))
        return QTE_CLIENT

    draft = context.user_data.setdefault("quote", _new_quote_draft())
    draft["client_name"] = text

    user_id = update.effective_user.id
    saved = profile_manager.get_saved_client_by_name(user_id, text)
    if saved is not None:
        draft["client_details"] = {
            "phone": saved.get("phone"),
            "address": saved.get("address"),
            "bank": saved.get("bank"),
            "vat": saved.get("vat"),
        }
        draft["client_saved"] = True
        return await _quote_ask_date(update, context)

    await msg.reply_text(
        strings.get_string("ASK_CLIENT_DETAILS_CHOICE", lang),
        reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
    )
    return QTE_CLIENT_DETAILS_CHOICE


def _save_quote_detail(
    context: ContextTypes.DEFAULT_TYPE, key: str, value: str | None
) -> None:
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    details = draft.setdefault(
        "client_details",
        {"phone": None, "address": None, "bank": None, "vat": None},
    )
    details[key] = value


@_handler_safe
async def quote_client_details_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
            )
        return QTE_CLIENT_DETAILS_CHOICE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_ADD_CLIENT_DETAILS", lang):
        await msg.reply_text(
            strings.get_string("ASK_CLIENT_PHONE", lang),
            reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            parse_mode="Markdown",
        )
        return QTE_CLIENT_PHONE
    if text == strings.get_string("BTN_SKIP_CLIENT_DETAILS", lang):
        return await _quote_ask_date(update, context)

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.client_details_choice_keyboard(lang=lang),
    )
    return QTE_CLIENT_DETAILS_CHOICE


@_handler_safe
async def quote_client_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return QTE_CLIENT_PHONE
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_quote_detail(context, "phone", None)
    else:
        if len(text) < 3 or len(text) > 30:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_PHONE", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return QTE_CLIENT_PHONE
        _save_quote_detail(context, "phone", text)
    await msg.reply_text(
        strings.get_string("ASK_CLIENT_ADDRESS", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return QTE_CLIENT_ADDRESS


@_handler_safe
async def quote_client_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return QTE_CLIENT_ADDRESS
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_quote_detail(context, "address", None)
    else:
        if len(text) < 3 or len(text) > 200:
            await msg.reply_text(
                strings.get_string("ERR_LONG_TEXT", lang).format(n=200)
                if len(text) > 200
                else strings.get_string("ERR_SHORT_TEXT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return QTE_CLIENT_ADDRESS
        _save_quote_detail(context, "address", text)
    await msg.reply_text(
        strings.get_string("ASK_CLIENT_BANK", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return QTE_CLIENT_BANK


@_handler_safe
async def quote_client_bank(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return QTE_CLIENT_BANK
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_quote_detail(context, "bank", None)
    else:
        if len(text) < 5 or len(text) > 40:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_ACCOUNT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return QTE_CLIENT_BANK
        _save_quote_detail(context, "bank", text)
    await msg.reply_text(
        strings.get_string("ASK_CLIENT_VAT", lang),
        reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
        parse_mode="Markdown",
    )
    return QTE_CLIENT_VAT


@_handler_safe
async def quote_client_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
        return QTE_CLIENT_VAT
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_SKIP_DETAIL", lang):
        _save_quote_detail(context, "vat", None)
    else:
        if len(text) < 3 or len(text) > 20:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_VAT", lang),
                reply_markup=keyboards.client_detail_skip_keyboard(lang=lang),
            )
            return QTE_CLIENT_VAT
        _save_quote_detail(context, "vat", text)
    return await _quote_ask_date(update, context)


async def _quote_ask_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    await update.effective_chat.send_message(
        strings.get_string("QUOTE_ASK_ITEM_NAME", lang),
        reply_markup=keyboards.quote_item_keyboard(lang=lang),
    )
    return QTE_ITEM_NAME


@_handler_safe
async def quote_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.quote_date_keyboard(lang=lang),
            )
        return QTE_DATE

    text = msg.text.strip()
    today = date.today()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_TODAY", lang):
        context.user_data.setdefault("quote", _new_quote_draft())["date"] = today
        return await _quote_ask_item_name(update, context)
    if text == strings.get_string("BTN_YESTERDAY", lang):
        context.user_data.setdefault("quote", _new_quote_draft())["date"] = today - timedelta(days=1)
        return await _quote_ask_item_name(update, context)
    if text == strings.get_string("BTN_PICK_DATE", lang):
        min_date, max_date = _cal_bounds()
        await msg.reply_text(
            strings.get_string("CALENDAR_PROMPT", lang),
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_QUOTE_DATE,
                lang=lang, min_date=min_date, max_date=max_date,
            ),
        )
        return QTE_CALENDAR

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.quote_date_keyboard(lang=lang),
    )
    return QTE_DATE


@_handler_safe
async def quote_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Quote ISSUE-date calendar callback."""
    query = update.callback_query
    if query is None:
        return QTE_CALENDAR
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    cb = _parse_cal_callback(query.data)
    if cb is None or cb.flow != keyboards.CAL_FLOW_QUOTE_DATE:
        await _safe_ack(query, "This calendar is no longer active. Please start again.")
        await _safe_delete(query.message)
        return QTE_CALENDAR
    await _safe_ack(query)

    if cb.action == keyboards.CAL_ACTION_NOOP:
        return QTE_CALENDAR
    if cb.action == keyboards.CAL_ACTION_CANCEL:
        await _safe_delete(query.message)
        return await quote_cancel(update, context)

    min_date, max_date = _cal_bounds()
    if cb.action == keyboards.CAL_ACTION_PREV:
        ny, nm = _prev_month(cb.year, cb.month)
        if _last_day_of_month(ny, nm) < min_date:
            await _safe_ack(query, "Already at the earliest month.")
            return QTE_CALENDAR
        await _render_calendar(query, ny, nm, flow=keyboards.CAL_FLOW_QUOTE_DATE, lang=lang)
        return QTE_CALENDAR
    if cb.action == keyboards.CAL_ACTION_NEXT:
        ny, nm = _next_month(cb.year, cb.month)
        if _first_day_of_month(ny, nm) > max_date:
            await _safe_ack(query, "Already at the latest month.")
            return QTE_CALENDAR
        await _render_calendar(query, ny, nm, flow=keyboards.CAL_FLOW_QUOTE_DATE, lang=lang)
        return QTE_CALENDAR
    if cb.action == keyboards.CAL_ACTION_DAY:
        selected = date(cb.year, cb.month, cb.day)
        if not _is_valid_calendar_date(selected):
            await _safe_ack(query, "Date out of allowed range.", alert=True)
            return QTE_CALENDAR
        context.user_data.setdefault("quote", _new_quote_draft())["date"] = selected
        await _safe_delete(query.message)
        return await _quote_ask_item_name(update, context)
    return QTE_CALENDAR


@_handler_safe
async def quote_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_NOT_TEXT", lang))
        return QTE_ITEM_NAME
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if not text:
        await msg.reply_text(strings.get_string("ERR_EMPTY", lang))
        return QTE_ITEM_NAME
    if len(text) > 200:
        await msg.reply_text(strings.get_string("ERR_LONG_TEXT", lang).format(n=200))
        return QTE_ITEM_NAME
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    draft["pending_item_name"] = text
    await msg.reply_text(
        strings.get_string("QUOTE_ASK_ITEM_PRICE", lang).format(item_name=text),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return QTE_ITEM_PRICE


@_handler_safe
async def quote_item_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_PRICE", lang))
        return QTE_ITEM_PRICE
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    try:
        price = _parse_price(text)
    except ValueError as exc:
        err = exc.args[0] if exc.args else "not_number"
        await msg.reply_text(
            strings.get_string("ERR_ZERO_NEGATIVE_PRICE", lang)
            if err == "zero_negative"
            else strings.get_string("ERR_INVALID_PRICE", lang)
        )
        return QTE_ITEM_PRICE
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    item_name = draft.pop("pending_item_name", None) or "Item"
    draft.setdefault("items", []).append({"name": item_name, "price": price})
    currency = draft.get("currency", "EUR")
    summary = _format_quote_summary(draft["items"], currency, lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_quote_after_item_keyboard(draft, lang=lang),
    )
    return QTE_ADD_MORE


@_handler_safe
async def quote_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=_quote_after_item_keyboard(draft, lang=lang),
            )
        return QTE_ADD_MORE

    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    if text == strings.get_string("BTN_ADD_ANOTHER", lang):
        return await _quote_ask_item_name(update, context)
    if text == strings.get_string("BTN_CREATE_QUOTE_CONFIRM", lang):
        return await _generate_and_send_quote(update, context)
    if text == strings.get_string("BTN_QUOTE_SET_VALID", lang):
        await msg.reply_text(
            strings.get_string("QUOTE_ASK_VALID_UNTIL", lang),
            reply_markup=keyboards.quote_valid_until_keyboard(lang=lang),
        )
        return QTE_VALID_UNTIL
    if text.startswith(strings.get_string("BTN_CHANGE_CURRENCY", lang)):
        await msg.reply_text(
            strings.get_string("ASK_CURRENCY", lang),
            reply_markup=keyboards.currency_picker_keyboard(lang=lang),
        )
        return QTE_CURRENCY
    if text.startswith(strings.get_string("BTN_SET_VAT", lang)):
        await msg.reply_text(
            strings.get_string("QUOTE_ASK_VAT_RATE", lang),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="Markdown",
        )
        return QTE_VAT_RATE
    if text in (
        strings.get_string("BTN_SAVE_CLIENT", lang),
        strings.get_string("CLIENT_SAVED_INLINE", lang),
    ):
        client_name = draft.get("client_name")
        if client_name:
            cd = draft.get("client_details") or {}
            try:
                profile_manager.save_client(
                    update.effective_user.id, client_name,
                    phone=cd.get("phone"), address=cd.get("address"),
                    bank=cd.get("bank"), vat=cd.get("vat"),
                )
                draft["client_saved"] = True
                await msg.reply_text(
                    strings.get_string("CLIENT_SAVED", lang),
                    reply_markup=_quote_after_item_keyboard(draft, lang=lang),
                )
            except Exception:
                logger.exception("Failed to save client (quote) for %s", update.effective_user.id)
                await msg.reply_text(strings.get_string("ERR_QUOTE_PDF_FAILURE", lang))
        return QTE_ADD_MORE

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=_quote_after_item_keyboard(draft, lang=lang),
    )
    return QTE_ADD_MORE


@_handler_safe
async def quote_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_INVALID_CURRENCY", lang),
                reply_markup=keyboards.currency_picker_keyboard(lang=lang),
            )
        return QTE_CURRENCY
    text = msg.text.strip()

    async def _back_to_summary() -> int:
        summary = _format_quote_summary(draft.get("items", []), draft.get("currency", "EUR"), lang=lang)
        await msg.reply_text(
            f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
            reply_markup=_quote_after_item_keyboard(draft, lang=lang),
        )
        return QTE_ADD_MORE

    if text == strings.get_string("BTN_BACK", lang):
        return await _back_to_summary()
    if text == strings.get_string("BTN_CURRENCY_OTHER", lang):
        await msg.reply_text(
            strings.get_string("ASK_CURRENCY_CUSTOM", lang),
            reply_markup=ReplyKeyboardRemove(),
        )
        return QTE_CURRENCY_CUSTOM

    code = _CURRENCY_BUTTON_CODES.get(text)
    if code is None:
        upper = text.upper()
        if 2 <= len(upper) <= 4 and upper.isalpha():
            code = upper
    if code is None:
        await msg.reply_text(
            strings.get_string("ERR_INVALID_CURRENCY", lang),
            reply_markup=keyboards.currency_picker_keyboard(lang=lang),
        )
        return QTE_CURRENCY
    draft["currency"] = code
    await msg.reply_text(strings.get_string("CURRENCY_SET", lang).format(currency=code))
    return await _back_to_summary()


@_handler_safe
async def quote_currency_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_CURRENCY", lang))
        return QTE_CURRENCY_CUSTOM
    upper = msg.text.strip().upper()
    if not (2 <= len(upper) <= 4 and upper.isalpha()):
        await msg.reply_text(strings.get_string("ERR_INVALID_CURRENCY", lang))
        return QTE_CURRENCY_CUSTOM
    draft["currency"] = upper
    await msg.reply_text(strings.get_string("CURRENCY_SET", lang).format(currency=upper))
    summary = _format_quote_summary(draft.get("items", []), upper, lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_quote_after_item_keyboard(draft, lang=lang),
    )
    return QTE_ADD_MORE


@_handler_safe
async def quote_vat_rate(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.get_string("ERR_INVALID_VAT_RATE", lang))
        return QTE_VAT_RATE
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await quote_cancel(update, context)
    try:
        rate = _parse_vat_rate_input(text)
    except ValueError:
        await msg.reply_text(strings.get_string("ERR_INVALID_VAT_RATE", lang))
        return QTE_VAT_RATE
    draft["vat_rate"] = rate
    await msg.reply_text(
        strings.get_string("QUOTE_VAT_SET", lang).format(rate=_fmt_rate(rate))
    )
    summary = _format_quote_summary(draft.get("items", []), draft.get("currency", "EUR"), lang=lang)
    await msg.reply_text(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_quote_after_item_keyboard(draft, lang=lang),
    )
    return QTE_ADD_MORE


@_handler_safe
async def quote_valid_until(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.get_string("ERR_WRONG_BUTTON", lang),
                reply_markup=keyboards.quote_valid_until_keyboard(lang=lang),
            )
        return QTE_VALID_UNTIL

    text = msg.text.strip()
    base = draft.get("date") or date.today()
    if not isinstance(base, date):
        base = date.today()

    async def _back_to_summary() -> int:
        summary = _format_quote_summary(draft.get("items", []), draft.get("currency", "EUR"), lang=lang)
        await msg.reply_text(
            f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
            reply_markup=_quote_after_item_keyboard(draft, lang=lang),
        )
        return QTE_ADD_MORE

    if text == strings.get_string("BTN_BACK", lang):
        return await _back_to_summary()
    if text == strings.get_string("BTN_QUOTE_NO_VALID", lang):
        draft["valid_until"] = None
        return await _back_to_summary()

    days_map = {
        strings.get_string("BTN_QUOTE_VALID_14", lang): 14,
        strings.get_string("BTN_QUOTE_VALID_30", lang): 30,
        strings.get_string("BTN_QUOTE_VALID_60", lang): 60,
    }
    if text in days_map:
        vu = base + timedelta(days=days_map[text])
        draft["valid_until"] = vu.strftime("%d.%m.%Y")
        await msg.reply_text(
            strings.get_string("QUOTE_VALID_UNTIL_SET", lang).format(date=draft["valid_until"])
        )
        return await _back_to_summary()
    if text == strings.get_string("BTN_QUOTE_VALID_CUSTOM", lang):
        min_date, max_date = _cal_bounds()
        today = date.today()
        await msg.reply_text(
            strings.get_string("CALENDAR_PROMPT", lang),
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
                flow=keyboards.CAL_FLOW_QUOTE_VALID,
                lang=lang, min_date=min_date, max_date=max_date,
            ),
        )
        return QTE_VALID_CALENDAR

    await msg.reply_text(
        strings.get_string("ERR_WRONG_BUTTON", lang),
        reply_markup=keyboards.quote_valid_until_keyboard(lang=lang),
    )
    return QTE_VALID_UNTIL


@_handler_safe
async def quote_valid_calendar_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query = update.callback_query
    if query is None:
        return QTE_VALID_CALENDAR
    lang = _get_lang(context, update.effective_user.id) if update.effective_user else "en"
    cb = _parse_cal_callback(query.data)
    if cb is None or cb.flow != keyboards.CAL_FLOW_QUOTE_VALID:
        await _safe_ack(query, "This calendar is no longer active. Please start again.")
        await _safe_delete(query.message)
        return QTE_VALID_CALENDAR
    await _safe_ack(query)

    draft = context.user_data.setdefault("quote", _new_quote_draft())
    if cb.action == keyboards.CAL_ACTION_NOOP:
        return QTE_VALID_CALENDAR
    if cb.action == keyboards.CAL_ACTION_CANCEL:
        await _safe_delete(query.message)
        return await quote_cancel(update, context)

    min_date, max_date = _cal_bounds()
    if cb.action == keyboards.CAL_ACTION_PREV:
        ny, nm = _prev_month(cb.year, cb.month)
        if _last_day_of_month(ny, nm) < min_date:
            await _safe_ack(query, "Already at the earliest month.")
            return QTE_VALID_CALENDAR
        await _render_calendar(query, ny, nm, flow=keyboards.CAL_FLOW_QUOTE_VALID, lang=lang)
        return QTE_VALID_CALENDAR
    if cb.action == keyboards.CAL_ACTION_NEXT:
        ny, nm = _next_month(cb.year, cb.month)
        if _first_day_of_month(ny, nm) > max_date:
            await _safe_ack(query, "Already at the latest month.")
            return QTE_VALID_CALENDAR
        await _render_calendar(query, ny, nm, flow=keyboards.CAL_FLOW_QUOTE_VALID, lang=lang)
        return QTE_VALID_CALENDAR
    if cb.action == keyboards.CAL_ACTION_DAY:
        selected = date(cb.year, cb.month, cb.day)
        if not _is_valid_calendar_date(selected):
            await _safe_ack(query, "Date out of allowed range.", alert=True)
            return QTE_VALID_CALENDAR
        draft["valid_until"] = selected.strftime("%d.%m.%Y")
        await _safe_delete(query.message)
        summary = _format_quote_summary(draft.get("items", []), draft.get("currency", "EUR"), lang=lang)
        await update.effective_chat.send_message(
            strings.get_string("QUOTE_VALID_UNTIL_SET", lang).format(date=draft["valid_until"])
        )
        await update.effective_chat.send_message(
            f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
            reply_markup=_quote_after_item_keyboard(draft, lang=lang),
        )
        return QTE_ADD_MORE
    return QTE_VALID_CALENDAR


def _quote_client_details_for_pdf(draft: dict[str, Any]) -> dict[str, Any] | None:
    details = (draft or {}).get("client_details") or {}
    if any((v or "").strip() if isinstance(v, str) else False for v in details.values()):
        return details
    return None


async def _generate_and_send_quote(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    chat = update.effective_chat
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    draft = context.user_data.get("quote", {})
    items = draft.get("items", [])

    if not items:
        await chat.send_message(
            "Please add at least one item.",
            reply_markup=keyboards.quote_item_keyboard(lang=lang),
        )
        return QTE_ITEM_NAME

    profile = profile_manager.get_profile(user_id)
    if not profile:
        await chat.send_message(strings.get_string("ERR_QUOTE_PDF_FAILURE", lang))
        context.user_data.pop("quote", None)
        return ConversationHandler.END

    status_msg = await chat.send_message(strings.get_string("QUOTE_GENERATING", lang))

    editing_number = draft.get("editing_number")
    if editing_number:
        quote_number = int(editing_number)
    else:
        quote_number = int(profile.get("last_quote_number", 0)) + 1

    quote_date_value = draft.get("date") or date.today()
    client_name = draft.get("client_name")
    currency = str(draft.get("currency") or "EUR").upper()
    valid_until = draft.get("valid_until")
    client_details = _quote_client_details_for_pdf(draft)
    vat_pct = float(draft.get("vat_rate", 0.0) or 0.0)
    tax_decimal = (vat_pct / 100.0) if vat_pct > 0 else None

    # Preserve an existing status when re-saving an edited quote.
    status = profile_manager.QUOTE_STATUS_PENDING
    if editing_number:
        existing = profile_manager.get_quote_by_number(user_id, editing_number)
        if existing and existing.get("status"):
            status = existing["status"]

    try:
        pdf_path: Path = pdf_generator.generate_quote_pdf(
            quote_number=quote_number,
            quote_date=quote_date_value,
            client_name=client_name,
            items=items,
            profile=profile,
            currency=currency,
            valid_until=valid_until,
            status=status,
            tax_rate=tax_decimal,
            client_details=client_details,
        )
    except Exception:
        logger.exception("Quote PDF generation failed for user_id=%s", user_id)
        await _safe_delete(status_msg)
        await chat.send_message(
            strings.get_string("ERR_QUOTE_PDF_FAILURE", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        context.user_data.pop("quote", None)
        return ConversationHandler.END

    if not editing_number:
        try:
            quote_number = profile_manager.increment_quote_number(user_id)
        except Exception:
            logger.exception("Quote counter increment failed for %s", user_id)

    await _safe_delete(status_msg)

    caption = (
        f"{strings.get_string('QUOTE_DONE', lang).format(number=f'{quote_number:04d}')}\n\n"
        f"{strings.get_string('QUOTE_STORAGE_HINT', lang)}"
    )
    try:
        with pdf_path.open("rb") as fh:
            await chat.send_document(document=fh, filename=pdf_path.name, caption=caption)
    except Exception:
        logger.exception("Failed to deliver quote PDF to %s", user_id)
        await chat.send_message(
            strings.get_string("ERR_QUOTE_PDF_FAILURE", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        context.user_data.pop("quote", None)
        return ConversationHandler.END

    total_amount = float(sum(float(i.get("price", 0)) for i in items))
    record = {
        "number": int(quote_number),
        "client_name": client_name or None,
        "amount": total_amount,
        "currency": currency,
        "quote_date": quote_date_value.strftime("%d.%m.%Y") if isinstance(quote_date_value, date) else str(quote_date_value),
        "valid_until": valid_until,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "status": status,
        "items": [dict(i) for i in items],
        "vat_rate": vat_pct if vat_pct > 0 else None,
        "client_details": client_details or None,
    }
    try:
        if editing_number:
            # Replace the existing record in place.
            quotes = profile_manager.get_quotes(user_id)
            kept = [q for q in quotes if int(q.get("number", -1)) != int(editing_number)]
            # rebuild list preserving order isn't critical; append updated
            profile_manager.update_profile(user_id, quotes=kept + [record])
        else:
            profile_manager.record_quote(user_id, record)
    except Exception:
        logger.exception("Could not record quote Q-%04d for %s", quote_number, user_id)

    context.user_data.pop("quote", None)
    profile_after = profile_manager.get_profile(user_id) or {}
    await chat.send_message(
        strings.get_string("WELCOME_BACK", lang).format(
            org_name=profile_after.get("org_name", "")
        ),
        reply_markup=keyboards.main_menu_keyboard(lang=lang),
    )
    return ConversationHandler.END


# =============================================================================
# === MY QUOTES — list + per-quote actions ====================================
# =============================================================================

def _quote_status_display(status: str, lang: str) -> str:
    key = {
        "Pending": "QUOTE_STATUS_PENDING",
        "Accepted": "QUOTE_STATUS_ACCEPTED",
        "Converted": "QUOTE_STATUS_CONVERTED",
    }.get(str(status), "QUOTE_STATUS_PENDING")
    return strings.get_string(key, lang)


@_handler_safe
async def my_quotes_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """My quotes — reply-button entry. Lists quotes as inline rows."""
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.get_string("RESTARTED", lang), reply_markup=ReplyKeyboardRemove())
        return

    quotes = profile_manager.get_quotes(user_id)
    if not quotes:
        await update.message.reply_text(
            strings.get_string("QUOTE_LIST_EMPTY", lang),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return

    # Newest first.
    quotes_sorted = sorted(quotes, key=lambda q: int(q.get("number", 0)), reverse=True)
    await update.message.reply_text(
        f"{strings.get_string('QUOTE_LIST_HEADER', lang)}\n\n"
        f"{strings.get_string('QUOTE_SELECT_PROMPT', lang)}",
        parse_mode="Markdown",
        reply_markup=keyboards.quotes_list_keyboard(quotes_sorted, lang=lang),
    )


def _render_quote_view(q: dict[str, Any], lang: str) -> str:
    number = int(q.get("number", 0))
    client = q.get("client_name") or strings.get_string("NO_CLIENT_LABEL", lang)
    amount = _format_money(float(q.get("amount", 0)), str(q.get("currency", "EUR")))
    status = _quote_status_display(q.get("status", "Pending"), lang)
    valid = q.get("valid_until") or "\u2014"
    qdate = q.get("quote_date") or "\u2014"
    lines = [
        strings.get_string("QUOTE_VIEW_HEADER", lang).format(number=f"{number:04d}"),
        "",
        f"\U0001f464 {client}",
        f"\U0001f4b0 {amount}",
        f"\U0001f4c5 {strings.get_string('DATE_LABEL', lang)} {qdate}",
        f"\U0001f4c5 {strings.get_string('QUOTE_VALID_LABEL', lang)} {valid}",
        f"\U0001f4cc {strings.get_string('QUOTE_STATUS_LABEL', lang)} {status}",
    ]
    return "\n".join(lines)


@_handler_safe
async def quote_action_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Single callback router for all quote:* inline actions."""
    query = update.callback_query
    await _safe_ack(query)
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id) if update.effective_user else "en"
    data = query.data or ""

    if data == keyboards.CB_QUOTE_LIST:
        quotes = profile_manager.get_quotes(user_id)
        if not quotes:
            await _safe_delete(query.message)
            await update.effective_chat.send_message(
                strings.get_string("QUOTE_LIST_EMPTY", lang),
                reply_markup=keyboards.main_menu_keyboard(lang=lang),
            )
            return
        quotes_sorted = sorted(quotes, key=lambda q: int(q.get("number", 0)), reverse=True)
        try:
            await query.edit_message_text(
                f"{strings.get_string('QUOTE_LIST_HEADER', lang)}\n\n"
                f"{strings.get_string('QUOTE_SELECT_PROMPT', lang)}",
                parse_mode="Markdown",
                reply_markup=keyboards.quotes_list_keyboard(quotes_sorted, lang=lang),
            )
        except Exception:
            await update.effective_chat.send_message(
                f"{strings.get_string('QUOTE_LIST_HEADER', lang)}\n\n"
                f"{strings.get_string('QUOTE_SELECT_PROMPT', lang)}",
                parse_mode="Markdown",
                reply_markup=keyboards.quotes_list_keyboard(quotes_sorted, lang=lang),
            )
        return

    parts = data.split(":")
    if len(parts) != 3:
        return
    action = parts[1]
    try:
        number = int(parts[2])
    except ValueError:
        return

    q = profile_manager.get_quote_by_number(user_id, number)
    if q is None:
        await query.edit_message_text(strings.get_string("QUOTE_NOT_FOUND", lang))
        return

    if action == "view":
        try:
            await query.edit_message_text(
                _render_quote_view(q, lang),
                parse_mode="Markdown",
                reply_markup=keyboards.quote_view_keyboard(number, q.get("status", "Pending"), lang=lang),
            )
        except Exception:
            await update.effective_chat.send_message(
                _render_quote_view(q, lang),
                parse_mode="Markdown",
                reply_markup=keyboards.quote_view_keyboard(number, q.get("status", "Pending"), lang=lang),
            )
        return

    if action == "accept":
        profile_manager.update_quote_status(user_id, number, profile_manager.QUOTE_STATUS_ACCEPTED)
        q = profile_manager.get_quote_by_number(user_id, number) or q
        await update.effective_chat.send_message(
            strings.get_string("QUOTE_MARKED_ACCEPTED", lang).format(number=f"{number:04d}")
        )
        try:
            await query.edit_message_text(
                _render_quote_view(q, lang),
                parse_mode="Markdown",
                reply_markup=keyboards.quote_view_keyboard(number, q.get("status", "Pending"), lang=lang),
            )
        except Exception:
            pass
        return

    if action == "delete":
        quotes = profile_manager.get_quotes(user_id)
        kept = [x for x in quotes if int(x.get("number", -1)) != number]
        profile_manager.update_profile(user_id, quotes=kept)
        await _safe_delete(query.message)
        await update.effective_chat.send_message(
            strings.get_string("QUOTE_DELETED", lang).format(number=f"{number:04d}"),
            reply_markup=keyboards.main_menu_keyboard(lang=lang),
        )
        return

    if action == "send":
        await _resend_quote_pdf(update, context, q)
        return

    # Note: 'convert' and 'edit' are handled by dedicated entry-point
    # handlers (quote_convert_entry / quote_edit_entry) so they can enter
    # the invoice / quote ConversationHandlers. They are registered with
    # their own CallbackQueryHandlers and never reach this router.


async def _resend_quote_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE, q: dict[str, Any]
) -> None:
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    chat = update.effective_chat
    profile = profile_manager.get_profile(user_id) or {}
    number = int(q.get("number", 0))

    await chat.send_message(strings.get_string("QUOTE_RESENDING", lang).format(number=f"{number:04d}"))
    vat_pct = float(q.get("vat_rate") or 0.0)
    tax_decimal = (vat_pct / 100.0) if vat_pct > 0 else None
    try:
        qdate = q.get("quote_date")
        if isinstance(qdate, str):
            try:
                qdate_val = datetime.strptime(qdate, "%d.%m.%Y").date()
            except ValueError:
                qdate_val = date.today()
        else:
            qdate_val = date.today()
        pdf_path = pdf_generator.generate_quote_pdf(
            quote_number=number,
            quote_date=qdate_val,
            client_name=q.get("client_name"),
            items=q.get("items") or [],
            profile=profile,
            currency=str(q.get("currency") or "EUR").upper(),
            valid_until=q.get("valid_until"),
            status=q.get("status", "Pending"),
            tax_rate=tax_decimal,
            client_details=q.get("client_details"),
        )
        with pdf_path.open("rb") as fh:
            await chat.send_document(
                document=fh, filename=pdf_path.name,
                caption=strings.get_string("QUOTE_SENT", lang).format(number=f"{number:04d}"),
            )
    except Exception:
        logger.exception("Failed to resend quote Q-%04d for %s", number, user_id)
        await chat.send_message(strings.get_string("ERR_QUOTE_PDF_FAILURE", lang))


@_handler_safe
async def quote_convert_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point for quote:convert:<n> — enters the INVOICE conversation.

    Copies a quote into a fresh invoice draft and drops the user into the
    invoice after-items screen. Marks the quote Converted (guarded)."""
    query = update.callback_query
    await _safe_ack(query)
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    chat = update.effective_chat

    try:
        number = int((query.data or "").split(":")[2])
    except (ValueError, IndexError):
        return ConversationHandler.END

    q = profile_manager.get_quote_by_number(user_id, number)
    if q is None:
        await chat.send_message(strings.get_string("QUOTE_NOT_FOUND", lang))
        return ConversationHandler.END

    # Double-conversion guard.
    if str(q.get("status")) == profile_manager.QUOTE_STATUS_CONVERTED:
        await chat.send_message(
            strings.get_string("QUOTE_ALREADY_CONVERTED", lang).format(number=f"{number:04d}")
        )
        return ConversationHandler.END

    ok = profile_manager.mark_quote_converted(user_id, number)
    if not ok:
        await chat.send_message(
            strings.get_string("QUOTE_ALREADY_CONVERTED", lang).format(number=f"{number:04d}")
        )
        return ConversationHandler.END

    await chat.send_message(strings.get_string("QUOTE_CONVERTING", lang).format(number=f"{number:04d}"))

    draft = _new_invoice_draft()
    draft["client_name"] = q.get("client_name")
    draft["items"] = [dict(i) for i in (q.get("items") or [])]
    draft["currency"] = str(q.get("currency") or "EUR").upper()
    draft["vat_rate"] = float(q.get("vat_rate") or 0.0)
    cd = q.get("client_details") or {}
    draft["client_details"] = {
        "phone": cd.get("phone"), "address": cd.get("address"),
        "bank": cd.get("bank"), "vat": cd.get("vat"),
    }
    draft["date"] = date.today()
    draft["from_quote_number"] = number
    context.user_data["invoice"] = draft

    summary = _format_invoice_summary(draft["items"], draft["currency"], lang=lang)
    await chat.send_message(
        strings.get_string("QUOTE_CONVERTED_MSG", lang).format(qnumber=f"{number:04d}")
    )
    await chat.send_message(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_after_item_keyboard(draft, lang=lang),
    )
    return INV_ADD_MORE


@_handler_safe
async def quote_edit_entry(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Entry point for quote:edit:<n> — enters the QUOTE conversation.

    Loads a quote's data into a quote draft and resumes at the after-items
    screen. On 'Create quote' the existing quote is updated in place."""
    query = update.callback_query
    await _safe_ack(query)
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    chat = update.effective_chat

    try:
        number = int((query.data or "").split(":")[2])
    except (ValueError, IndexError):
        return ConversationHandler.END

    q = profile_manager.get_quote_by_number(user_id, number)
    if q is None:
        await chat.send_message(strings.get_string("QUOTE_NOT_FOUND", lang))
        return ConversationHandler.END
    if str(q.get("status")) == profile_manager.QUOTE_STATUS_CONVERTED:
        # A converted quote is locked; editing it would desync the invoice.
        await chat.send_message(
            strings.get_string("QUOTE_ALREADY_CONVERTED", lang).format(number=f"{number:04d}")
        )
        return ConversationHandler.END

    draft = _new_quote_draft()
    draft["client_name"] = q.get("client_name")
    draft["items"] = [dict(i) for i in (q.get("items") or [])]
    draft["currency"] = str(q.get("currency") or "EUR").upper()
    draft["vat_rate"] = float(q.get("vat_rate") or 0.0)
    draft["valid_until"] = q.get("valid_until")
    cd = q.get("client_details") or {}
    draft["client_details"] = {
        "phone": cd.get("phone"), "address": cd.get("address"),
        "bank": cd.get("bank"), "vat": cd.get("vat"),
    }
    qdate = q.get("quote_date")
    if isinstance(qdate, str):
        try:
            draft["date"] = datetime.strptime(qdate, "%d.%m.%Y").date()
        except ValueError:
            draft["date"] = date.today()
    else:
        draft["date"] = date.today()
    draft["editing_number"] = number
    draft["client_saved"] = True
    context.user_data["quote"] = draft

    summary = _format_quote_summary(draft["items"], draft["currency"], lang=lang)
    await chat.send_message(
        f"{summary}\n\n{strings.get_string('WHATS_NEXT_PROMPT', lang)}",
        reply_markup=_quote_after_item_keyboard(draft, lang=lang),
    )
    return QTE_ADD_MORE


# =============================================================================
# === REGISTER ALL HANDLERS ===================================================
# =============================================================================

def register_handlers(application: Application) -> None:
    """Attach every handler to *application*. Called once from main.py."""

    onboarding_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            ONBOARD_LANGUAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_language),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_ORG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_org),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_PHONE: [
                # Rule 3 — Accept text OR a shared contact in this step.
                MessageHandler(
                    (filters.TEXT | filters.CONTACT) & ~filters.COMMAND,
                    onboard_phone,
                ),
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
            ONBOARD_VAT_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_vat_rate),
                CommandHandler("start", onboard_cancel_or_restart),
                CommandHandler("cancel", onboard_cancel_or_restart),
            ],
            ONBOARD_CURRENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_currency),
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
            MessageHandler(
                filters.Regex(_bilingual_regex("BTN_CREATE_INVOICE")),
                invoice_start_entry,
            ),
            # Goal 1 — converting a quote enters the invoice flow directly
            # at the after-items screen with a pre-populated draft.
            CallbackQueryHandler(
                quote_convert_entry,
                pattern=rf"^{re.escape(keyboards.CB_QUOTE_CONVERT)}:\d+$",
            ),
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
            INV_VAT_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_vat_rate),
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
            MessageHandler(
                filters.Regex(_bilingual_regex("BTN_EDIT_PROFILE")),
                profile_edit_entry,
            ),
        ],
        states={
            PE_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_menu),
            ],
            PE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_name),
            ],
            PE_PHONE: [
                # Rule 3 — Accept text OR a shared contact in this step.
                MessageHandler(
                    (filters.TEXT | filters.CONTACT) & ~filters.COMMAND,
                    profile_edit_phone,
                ),
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
            PE_VAT_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_vat_rate),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", profile_edit_entry),
            CommandHandler("start", profile_edit_entry),
        ],
        allow_reentry=True,
    )

    # Goal 1 — Quote conversation. Mirrors the invoice flow. The Edit
    # action enters this conversation at the after-items screen.
    quote_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(_bilingual_regex("BTN_CREATE_QUOTE")),
                quote_start_entry,
            ),
            CallbackQueryHandler(
                quote_edit_entry,
                pattern=rf"^{re.escape(keyboards.CB_QUOTE_EDIT)}:\d+$",
            ),
        ],
        states={
            QTE_CLIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client),
            ],
            QTE_CLIENT_DETAILS_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client_details_choice),
            ],
            QTE_CLIENT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client_phone),
            ],
            QTE_CLIENT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client_address),
            ],
            QTE_CLIENT_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client_bank),
            ],
            QTE_CLIENT_VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_client_vat),
            ],
            QTE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_date),
            ],
            QTE_CALENDAR: [
                CallbackQueryHandler(
                    quote_calendar_callback,
                    pattern=rf"^{keyboards.CAL_NS}:",
                ),
            ],
            QTE_ITEM_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_item_name),
            ],
            QTE_ITEM_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_item_price),
            ],
            QTE_ADD_MORE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_add_more),
            ],
            QTE_CURRENCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_currency),
            ],
            QTE_CURRENCY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_currency_custom),
            ],
            QTE_VAT_RATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_vat_rate),
            ],
            QTE_VALID_UNTIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, quote_valid_until),
            ],
            QTE_VALID_CALENDAR: [
                CallbackQueryHandler(
                    quote_valid_calendar_callback,
                    pattern=rf"^{keyboards.CAL_NS}:",
                ),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", quote_cancel),
            CommandHandler("start", quote_cancel),
        ],
        allow_reentry=True,
    )

    application.add_handler(CommandHandler("help", help_command))

    # ❓ Help reply-keyboard button — previously unhandled (fell through to
    # the catch-all and silently re-showed the menu). Bind it to the help
    # screen. Must be registered before the catch-all fallback below.
    application.add_handler(
        MessageHandler(
            filters.Regex(_bilingual_regex("BTN_HELP")),
            help_button,
        )
    )
    # Inline "Back to Menu" button beneath the help message.
    application.add_handler(
        CallbackQueryHandler(
            help_back_to_menu_callback,
            pattern=rf"^{re.escape(strings.CB_HELP_BACK_TO_MENU)}$",
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(_bilingual_regex("BTN_TRACK_INVOICES")),
            track_invoices_entry,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(_bilingual_regex("BTN_MARK_AS_PAID")),
            track_invoices_mark_paid_entry,
        )
    )
    application.add_handler(
        CallbackQueryHandler(track_mark_paid_callback, pattern=r"^markpaid:")
    )

    application.add_handler(onboarding_conv)
    application.add_handler(invoice_conv)
    application.add_handler(profile_edit_conv)

    # Goal 1 — Quotes. The "My quotes" reply button opens the list; the
    # quote conversation handles creation + editing; a standalone callback
    # router handles view/send/accept/delete/list (the convert + edit
    # actions are entry points of invoice_conv / quote_conv respectively).
    application.add_handler(
        MessageHandler(
            filters.Regex(_bilingual_regex("BTN_MY_QUOTES")),
            my_quotes_entry,
        )
    )
    application.add_handler(quote_conv)
    application.add_handler(
        CallbackQueryHandler(
            quote_action_callback,
            pattern=r"^quote:(view|send|accept|delete|list)",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            orphan_calendar_callback,
            pattern=rf"^{keyboards.CAL_NS}:",
        )
    )

    # --- Receipts (Feature 1) ---
    receipt_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(_bilingual_regex("BTN_CREATE_RECEIPT")),
                receipt_start_entry,
            ),
        ],
        states={
            RCP_BILL_TO:        [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_bill_to)],
            RCP_CLIENT_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_client_address)],
            RCP_CLIENT_EMAIL:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_client_email)],
            RCP_INVOICE_REF:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_invoice_ref)],
            RCP_DATE_PAID:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_date_paid)],
            RCP_ITEM_DESC:      [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_item_desc)],
            RCP_ITEM_QTY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_item_qty)],
            RCP_ITEM_PRICE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_item_price)],
            RCP_ITEM_VAT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_item_vat)],
            RCP_ADD_MORE:       [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_add_more)],
            RCP_AMOUNT_PAID:    [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_amount_paid)],
            RCP_PAYMENT_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_payment_method)],
            RCP_PAYMENT_OTHER:  [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_payment_other)],
            RCP_PAYMENT_DATE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, receipt_payment_date)],
        },
        fallbacks=[
            CommandHandler("cancel", receipt_cancel),
            CommandHandler("start", receipt_cancel),
        ],
        allow_reentry=True,
    )
    application.add_handler(receipt_conv)

    # Feature 3 — View-paid reply button.
    application.add_handler(
        MessageHandler(
            filters.Regex(_bilingual_regex("BTN_VIEW_PAID")),
            track_view_paid_entry,
        )
    )
    # Feature 2 — payment-method picker after tapping an unpaid invoice.
    application.add_handler(
        CallbackQueryHandler(track_payment_method_callback, pattern=r"^paymethod:")
    )
    # Feature 3 — inline "view paid" shown when all invoices are paid.
    application.add_handler(
        CallbackQueryHandler(
            track_view_paid_callback,
            pattern=rf"^{keyboards.CB_TRACK_VIEW_PAID}$",
        )
    )

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_any_message)
    )

    logger.info("All handlers registered successfully.")

# =============================================================================
# === RECEIPTS — shared helpers ===============================================
# =============================================================================

# callback_key -> display label, resolved through get_string at call time.
_PM_LABELS = {
    "bank_transfer": "PM_BANK_TRANSFER",
    "credit_card": "PM_CREDIT_CARD",
    "cash": "PM_CASH",
    "paypal": "PM_PAYPAL",
    "stripe": "PM_STRIPE",
    "other": "PM_OTHER",
}


def _pm_label(key: str, lang: str = "en") -> str:
    return strings.get_string(_PM_LABELS.get(key, "PM_OTHER"), lang)


def _new_receipt_draft() -> dict[str, Any]:
    return {
        "bill_to": {"name": None, "address": None, "email": None},
        "invoice_number": None,
        "date_paid": None,
        "items": [],            # {"description","qty","unit_price","vat_rate"}
        "amount_paid": None,
        "payment_method": None,
        "payment_date": None,
        "currency": profile_manager.CURRENCY_DEFAULT,
    }


def _receipt_total(items: list[dict[str, Any]]) -> float:
    total = 0.0
    for it in items:
        qty = float(it.get("qty", 1) or 1)
        unit = float(it.get("unit_price", 0) or 0)
        rate = float(it.get("vat_rate", 0) or 0)
        total += qty * unit * (1 + rate / 100.0)
    return round(total, 2)


def _parse_qty(text: str) -> float:
    v = float(text.strip().replace(",", "."))
    if v <= 0:
        raise ValueError("zero_negative")
    return round(v, 3)


def _parse_vat_rate(text: str) -> float:
    v = float(text.strip().replace("%", "").replace(",", "."))
    if v < 0 or v > 100:
        raise ValueError("range")
    return round(v, 2)


def _invoice_items_to_receipt_items(inv: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a stored invoice's items -> receipt line items.

    Invoice items are {"name","price"} so qty=1, unit_price=price, vat=0.
    Falls back to a single total line for invoices created before items
    were persisted (see 5e)."""
    items = inv.get("items") or []
    out = [
        {"description": i.get("name", "Item"),
         "qty": 1, "unit_price": float(i.get("price", 0) or 0), "vat_rate": 0}
        for i in items
    ]
    if not out:
        out = [{
            "description": f"Invoice #{int(inv.get('number', 0)):05d}",
            "qty": 1, "unit_price": float(inv.get("amount", 0) or 0), "vat_rate": 0,
        }]
    return out


# =============================================================================
# === RECEIPTS — standalone flow (Feature 1) ==================================
# =============================================================================

@_handler_safe
async def receipt_start_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.get_string("RESTARTED", lang), reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    profile = profile_manager.get_profile(user_id) or {}
    draft = _new_receipt_draft()
    draft["currency"] = str(profile.get("currency") or profile_manager.CURRENCY_DEFAULT).upper()
    context.user_data["receipt"] = draft

    await update.message.reply_text(
        strings.get_string("RCP_ASK_BILL_TO", lang),
        reply_markup=keyboards.receipt_bill_to_keyboard(
            saved_clients=profile_manager.get_saved_clients(user_id), lang=lang),
    )
    return RCP_BILL_TO


@_handler_safe
async def receipt_bill_to(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_BILL_TO
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)

    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    draft["bill_to"]["name"] = text

    # Auto-fill from a saved client if the name matches.
    saved = profile_manager.get_saved_client_by_name(update.effective_user.id, text)
    if saved:
        draft["bill_to"]["address"] = saved.get("address")

    await msg.reply_text(
        strings.get_string("RCP_ASK_CLIENT_ADDRESS", lang),
        reply_markup=keyboards.receipt_skip_keyboard(lang=lang), parse_mode="Markdown")
    return RCP_CLIENT_ADDRESS


@_handler_safe
async def receipt_client_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_CLIENT_ADDRESS
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text != strings.get_string("BTN_RCP_SKIP", lang):
        draft["bill_to"]["address"] = text
    await msg.reply_text(
        strings.get_string("RCP_ASK_CLIENT_EMAIL", lang),
        reply_markup=keyboards.receipt_skip_keyboard(lang=lang), parse_mode="Markdown")
    return RCP_CLIENT_EMAIL


@_handler_safe
async def receipt_client_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_CLIENT_EMAIL
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text != strings.get_string("BTN_RCP_SKIP", lang):
        draft["bill_to"]["email"] = text
    await msg.reply_text(
        strings.get_string("RCP_ASK_INVOICE_REF", lang),
        reply_markup=keyboards.receipt_skip_keyboard(lang=lang))
    return RCP_INVOICE_REF


@_handler_safe
async def receipt_invoice_ref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_INVOICE_REF
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text != strings.get_string("BTN_RCP_SKIP", lang):
        digits = "".join(ch for ch in text if ch.isdigit())
        draft["invoice_number"] = int(digits) if digits else None
    await msg.reply_text(
        strings.get_string("RCP_ASK_DATE_PAID", lang),
        reply_markup=keyboards.receipt_date_keyboard(lang=lang))
    return RCP_DATE_PAID


@_handler_safe
async def receipt_date_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_DATE_PAID
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text == strings.get_string("BTN_TODAY", lang):
        draft["date_paid"] = date.today()
    elif text == strings.get_string("BTN_YESTERDAY", lang):
        draft["date_paid"] = date.today() - timedelta(days=1)
    else:
        try:
            draft["date_paid"] = datetime.strptime(text, "%d.%m.%Y").date()
        except ValueError:
            await msg.reply_text(strings.get_string("ASK_DATE", lang),
                                 reply_markup=keyboards.receipt_date_keyboard(lang=lang))
            return RCP_DATE_PAID
    return await _receipt_ask_item_desc(update, context)


async def _receipt_ask_item_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = _get_lang(context, update.effective_user.id)
    await update.effective_chat.send_message(
        strings.get_string("RCP_ASK_ITEM_DESC", lang),
        reply_markup=keyboards.invoice_item_keyboard(lang=lang))  # reuse Cancel-only kb
    return RCP_ITEM_DESC


@_handler_safe
async def receipt_item_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_ITEM_DESC
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    draft["pending_item"] = {"description": text}
    await msg.reply_text(
        strings.get_string("RCP_ASK_ITEM_QTY", lang).format(desc=text),
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return RCP_ITEM_QTY


@_handler_safe
async def receipt_item_qty(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_ITEM_QTY
    try:
        qty = _parse_qty(msg.text)
    except ValueError:
        await msg.reply_text(strings.get_string("ERR_RCP_INVALID_QTY", lang))
        return RCP_ITEM_QTY
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    draft["pending_item"]["qty"] = qty
    desc = draft["pending_item"]["description"]
    await msg.reply_text(strings.get_string("RCP_ASK_ITEM_PRICE", lang).format(desc=desc),
                         parse_mode="Markdown")
    return RCP_ITEM_PRICE


@_handler_safe
async def receipt_item_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_ITEM_PRICE
    try:
        price = _parse_price(msg.text)   # reuse existing invoice price parser
    except ValueError:
        await msg.reply_text(strings.get_string("ERR_INVALID_PRICE", lang))
        return RCP_ITEM_PRICE
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    draft["pending_item"]["unit_price"] = price
    desc = draft["pending_item"]["description"]
    await msg.reply_text(strings.get_string("RCP_ASK_ITEM_VAT", lang).format(desc=desc),
                         parse_mode="Markdown")
    return RCP_ITEM_VAT


@_handler_safe
async def receipt_item_vat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_ITEM_VAT
    try:
        rate = _parse_vat_rate(msg.text)
    except ValueError:
        await msg.reply_text(strings.get_string("ERR_RCP_INVALID_VAT", lang))
        return RCP_ITEM_VAT
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    item = draft.pop("pending_item")
    item["vat_rate"] = rate
    draft["items"].append(item)
    await msg.reply_text(
        strings.get_string("RCP_ITEM_ADDED", lang).format(desc=item["description"]),
        reply_markup=keyboards.receipt_after_item_keyboard(lang=lang))
    return RCP_ADD_MORE


@_handler_safe
async def receipt_add_more(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_ADD_MORE
    text = msg.text.strip()
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    if text == strings.get_string("BTN_RCP_ADD_ANOTHER", lang):
        return await _receipt_ask_item_desc(update, context)
    if text == strings.get_string("BTN_RCP_DONE_ITEMS", lang):
        if not draft["items"]:
            await msg.reply_text(strings.get_string("RCP_NO_ITEMS", lang))
            return RCP_ADD_MORE
        total = _receipt_total(draft["items"])
        await msg.reply_text(
            strings.get_string("RCP_ASK_AMOUNT_PAID", lang).format(
                total=_format_money(total, draft["currency"])),
            reply_markup=keyboards.receipt_amount_paid_keyboard(lang=lang))
        return RCP_AMOUNT_PAID
    await msg.reply_text(strings.get_string("ERR_WRONG_BUTTON", lang),
                         reply_markup=keyboards.receipt_after_item_keyboard(lang=lang))
    return RCP_ADD_MORE


@_handler_safe
async def receipt_amount_paid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_AMOUNT_PAID
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text == strings.get_string("BTN_RCP_FULL_TOTAL", lang):
        draft["amount_paid"] = _receipt_total(draft["items"])
    else:
        try:
            draft["amount_paid"] = _parse_price(text)
        except ValueError:
            await msg.reply_text(strings.get_string("ERR_INVALID_PRICE", lang))
            return RCP_AMOUNT_PAID
    await msg.reply_text(strings.get_string("RCP_ASK_PAYMENT_METHOD", lang),
                         reply_markup=keyboards.payment_method_reply_keyboard(lang=lang))
    return RCP_PAYMENT_METHOD


@_handler_safe
async def receipt_payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_PAYMENT_METHOD
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text == strings.get_string("PM_OTHER", lang):
        await msg.reply_text(strings.get_string("RCP_ASK_PAYMENT_OTHER", lang),
                             reply_markup=ReplyKeyboardRemove())
        return RCP_PAYMENT_OTHER
    # Map a tapped label back to its canonical display label (identity here,
    # since the reply keyboard uses the display labels directly).
    draft["payment_method"] = text
    await msg.reply_text(strings.get_string("RCP_ASK_PAYMENT_DATE", lang),
                         reply_markup=keyboards.receipt_date_keyboard(lang=lang))
    return RCP_PAYMENT_DATE


@_handler_safe
async def receipt_payment_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_PAYMENT_OTHER
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    draft["payment_method"] = msg.text.strip() or strings.get_string("PM_OTHER", lang)
    await msg.reply_text(strings.get_string("RCP_ASK_PAYMENT_DATE", lang),
                         reply_markup=keyboards.receipt_date_keyboard(lang=lang))
    return RCP_PAYMENT_DATE


@_handler_safe
async def receipt_payment_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    msg = update.message
    lang = _get_lang(context, update.effective_user.id)
    if msg is None or not msg.text:
        return RCP_PAYMENT_DATE
    text = msg.text.strip()
    if text == strings.get_string("BTN_CANCEL", lang):
        return await receipt_cancel(update, context)
    draft = context.user_data.setdefault("receipt", _new_receipt_draft())
    if text == strings.get_string("BTN_TODAY", lang):
        draft["payment_date"] = date.today()
    elif text == strings.get_string("BTN_YESTERDAY", lang):
        draft["payment_date"] = date.today() - timedelta(days=1)
    else:
        try:
            draft["payment_date"] = datetime.strptime(text, "%d.%m.%Y").date()
        except ValueError:
            await msg.reply_text(strings.get_string("ASK_DATE", lang),
                                 reply_markup=keyboards.receipt_date_keyboard(lang=lang))
            return RCP_PAYMENT_DATE
    return await _receipt_generate_and_send(update, context)


async def _receipt_generate_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat = update.effective_chat
    user_id = update.effective_user.id
    lang = _get_lang(context, user_id)
    draft = context.user_data.get("receipt", {})
    profile = profile_manager.get_profile(user_id) or {}

    status = await chat.send_message(strings.get_string("RCP_GENERATING", lang))
    try:
        rcp_number = profile_manager.increment_receipt_number(user_id)
        pdf_path = pdf_generator.generate_receipt_pdf(
            receipt_number=rcp_number,
            date_paid=draft["date_paid"],
            profile=profile,
            bill_to=draft["bill_to"],
            items=draft["items"],
            payment_method=draft["payment_method"],
            payment_date=draft["payment_date"],
            currency=draft["currency"],
            invoice_number=draft.get("invoice_number"),
            amount_paid=draft.get("amount_paid"),
        )
    except Exception:
        logger.exception("Receipt generation failed for user_id=%s", user_id)
        await _safe_delete(status)
        await chat.send_message(strings.get_string("ERR_RCP_PDF_FAILURE", lang),
                                reply_markup=keyboards.main_menu_keyboard(lang=lang))
        context.user_data.pop("receipt", None)
        return ConversationHandler.END

    await _safe_delete(status)
    caption = (f"{strings.get_string('RCP_DONE', lang).format(number=f'RCP-{rcp_number:05d}')}"
               f"\n\n{strings.get_string('RCP_STORAGE_HINT', lang)}")
    try:
        with pdf_path.open("rb") as fh:
            await chat.send_document(document=fh, filename=pdf_path.name, caption=caption)
    except Exception:
        logger.exception("Failed to deliver receipt to user_id=%s", user_id)
        await chat.send_message(strings.get_string("ERR_RCP_PDF_FAILURE", lang))

    context.user_data.pop("receipt", None)
    await chat.send_message(
        strings.get_string("WELCOME_BACK", lang).format(org_name=profile.get("org_name", "")),
        reply_markup=keyboards.main_menu_keyboard(lang=lang))
    return ConversationHandler.END


@_handler_safe
async def receipt_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = _get_lang(context, update.effective_user.id)
    context.user_data.pop("receipt", None)
    await update.effective_chat.send_message(
        strings.get_string("RCP_CANCELLED", lang),
        reply_markup=keyboards.main_menu_keyboard(lang=lang))
    return ConversationHandler.END
