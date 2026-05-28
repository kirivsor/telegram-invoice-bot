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

# =============================================================================
# === HELPERS =================================================================
# =============================================================================