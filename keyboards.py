"""Entry point for the Telegram Invoice Bot.

Responsibilities (and nothing else):
  1. Configure logging.
  2. Read BOT_TOKEN from the environment.
  3. Build the Telegram Application.
  4. Register handlers and start polling.
"""

import logging
import os

from telegram.ext import ApplicationBuilder

from handlers import register_handlers


# 1. Configure logging at INFO level with a clear, readable format.
logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot."""
    # 2. Load the bot token from the environment. Fail fast if missing.
    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError(
            "BOT_TOKEN environment variable is not set. "
            "Add it to Replit Secrets."
        )

    logger.info("Bot is starting...")

    # 3. Build the Telegram Application (PTB v20+ async style).
    application = ApplicationBuilder().token(bot_token).build()

    # 4. Wire up all conversation/command handlers, then poll for updates.
    register_handlers(application)
    application.run_polling()


if __name__ == "__main__":
    main()
