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

from telegram import ReplyKeyboardRemove, Update
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
INV_ADD_MORE = 205
INV_AFTER_PDF = 206
INV_SAVE_CLIENT = 207

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


def _format_eur(amount: float | int) -> str:
    """Format an amount as €X,XXX.XX"""
    return f"€{amount:,.2f}"


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


def _format_invoice_summary(items: list[dict[str, Any]]) -> str:
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
        lines.append(f"{item['name']} — {_format_eur(item['price'])}")
    total = sum(int(item["price"]) for item in items)
    lines.append("")
    lines.append(f"{strings.TOTAL_LABEL} {_format_eur(total)}")
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
async def invoice_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Begin a new invoice — step 1 of Flow 3."""
    user_id = update.effective_user.id
    if not profile_manager.has_profile(user_id):
        await update.message.reply_text(
            strings.RESTARTED, reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    context.user_data["invoice"] = _new_invoice_draft()

    # If the user has saved clients, surface them as tap-to-fill buttons.
    saved_clients = profile_manager.get_saved_clients(user_id)
    if saved_clients:
        message_text = f"{strings.ASK_CLIENT}\n\n{strings.SAVED_CLIENTS_HINT}"
        reply_markup = keyboards.saved_clients_keyboard(saved_clients)
    else:
        message_text = strings.ASK_CLIENT
        reply_markup = keyboards.invoice_client_keyboard()

    await update.message.reply_text(message_text, reply_markup=reply_markup)
    return INV_CLIENT

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
    """Invoice step 2 — Today / Yesterday / Next Mon / Next Fri / Pick a date."""
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

    if text == strings.BTN_TODAY:
        context.user_data["invoice"]["date"] = today
        return await _ask_item_name(update, context)

    if text == strings.BTN_YESTERDAY:
        context.user_data["invoice"]["date"] = today - timedelta(days=1)
        return await _ask_item_name(update, context)

    if text == strings.BTN_NEXT_MONDAY:
        # Monday is weekday 0. If today is Monday, skip to next week's Monday.
        days_ahead = (0 - today.weekday()) % 7 or 7
        context.user_data["invoice"]["date"] = today + timedelta(days=days_ahead)
        return await _ask_item_name(update, context)

    if text == strings.BTN_NEXT_FRIDAY:
        # Friday is weekday 4. If today is Friday, skip to next week's Friday.
        days_ahead = (4 - today.weekday()) % 7 or 7
        context.user_data["invoice"]["date"] = today + timedelta(days=days_ahead)
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
    action = ":".join(parts[:2])  # e.g. "cal:day"

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
        # If entire previous month is before the 12-month window, ignore.
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
        # Don't navigate into a future month.
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

    added_line = f"{strings.ITEM_ADDED_PREFIX}{name} — {_format_eur(price)}"
    summary = _format_invoice_summary(draft["items"])
    await msg.reply_text(
        f"{added_line}\n\n{summary}\n\n{strings.WHATS_NEXT_PROMPT}",
        reply_markup=keyboards.invoice_after_item_keyboard(),
    )
    return INV_ADD_MORE


@_handler_safe
async def invoice_add_more(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step 5 — add another / finalize."""
    msg = update.message
    if msg is None or not msg.text:
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.invoice_after_item_keyboard(),
            )
        return INV_ADD_MORE

    text = msg.text.strip()
    if text == strings.BTN_ADD_ANOTHER:
        return await _ask_item_name(update, context)
    if text == strings.BTN_CREATE_INVOICE_CONFIRM:
        return await _finalize_invoice(update, context)

    await msg.reply_text(
        strings.ERR_WRONG_BUTTON,
        reply_markup=keyboards.invoice_after_item_keyboard(),
    )
    return INV_ADD_MORE


