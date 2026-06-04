"""Entry point for the Telegram Invoice Bot.

Responsibilities (and nothing else):
  1. Configure logging.
  2. Initialise the database schema.
  3. Read BOT_TOKEN from the environment.
  4. Build the Telegram Application.
  5. Register handlers and start polling.
"""

import logging
import os

from telegram.ext import ApplicationBuilder

from handlers import register_handlers
from profile_manager import _init_db
import storage

# 1. Configure logging at INFO level with a clear, readable format.
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    # 2. Ensure the database schema exists before anything else runs.
    #    Safe to call on every deploy (CREATE TABLE IF NOT EXISTS).
    _init_db()
    storage.ensure_dirs()  # create the Railway Volume upload tree at startup

    # 3. Load the bot token from the environment. Fail fast if missing.
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add it to your Railway service variables."
        )

    logger.info("Bot is starting...")

    # 4. Build the Telegram Application (PTB v20+ async style).
    application = ApplicationBuilder().token(bot_token).build()

    # 5. Wire up all conversation/command handlers, then poll for updates.
    register_handlers(application)
    application.run_polling()


if __name__ == "__main__":
    main()
