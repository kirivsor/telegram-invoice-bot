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