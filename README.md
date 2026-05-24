# telegram-invoice-bot

A Telegram bot that guides users through a step-by-step conversation flow and generates a professional **PDF invoice** at the end.

---

## Features

- Guided multi-step invoice flow (client → date → line items → totals)
- Cancel button (`❌ Cancel`) works at every step of the flow
- Generates a clean PDF invoice sent directly in the chat
- Seller profile management (save & reuse your company details)
- "Add more items" loop with running subtotal
- Today shortcut button for invoice date

---

## Tech Stack

| Layer | Library |
|---|---|
| Bot framework | [python-telegram-bot v20+](https://github.com/python-telegram-bot/python-telegram-bot) (async) |
| PDF generation | `pdf_generator.py` (custom) |
| Runtime | Python 3.10+ |

---

## Project Structure

```
telegram-invoice-bot/
├── main.py              # Entry point — builds app, registers handlers, starts polling
├── handlers.py          # All ConversationHandler steps and command handlers
├── keyboards.py         # ReplyKeyboardMarkup builders
├── strings.py           # All user-facing strings and button labels (single source of truth)
├── pdf_generator.py     # Builds and returns the PDF bytes
├── profile_manager.py   # Saves/loads seller profile per Telegram user ID
├── assets/              # Static assets used in PDF generation
└── requirements.txt
```

---

## Setup

### 1. Clone & install dependencies

```bash
git clone https://github.com/kirivsor/telegram-invoice-bot.git
cd telegram-invoice-bot
pip install -r requirements.txt
```

### 2. Set the bot token

The bot reads `BOT_TOKEN` from the environment. On **Replit**, add it to Secrets. Locally:

```bash
export BOT_TOKEN="your-telegram-bot-token"
```

Get a token from [@BotFather](https://t.me/BotFather) on Telegram.

### 3. Run

```bash
python main.py
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |

---

## Invoice Flow

```
/start
  └─ /invoice
       ├─ Client name
       ├─ Invoice date  (or "Today" shortcut)
       ├─ Item name  ──┐
       ├─ Item price   │  repeats
       ├─ Add more? ───┘
       └─ PDF generated & sent
```

At any step, pressing **❌ Cancel** aborts the flow and returns to the main menu.

---

## License

MIT
