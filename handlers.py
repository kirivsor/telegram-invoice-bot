"""ConversationHandler flow logic for the Telegram Invoice Bot.

Onboarding, invoice creation, profile editing, and the
/start /cancel /help command handlers all live in this module.
Persistence, PDF generation, keyboards, and user-facing strings live
in separate modules.

Handler registration is done in main.py.
"""

import calendar as _cal
import functools
import logging
import re
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
ONBOARD_VAT = 105                # NEW (Fix 3) — optional VAT after email

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
# Fix 4 — optional client-details sub-flow after the client name
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
PE_VAT = 306                     # NEW (Fix 3) — edit VAT in profile

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


def _fmt_currency(amount: float, currency: str) -> str:
    """Format *amount* with the appropriate currency symbol."""
    sym = _CURRENCY_SYMBOLS.get(currency, currency)
    return f"{sym}{amount:,.2f}"


def _fmt_currency_inline(amount: float, currency: str) -> str:
    """Same as _fmt_currency but without a trailing space."""
    return _fmt_currency(amount, currency)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

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
    """Parse a price string into a positive float (Fix 2).

    Accepts integers ("150"), dot-decimals ("49.99"), and comma-decimals
    ("49,99" — common in Europe). Strips surrounding currency tokens
    and spaces. Result is rounded to 2 decimal places to avoid
    floating-point noise like 49.989999...

    Raises ValueError with a code in args[0]:
        "zero_negative"  -> user gave 0 or a negative
        "not_number"     -> unparseable
    """
    cleaned = text.strip()
    for sym in _CURRENCY_TOKENS:
        cleaned = cleaned.replace(sym, "")
    cleaned = cleaned.replace(" ", "")
    if not cleaned:
        raise ValueError("not_number")
    # European decimal comma -> dot. We accept either separator but
    # only ONE separator (mixing thousands + decimal in chat is a stretch).
    cleaned = cleaned.replace(",", ".")
    if cleaned.startswith("-"):
        raise ValueError("zero_negative")
    # Guard against double-dots like "1.2.3" which float() would accept
    # as ValueError, but be explicit.
    if cleaned.count(".") > 1:
        raise ValueError("not_number")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise ValueError("not_number") from exc
    if value <= 0:
        raise ValueError("zero_negative")
    return round(value, 2)


# ---------------------------------------------------------------------------
# Invoice summary helpers
# ---------------------------------------------------------------------------

def _format_invoice_summary(items: list[dict], currency: str) -> str:
    """Return a Markdown summary of the invoice line-items + total."""
    if not items:
        return strings.NO_ITEMS_YET
    lines = []
    total = 0.0
    for i, item in enumerate(items, 1):
        name = item.get("name", "?")
        price = item.get("price", 0.0)
        total += price
        lines.append(f"{i}. {name} — {_fmt_currency(price, currency)}")
    lines.append("")
    lines.append(strings.TOTAL_LABEL.format(total=_fmt_currency(total, currency)))
    return "\n".join(lines)


def _after_item_keyboard(draft: dict) -> ReplyKeyboardMarkup:
    """Return the keyboard shown after adding/removing items."""
    has_items = bool(draft.get("items"))
    return keyboards.invoice_item_keyboard(has_items=has_items)


def _new_invoice_draft() -> dict:
    """Return a fresh invoice draft dict."""
    return {
        "items": [],
        "date": None,
        "due_date": None,
        "client": None,
        "client_details": {},
        "currency": "EUR",
        "number": None,
    }


# =============================================================================
# === ONBOARDING ==============================================================
# =============================================================================