async def _finalize_invoice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Generate the PDF, deliver it, and only then increment the counter.

    Spec rule: PDF generation runs BEFORE increment_invoice_number(),
    and the counter is only bumped on a successful PDF.
    """
    chat = update.effective_chat
    user_id = update.effective_user.id
    draft = context.user_data.get("invoice", {})
    items = draft.get("items", [])

    # Edge case 10 — empty invoice defensive guard.
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

    # --- Generate PDF first. Only increment counter on success. ---
    try:
        pdf_path: Path = pdf_generator.generate_invoice_pdf(
            invoice_number=next_number,
            invoice_date=invoice_date_value,
            client_name=client_name,
            items=items,
            profile=profile,
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

    # PDF written; now commit the invoice number.
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

    # If the invoice had a named client, offer to save it before
    # showing the post-PDF menu. Keep the invoice draft in user_data
    # so invoice_save_client can read client_name — it will be popped
    # there. If there's no client name, skip straight to INV_AFTER_PDF.
    if client_name:
        await chat.send_message(
            strings.ASK_SAVE_CLIENT.format(client_name=client_name),
            reply_markup=keyboards.save_client_keyboard(),
        )
        return INV_SAVE_CLIENT

    await chat.send_message(
        strings.WHATS_NEXT_PROMPT,
        reply_markup=keyboards.invoice_after_pdf_keyboard(),
    )
    context.user_data.pop("invoice", None)
    return INV_AFTER_PDF

@_handler_safe
async def invoice_save_client(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Post-PDF step — save the client name, or skip, then show the
    after-PDF menu."""
    msg = update.message
    text = (msg.text or "").strip() if msg else ""

    if text not in (strings.BTN_SAVE_CLIENT, strings.BTN_SKIP_SAVE):
        if msg is not None:
            await msg.reply_text(
                strings.ERR_WRONG_BUTTON,
                reply_markup=keyboards.save_client_keyboard(),
            )
        return INV_SAVE_CLIENT

    if text == strings.BTN_SAVE_CLIENT:
        user_id = update.effective_user.id
        draft = context.user_data.get("invoice", {})
        client_name = draft.get("client_name")
        if client_name:
            try:
                profile_manager.save_client(user_id, client_name)
            except (KeyError, OSError):
                logger.exception(
                    "Failed to save client for user_id=%s", user_id
                )
            else:
                await update.effective_chat.send_message(
                    strings.CLIENT_SAVED
                )

    # Either way, move on to the standard after-PDF menu.
    context.user_data.pop("invoice", None)
    await update.effective_chat.send_message(
        strings.WHATS_NEXT_PROMPT,
        reply_markup=keyboards.invoice_after_pdf_keyboard(),
    )
    return INV_AFTER_PDF

@_handler_safe
async def invoice_after_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Invoice step after PDF — Create another / All done / anything else."""
    msg = update.message
    text = (msg.text or "").strip() if msg else ""

    if text == strings.BTN_CREATE_ANOTHER:
        return await invoice_start(update, context)

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
    """Route the inline edit-menu callbacks (Name / Phone / Account /
    References / Done)."""
    # TODO: wire CB_UPLOAD_LOGO when logo upload flow is built.
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
    """Catch stray text while the inline edit menu is active.

    Prevents unexpected text from leaking into other conversation entry
    points (e.g. triggering the invoice flow from the profile menu).
    """
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
    """Update one or more profile fields and emit FIELD_UPDATED.

    Returns the refreshed profile, or None on failure.
    """
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
    """/cancel mid-profile-edit — discard partial input and return to
    the profile view (not the main menu, per spec Flow 4)."""
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
# === STANDALONE COMMANDS (outside conversations) ==============================
# =============================================================================

@_handler_safe
async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/help or ❓ Help button — show help text and main menu keyboard."""
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
    """/cancel outside any active conversation — nothing to cancel."""
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
    """Catch-all for unexpected text messages at the top level.

    Returning users see the main menu. New users are prompted to /start.
    """
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

    Called once from main.py during bot startup.

    Order matters:
    1. ConversationHandlers first — they intercept messages in active flows.
    2. Top-level CommandHandlers for /help and /cancel outside flows.
    3. Catch-all MessageHandler last.
    """

    # -----------------------------------------------------------------
    # Onboarding conversation
    # Entry: /start when user has no profile (start_command returns a state).
    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
    # Invoice creation conversation
    # Entry: "🧾 Create invoice" button text.
    # -----------------------------------------------------------------
    invoice_conv = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Regex(_exact(strings.BTN_CREATE_INVOICE)),
                invoice_start,
            ),
            MessageHandler(
                filters.Regex(_exact(strings.BTN_CREATE_ANOTHER)),
                invoice_start,
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
            INV_SAVE_CLIENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, invoice_save_client),
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

    # -----------------------------------------------------------------
    # Profile editing conversation
    # Entry: "✏️ Edit profile" button or /profile command.
    # -----------------------------------------------------------------
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

    # Register conversation handlers (order: most specific first).
    application.add_handler(onboarding_conv)
    application.add_handler(invoice_conv)
    application.add_handler(profile_conv)

    # Top-level standalone commands (active outside any conversation).
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel_command_global))
    application.add_handler(
        MessageHandler(
            filters.Regex(_exact(strings.BTN_HELP)),
            help_command,
        )
    )

    # Catch-all — must be last.
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_handler)
    )

    logger.info("All handlers registered successfully.")