@_handler_safe
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point — /start command."""
    user = update.effective_user
    if user is None:
        return ConversationHandler.END

    if profile_manager.has_profile(user.id):
        await update.message.reply_text(
            strings.WELCOME_BACK.format(name=user.first_name),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        strings.WELCOME_NEW.format(name=user.first_name),
        reply_markup=ReplyKeyboardRemove(),
    )
    await update.message.reply_text(
        strings.ASK_ORG_NAME,
        reply_markup=ForceReply(selective=True),
    )
    return ONBOARD_ORG


@_handler_safe
async def onboard_org(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 1 — organisation / freelancer name."""
    msg = update.message
    if msg is None or not msg.text:
        return ONBOARD_ORG

    text = msg.text.strip()
    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_ORG
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return ONBOARD_ORG

    context.user_data["onboard"] = {"org": text}
    await msg.reply_text(
        strings.ASK_PHONE,
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton(strings.BTN_SHARE_CONTACT, request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return ONBOARD_PHONE


@_handler_safe
async def onboard_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 2 — phone number (contact or typed)."""
    msg = update.message
    if msg is None:
        return ONBOARD_PHONE

    if msg.contact:
        phone = msg.contact.phone_number or ""
    elif msg.text:
        phone = msg.text.strip()
    else:
        await msg.reply_text(strings.ERR_NOT_TEXT)
        return ONBOARD_PHONE

    phone = phone.strip()
    if not phone:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_PHONE

    context.user_data.setdefault("onboard", {})["phone"] = phone
    await msg.reply_text(
        strings.ASK_ACCOUNT,
        reply_markup=ReplyKeyboardRemove(),
    )
    return ONBOARD_ACCOUNT


@_handler_safe
async def onboard_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 3 — bank account / IBAN."""
    msg = update.message
    if msg is None or not msg.text:
        return ONBOARD_ACCOUNT

    text = msg.text.strip()
    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_ACCOUNT
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return ONBOARD_ACCOUNT

    context.user_data.setdefault("onboard", {})["account"] = text
    await msg.reply_text(strings.ASK_REFERENCES)
    return ONBOARD_REFERENCES


@_handler_safe
async def onboard_references(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 4 — payment references."""
    msg = update.message
    if msg is None or not msg.text:
        return ONBOARD_REFERENCES

    text = msg.text.strip()
    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_REFERENCES
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return ONBOARD_REFERENCES

    context.user_data.setdefault("onboard", {})["references"] = text
    await msg.reply_text(strings.ASK_EMAIL)
    return ONBOARD_EMAIL


@_handler_safe
async def onboard_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 5 — email address."""
    msg = update.message
    if msg is None or not msg.text:
        return ONBOARD_EMAIL

    text = msg.text.strip()
    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return ONBOARD_EMAIL
    if not _is_valid_email(text):
        await msg.reply_text(strings.ERR_INVALID_EMAIL)
        return ONBOARD_EMAIL

    context.user_data.setdefault("onboard", {})["email"] = text
    await msg.reply_text(
        strings.ASK_VAT,
        reply_markup=keyboards.skip_keyboard(),
    )
    return ONBOARD_VAT


@_handler_safe
async def onboard_vat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Onboarding step 6 — optional VAT number (Fix 3)."""
    msg = update.message
    if msg is None or not msg.text:
        return ONBOARD_VAT

    text = msg.text.strip()
    if text == strings.BTN_SKIP:
        vat = ""
    else:
        if len(text) > 50:
            await msg.reply_text(strings.ERR_LONG_TEXT.format(n=50))
            return ONBOARD_VAT
        vat = text

    onboard = context.user_data.get("onboard", {})
    onboard["vat"] = vat
    user_id = update.effective_user.id
    profile_manager.save_profile(
        user_id=user_id,
        org=onboard.get("org", ""),
        phone=onboard.get("phone", ""),
        account=onboard.get("account", ""),
        references=onboard.get("references", ""),
        email=onboard.get("email", ""),
        vat=vat,
    )
    context.user_data.pop("onboard", None)
    await msg.reply_text(
        strings.ONBOARD_COMPLETE,
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


# =============================================================================
# === INVOICE CREATION ========================================================
# =============================================================================

@_handler_safe
async def invoice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin a new invoice — ask for the client name."""
    msg = update.message
    context.user_data["invoice"] = _new_invoice_draft()
    await msg.reply_text(
        strings.ASK_CLIENT,
        reply_markup=keyboards.cancel_keyboard(),
    )
    return INV_CLIENT


@_handler_safe
async def invoice_client(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Invoice step 1 — receive the client name."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if not text:
        await msg.reply_text(strings.ERR_EMPTY)
        return INV_CLIENT
    if len(text) > 200:
        await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
        return INV_CLIENT

    context.user_data.setdefault("invoice", _new_invoice_draft())["client"] = text
    # Ask whether to add extra client details (Fix 4)
    await msg.reply_text(
        strings.ASK_CLIENT_DETAILS_CHOICE,
        reply_markup=keyboards.client_details_choice_keyboard(),
    )
    return INV_CLIENT_DETAILS_CHOICE


@_handler_safe
async def invoice_client_details_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Ask whether to add phone/address/bank/VAT for the client (Fix 4)."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT_DETAILS_CHOICE

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_SKIP:
        return await _ask_date(update, context)

    if text == strings.BTN_ADD_CLIENT_DETAILS:
        await msg.reply_text(
            strings.ASK_CLIENT_PHONE,
            reply_markup=keyboards.skip_keyboard(),
        )
        return INV_CLIENT_PHONE

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.client_details_choice_keyboard(),
    )
    return INV_CLIENT_DETAILS_CHOICE


@_handler_safe
async def invoice_client_phone(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Optional client phone (Fix 4)."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT_PHONE
    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)
    val = "" if text == strings.BTN_SKIP else text
    context.user_data.setdefault("invoice", _new_invoice_draft()).setdefault(
        "client_details", {}
    )["phone"] = val
    await msg.reply_text(
        strings.ASK_CLIENT_ADDRESS,
        reply_markup=keyboards.skip_keyboard(),
    )
    return INV_CLIENT_ADDRESS


@_handler_safe
async def invoice_client_address(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Optional client address (Fix 4)."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT_ADDRESS
    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)
    val = "" if text == strings.BTN_SKIP else text
    context.user_data.setdefault("invoice", _new_invoice_draft()).setdefault(
        "client_details", {}
    )["address"] = val
    await msg.reply_text(
        strings.ASK_CLIENT_BANK,
        reply_markup=keyboards.skip_keyboard(),
    )
    return INV_CLIENT_BANK


@_handler_safe
async def invoice_client_bank(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Optional client bank account (Fix 4)."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT_BANK
    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)
    val = "" if text == strings.BTN_SKIP else text
    context.user_data.setdefault("invoice", _new_invoice_draft()).setdefault(
        "client_details", {}
    )["bank"] = val
    await msg.reply_text(
        strings.ASK_CLIENT_VAT,
        reply_markup=keyboards.skip_keyboard(),
    )
    return INV_CLIENT_VAT


@_handler_safe
async def invoice_client_vat(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Optional client VAT number (Fix 4)."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CLIENT_VAT
    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)
    val = "" if text == strings.BTN_SKIP else text
    context.user_data.setdefault("invoice", _new_invoice_draft()).setdefault(
        "client_details", {}
    )["vat"] = val
    return await _ask_date(update, context)


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
    """Return the draft's client_details dict if any field is populated,
    otherwise None. Used by the PDF generator to decide whether to render
    extra lines under the client name (Fix 4)."""
    details = (draft or {}).get("client_details") or {}
    if any((v or "").strip() if isinstance(v, str) else False for v in details.values()):
        return details
    return None


async def _generate_and_send_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Generate the invoice PDF, deliver it to the user, persist the currency
    default, record the invoice in tracking history, then show the after-PDF menu.
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
    if profile is None:
        await chat.send_message(strings.ERR_NO_PROFILE)
        return ConversationHandler.END

    currency = draft.get("currency", "EUR")
    invoice_date = draft.get("date") or date.today()
    due_date = draft.get("due_date")
    client = draft.get("client", "")
    client_details = _client_details_for_pdf(draft)

    invoice_number = profile_manager.next_invoice_number(user_id)
    pdf_path: Path | None = None
    try:
        pdf_path = pdf_generator.build_invoice(
            profile=profile,
            client=client,
            client_details=client_details,
            items=items,
            currency=currency,
            invoice_date=invoice_date,
            due_date=due_date,
            invoice_number=invoice_number,
        )
        with pdf_path.open("rb") as fh:
            await chat.send_document(
                document=fh,
                filename=pdf_path.name,
                caption=strings.PDF_READY.format(number=invoice_number),
            )
    finally:
        if pdf_path and pdf_path.exists():
            try:
                pdf_path.unlink()
            except OSError:
                pass

    # Persist the currency choice for next time
    profile_manager.set_default_currency(user_id, currency)

    # Record the invoice in tracking history
    total = sum(it.get("price", 0.0) for it in items)
    profile_manager.record_invoice(
        user_id=user_id,
        number=invoice_number,
        client=client,
        amount=total,
        currency=currency,
        invoice_date=invoice_date,
    )

    context.user_data.pop("invoice", None)
    await chat.send_message(
        strings.AFTER_PDF_PROMPT,
        reply_markup=keyboards.after_pdf_keyboard(),
    )
    return INV_AFTER_PDF


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
    """Invoice step 2b — handle every inline-calendar callback."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    action = ":".join(parts[:2])

    min_date, max_date = _cal_bounds()

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
        if last_of_new < min_date:
            return INV_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                new_year, new_month,
                min_date=min_date, max_date=max_date,
            )
        )
        return INV_CALENDAR

    if action == keyboards.CB_CAL_NEXT and len(parts) >= 4:
        year, month = int(parts[2]), int(parts[3])
        new_month, new_year = month + 1, year
        if new_month > 12:
            new_month, new_year = 1, year + 1
        first_of_new = date(new_year, new_month, 1)
        if first_of_new > max_date:
            return INV_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                new_year, new_month,
                min_date=min_date, max_date=max_date,
            )
        )
        return INV_CALENDAR

    if action == keyboards.CB_CAL_DAY and len(parts) >= 4:
        try:
            selected = date(int(parts[2]), int(parts[3]), int(parts[4]) if len(parts) >= 5 else 1)
        except (ValueError, IndexError):
            return INV_CALENDAR
        if not _is_valid_calendar_date(selected):
            await query.answer("Date out of allowed range.", show_alert=True)
            return INV_CALENDAR
        context.user_data.setdefault("invoice", _new_invoice_draft())["date"] = selected
        try:
            await query.message.delete()
        except Exception:
            pass
        return await _ask_item_name(update, context)

    return INV_CALENDAR


# =============================================================================
# === ITEM ENTRY ==============================================================
# =============================================================================

async def _ask_item_name(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Send the item-name prompt."""
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
    await msg.reply_text(
        strings.ASK_ITEM_PRICE,
        reply_markup=ReplyKeyboardRemove(),
    )
    return INV_ITEM_PRICE


@_handler_safe
async def invoice_item_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 4 — receive an item price (Fix 2: accepts decimals)."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(strings.ERR_NOT_TEXT)
        return INV_ITEM_PRICE

    text = msg.text.strip()
    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    try:
        price = _parse_price(text)
    except ValueError as exc:
        code = exc.args[0] if exc.args else "not_number"
        if code == "zero_negative":
            await msg.reply_text(strings.ERR_PRICE_ZERO)
        else:
            await msg.reply_text(strings.ERR_PRICE_INVALID)
        return INV_ITEM_PRICE

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    name = draft.pop("pending_item_name", "Item")
    draft.setdefault("items", []).append({"name": name, "price": price})

    currency = draft.get("currency", "EUR")
    summary = _format_invoice_summary(draft["items"], currency)
    await msg.reply_text(
        f"{summary}\n\n{strings.ITEM_ADDED_PROMPT}",
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """After adding an item — Add more / Remove last / Done / Currency."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_ADD_MORE

    text = msg.text.strip()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_ADD_ITEM:
        await msg.reply_text(
            strings.ASK_ITEM_NAME,
            reply_markup=keyboards.invoice_item_keyboard(),
        )
        return INV_ITEM_NAME

    if text == strings.BTN_REMOVE_LAST:
        items = draft.get("items", [])
        if items:
            removed = items.pop()
            currency = draft.get("currency", "EUR")
            summary = _format_invoice_summary(items, currency)
            await msg.reply_text(
                strings.ITEM_REMOVED.format(name=removed["name"])
                + (f"\n\n{summary}" if items else ""),
                reply_markup=_after_item_keyboard(draft),
            )
        else:
            await msg.reply_text(
                strings.ERR_NO_ITEMS,
                reply_markup=_after_item_keyboard(draft),
            )
        return INV_ADD_MORE

    if text == strings.BTN_CHANGE_CURRENCY:
        await msg.reply_text(
            strings.ASK_CURRENCY,
            reply_markup=keyboards.currency_keyboard(),
        )
        return INV_CURRENCY

    if text == strings.BTN_DONE:
        # Move on to due date step
        await msg.reply_text(
            strings.ASK_DUE_DATE,
            reply_markup=keyboards.due_date_keyboard(),
        )
        return INV_DUE_DATE

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=_after_item_keyboard(draft),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_currency(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Currency selection step."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CURRENCY

    text = msg.text.strip()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_CURRENCY_CUSTOM:
        await msg.reply_text(
            strings.ASK_CURRENCY_CUSTOM,
            reply_markup=ReplyKeyboardRemove(),
        )
        return INV_CURRENCY_CUSTOM

    # Built-in currency buttons like "EUR €", "USD $", etc.
    for code in ("EUR", "USD", "KZT"):
        if code in text:
            draft["currency"] = code
            currency = code
            summary = _format_invoice_summary(draft.get("items", []), currency)
            await msg.reply_text(
                strings.CURRENCY_SET.format(currency=currency)
                + f"\n\n{summary}",
                reply_markup=_after_item_keyboard(draft),
            )
            return INV_ADD_MORE

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.currency_keyboard(),
    )
    return INV_CURRENCY


@_handler_safe
async def invoice_currency_custom(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Custom currency code entry."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_CURRENCY_CUSTOM

    text = msg.text.strip().upper()
    if text == strings.BTN_CANCEL.upper():
        return await invoice_cancel(update, context)

    if not text or len(text) > 10:
        await msg.reply_text(strings.ERR_CURRENCY_INVALID)
        return INV_CURRENCY_CUSTOM

    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    draft["currency"] = text
    summary = _format_invoice_summary(draft.get("items", []), text)
    await msg.reply_text(
        strings.CURRENCY_SET.format(currency=text) + f"\n\n{summary}",
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
    """Due date step — No due date / +30 days / +60 days / Pick a date."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.due_date_keyboard(),
            )
        return INV_DUE_DATE

    text = msg.text.strip()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())
    invoice_date_val = draft.get("date") or date.today()

    if text == strings.BTN_CANCEL:
        return await invoice_cancel(update, context)

    if text == strings.BTN_NO_DUE_DATE:
        draft["due_date"] = None
        return await _generate_and_send_pdf(update, context)

    if text == strings.BTN_DUE_30:
        draft["due_date"] = invoice_date_val + timedelta(days=30)
        return await _generate_and_send_pdf(update, context)

    if text == strings.BTN_DUE_60:
        draft["due_date"] = invoice_date_val + timedelta(days=60)
        return await _generate_and_send_pdf(update, context)

    if text == strings.BTN_PICK_DATE:
        min_date, max_date = _cal_bounds()
        today = date.today()
        await msg.reply_text(
            strings.CALENDAR_PROMPT,
            reply_markup=keyboards.calendar_keyboard(
                today.year, today.month,
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
    """Due date — handle every inline-calendar callback."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    action = ":".join(parts[:2])

    min_date, max_date = _cal_bounds()
    draft = context.user_data.setdefault("invoice", _new_invoice_draft())

    if data == keyboards.CB_CAL_IGNORE:
        return INV_DUE_DATE_CALENDAR

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
        if last_of_new < min_date:
            return INV_DUE_DATE_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                new_year, new_month,
                min_date=min_date, max_date=max_date,
            )
        )
        return INV_DUE_DATE_CALENDAR

    if action == keyboards.CB_CAL_NEXT and len(parts) >= 4:
        year, month = int(parts[2]), int(parts[3])
        new_month, new_year = month + 1, year
        if new_month > 12:
            new_month, new_year = 1, year + 1
        first_of_new = date(new_year, new_month, 1)
        if first_of_new > max_date:
            return INV_DUE_DATE_CALENDAR
        await query.edit_message_reply_markup(
            reply_markup=keyboards.calendar_keyboard(
                new_year, new_month,
                min_date=min_date, max_date=max_date,
            )
        )
        return INV_DUE_DATE_CALENDAR

    if action == keyboards.CB_CAL_DAY and len(parts) >= 4:
        try:
            selected = date(int(parts[2]), int(parts[3]), int(parts[4]) if len(parts) >= 5 else 1)
        except (ValueError, IndexError):
            return INV_DUE_DATE_CALENDAR
        if not _is_valid_calendar_date(selected):
            await query.answer("Date out of allowed range.", show_alert=True)
            return INV_DUE_DATE_CALENDAR
        draft["due_date"] = selected
        try:
            await query.message.delete()
        except Exception:
            pass
        items = draft.get("items", [])
        currency = draft.get("currency", "EUR")
        summary = _format_invoice_summary(items, currency)
        chat = update.effective_chat
        await chat.send_message(
            f"{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
            reply_markup=_after_item_keyboard(draft),
        )
        return await _generate_and_send_pdf(update, context)

    return INV_DUE_DATE_CALENDAR


# =============================================================================
# === AFTER-PDF MENU ==========================================================
# =============================================================================

@_handler_safe
async def invoice_after_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """After PDF is sent — New invoice / Main menu."""
    msg = update.message
    if msg is None or not msg.text:
        return INV_AFTER_PDF

    text = msg.text.strip()
    if text == strings.BTN_CREATE_INVOICE:
        return await invoice_start(update, context)

    if text == strings.BTN_MAIN_MENU:
        await msg.reply_text(
            strings.MAIN_MENU_PROMPT,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.after_pdf_keyboard(),
    )
    return INV_AFTER_PDF


# =============================================================================
# === CANCEL ==================================================================
# =============================================================================

async def invoice_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel the current invoice flow."""
    context.user_data.pop("invoice", None)
    chat = update.effective_chat
    user_id = update.effective_user.id if update.effective_user else None
    has_prof = bool(user_id and profile_manager.has_profile(user_id))
    await chat.send_message(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def _invoice_cancel_from_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Cancel the invoice when triggered from an inline-keyboard callback."""
    query = update.callback_query
    context.user_data.pop("invoice", None)
    user_id = update.effective_user.id if update.effective_user else None
    has_prof = bool(user_id and profile_manager.has_profile(user_id))
    try:
        await query.message.delete()
    except Exception:
        pass
    chat = update.effective_chat
    await chat.send_message(
        strings.INVOICE_CANCELLED,
        reply_markup=keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# =============================================================================
# === PROFILE EDITING =========================================================
# =============================================================================

@_handler_safe
async def profile_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Show the profile-edit menu."""
    msg = update.message
    user_id = update.effective_user.id
    profile = profile_manager.get_profile(user_id)
    if profile is None:
        await msg.reply_text(strings.ERR_NO_PROFILE)
        return ConversationHandler.END

    await msg.reply_text(
        strings.PROFILE_MENU_PROMPT.format(
            org=profile.get("org", ""),
            phone=profile.get("phone", ""),
            account=profile.get("account", ""),
            references=profile.get("references", ""),
            email=profile.get("email", ""),
            vat=profile.get("vat") or strings.NOT_SET,
        ),
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


@_handler_safe
async def profile_edit_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Dispatch from the profile-edit menu."""
    msg = update.message
    if msg is None or not msg.text:
        return PE_MENU

    text = msg.text.strip()

    if text == strings.BTN_EDIT_ORG:
        await msg.reply_text(strings.ASK_ORG_NAME, reply_markup=ReplyKeyboardRemove())
        return PE_NAME

    if text == strings.BTN_EDIT_PHONE:
        await msg.reply_text(strings.ASK_PHONE, reply_markup=ReplyKeyboardRemove())
        return PE_PHONE

    if text == strings.BTN_EDIT_ACCOUNT:
        await msg.reply_text(strings.ASK_ACCOUNT, reply_markup=ReplyKeyboardRemove())
        return PE_ACCOUNT

    if text == strings.BTN_EDIT_REFERENCES:
        await msg.reply_text(strings.ASK_REFERENCES, reply_markup=ReplyKeyboardRemove())
        return PE_REFERENCES

    if text == strings.BTN_EDIT_EMAIL:
        await msg.reply_text(strings.ASK_EMAIL, reply_markup=ReplyKeyboardRemove())
        return PE_EMAIL

    if text == strings.BTN_EDIT_VAT:
        await msg.reply_text(
            strings.ASK_VAT,
            reply_markup=keyboards.skip_keyboard(),
        )
        return PE_VAT

    if text == strings.BTN_MAIN_MENU:
        await msg.reply_text(
            strings.MAIN_MENU_PROMPT,
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.profile_edit_keyboard(),
    )
    return PE_MENU


def _profile_edit_save(field: str):
    """Factory for profile-edit field handlers."""

    @_handler_safe
    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        msg = update.message
        if msg is None or not msg.text:
            return PE_MENU
        text = msg.text.strip()
        user_id = update.effective_user.id

        if field == "vat" and text == strings.BTN_SKIP:
            text = ""

        if field == "email" and text and not _is_valid_email(text):
            await msg.reply_text(strings.ERR_INVALID_EMAIL)
            return PE_EMAIL

        if text and len(text) > 200:
            await msg.reply_text(strings.ERR_LONG_TEXT.format(n=200))
            return PE_MENU

        profile_manager.update_profile_field(user_id, field, text)
        label = _strip_colon(strings.PROFILE_FIELD_LABELS.get(field, field))
        await msg.reply_text(
            strings.FIELD_UPDATED.format(field=label),
            reply_markup=keyboards.main_menu_keyboard(),
        )
        return ConversationHandler.END

    return handler


pe_name       = _profile_edit_save("org")
pe_phone      = _profile_edit_save("phone")
pe_account    = _profile_edit_save("account")
pe_references = _profile_edit_save("references")
pe_email      = _profile_edit_save("email")
pe_vat        = _profile_edit_save("vat")


# =============================================================================
# === MISC / UTILITY ==========================================================
# =============================================================================

@_handler_safe
async def cancel_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/cancel — abort whatever is in progress."""
    context.user_data.pop("invoice", None)
    context.user_data.pop("onboard", None)
    user_id = update.effective_user.id if update.effective_user else None
    has_prof = bool(user_id and profile_manager.has_profile(user_id))
    await update.message.reply_text(
        strings.CANCELLED,
        reply_markup=keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


@_handler_safe
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/help — show usage instructions."""
    await update.message.reply_text(
        strings.HELP_TEXT,
        reply_markup=keyboards.main_menu_keyboard()
        if profile_manager.has_profile(update.effective_user.id)
        else ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


@_handler_safe
async def history_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """/history — show recent invoices."""
    user_id = update.effective_user.id
    records = profile_manager.get_invoice_history(user_id)
    if not records:
        await update.message.reply_text(strings.NO_HISTORY)
        return ConversationHandler.END

    lines = [strings.HISTORY_HEADER]
    for r in records[-10:]:
        lines.append(
            strings.HISTORY_ROW.format(
                number=r.get("number", "?"),
                client=r.get("client", "?"),
                amount=_fmt_currency(r.get("amount", 0.0), r.get("currency", "EUR")),
                date=r.get("invoice_date", "?"),
            )
        )
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboards.main_menu_keyboard(),
    )
    return ConversationHandler.END


@_handler_safe
async def unknown_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Catch-all for messages outside a conversation."""
    user_id = update.effective_user.id if update.effective_user else None
    has_prof = bool(user_id and profile_manager.has_profile(user_id))
    await update.message.reply_text(
        strings.UNKNOWN_MSG,
        reply_markup=keyboards.main_menu_keyboard() if has_prof else ReplyKeyboardRemove(),
    )


# =============================================================================
# === HANDLER REGISTRATION ====================================================
# =============================================================================

def _is_valid_email(text: str) -> bool:
    """Return True if *text* looks like a plausible email address."""
    return bool(_EMAIL_REGEX.match(text))


_EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _strip_colon(label: str) -> str:
    """'Organization:' -> 'Organization' (for FIELD_UPDATED interpolation)."""
    return label.rstrip(":").strip()


def register_handlers(app: Application) -> None:
    """Register all ConversationHandlers and standalone handlers."""

    onboard_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ONBOARD_ORG: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_org)],
            ONBOARD_PHONE: [
                MessageHandler(filters.CONTACT, onboard_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_phone),
            ],
            ONBOARD_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_account)],
            ONBOARD_REFERENCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_references)],
            ONBOARD_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_email)],
            ONBOARD_VAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, onboard_vat)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )

    invoice_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(_exact(strings.BTN_CREATE_INVOICE)), invoice_start),
        ],
        states={
            INV_CLIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client)],
            INV_CLIENT_DETAILS_CHOICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_details_choice)
            ],
            INV_CLIENT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_phone)
            ],
            INV_CLIENT_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_address)
            ],
            INV_CLIENT_BANK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_bank)
            ],
            INV_CLIENT_VAT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_client_vat)
            ],
            INV_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_date)],
            INV_CALENDAR: [
                CallbackQueryHandler(invoice_calendar_callback),
            ],
            INV_ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_name)],
            INV_ITEM_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_item_price)],
            INV_ADD_MORE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_add_more)],
            INV_CURRENCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency)],
            INV_CURRENCY_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_currency_custom)
            ],
            INV_DUE_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_due_date)],
            INV_DUE_DATE_CALENDAR: [
                CallbackQueryHandler(invoice_due_date_calendar_callback),
            ],
            INV_AFTER_PDF: [MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_after_pdf)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )

    profile_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(_exact(strings.BTN_EDIT_PROFILE)), profile_menu),
        ],
        states={
            PE_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, profile_edit_choice)],
            PE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_name)],
            PE_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_phone)],
            PE_ACCOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_account)],
            PE_REFERENCES: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_references)],
            PE_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_email)],
            PE_VAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pe_vat)],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
        allow_reentry=True,
    )

    app.add_handler(onboard_conv)
    app.add_handler(invoice_conv)
    app.add_handler(profile_conv)
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
