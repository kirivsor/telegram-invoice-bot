"""All user-facing strings for the Telegram Invoice Bot.

Keeping every string here (rather than inline in handlers.py) makes
translation and copy-editing straightforward.
"""

# =============================================================================
# === GENERAL =================================================================
# =============================================================================

WELCOME = (
    "👋 Welcome to the Invoice Bot!\n"
    "I'll help you create professional PDF invoices in seconds."
)
WELCOME_BACK = "👋 Welcome back, {org_name}!"
PROFILE_INTRO = (
    "Let's set up your profile first.\n"
    "This takes about a minute and you only need to do it once."
)
RESTARTED = "Something went wrong. Please send /start to begin again."
BACK_TO_MAIN_MENU = "🏠 Back to the main menu."
NOTHING_TO_CANCEL = "Nothing to cancel right now."

# Buttons — main menu
BTN_CREATE_INVOICE = "🧾 Create invoice"
BTN_EDIT_PROFILE = "✏️ Edit profile"
BTN_HELP = "❓ Help"

# Shared navigation buttons
BTN_CANCEL = "❌ Cancel"
BTN_BACK = "⬅️ Back"

# =============================================================================
# === ONBOARDING ==============================================================
# =============================================================================

ASK_ORG = "🏢 What is your organization or business name?"
ASK_PHONE = "📞 What is your phone number?"
ASK_ACCOUNT = "🏦 What is your bank account number or IBAN?"
ASK_REFERENCES = (
    "🔢 How should invoice references be formatted?\n\n"
    "• Standard — e.g. INV-00042\n"
    "• None — no reference number on the invoice"
)

# Onboarding reference buttons
BTN_REF_STANDARD = "Standard"
BTN_REF_NONE = "None"

PROFILE_CREATED_HEADER = "✅ Profile created!"
PROFILE_DETAILS_LABEL = "Here's what I saved:"
EDIT_HINT = "You can change any of this later via ✏️ Edit profile."

# =============================================================================
# === INVOICE CREATION ========================================================
# =============================================================================

ASK_CLIENT = "👤 Who is this invoice for? (Enter client name)"
ASK_DATE = "📅 What is the invoice date?"
CALENDAR_PROMPT = "📅 Pick a date:"
ASK_ITEM_NAME = "📦 What item or service are you invoicing for?"
ASK_ITEM_PRICE = "💶 What is the price for *{item_name}*? (Whole numbers only, e.g. 150)"
ASK_CURRENCY = "💱 Which currency for this invoice?"
ASK_CURRENCY_CUSTOM = "✏️ Enter a currency code (e.g. CHF, SEK, NOK):"
WHATS_NEXT_PROMPT = "What would you like to do next?"
CURRENT_INVOICE_HEADER = "📋 *Current invoice:*"
TOTAL_LABEL = "💰 Total:"
ITEM_ADDED_PREFIX = "✅ Added: "
GENERATING_PDF = "⏳ Generating your invoice…"
INVOICE_DONE = "✅ Invoice #{number} is ready!"
STORAGE_HINT = "💾 Save this PDF — it won't be stored on the server."

# Save-client feature
ASK_SAVE_CLIENT = '\U0001f4be Save "{client_name}" for future invoices?'
BTN_SAVE_CLIENT = "\U0001f4be Save client"
BTN_SKIP_SAVE = "Skip"
CLIENT_SAVED = "\u2705 Client saved."
SAVED_CLIENTS_HINT = "Or pick a saved client:"

# Date buttons
BTN_TODAY = "📅 Today"
BTN_YESTERDAY = "📅 Yesterday"
BTN_PICK_DATE = "🗓 Pick a date"

# Invoice-item buttons
BTN_ADD_ANOTHER = "➕ Add another item"
BTN_CREATE_INVOICE_CONFIRM = "✅ Create invoice"

# No-name button (shown on the client-name keyboard)
BTN_NO_NAME = "👤 No name"

# After-PDF buttons
BTN_CREATE_ANOTHER = "🧾 Create another"
BTN_ALL_DONE = "✅ All done"

# Currency buttons
BTN_CURRENCY_EUR = "💶 EUR"
BTN_CURRENCY_USD = "💵 USD"
BTN_CURRENCY_KZT = "₸ KZT"
BTN_CURRENCY_OTHER = "✏️ Other"

INVOICE_CANCELLED = "❌ Invoice cancelled."

# =============================================================================
# === PROFILE EDITING =========================================================
# =============================================================================

PROFILE_HEADER = "📋 *Your profile:*"
ORGANIZATION_LABEL = "🏢 Organization:"
PHONE_LABEL = "📞 Phone:"
ACCOUNT_LABEL = "🏦 Account:"
REFERENCES_LABEL = "🔢 References:"

EDIT_PROMPT = "Which field would you like to update?"
EDIT_CANCELLED = "✏️ Edit cancelled."
FIELD_UPDATED = "✅ {field} updated."

# =============================================================================
# === HELP ====================================================================
# =============================================================================

HELP_TEXT = (
    "🤖 *Invoice Bot — Help*\n\n"
    "*Create an invoice:*\n"
    "Tap 🧾 Create invoice and follow the prompts.\n\n"
    "*Edit your profile:*\n"
    "Tap ✏️ Edit profile to update your business details.\n\n"
    "*Cancel anytime:*\n"
    "Send /cancel to stop the current flow.\n\n"
    "*Supported currencies:* EUR, USD, KZT, and any custom 2-4 letter code."
)

# =============================================================================
# === ERRORS ==================================================================
# =============================================================================

ERR_NOT_TEXT = "Please send a text message."
ERR_EMPTY = "This field cannot be empty. Please try again."
ERR_SHORT_TEXT = "That's too short. Please enter at least 2 characters."
ERR_LONG_TEXT = "That's too long (max {n} characters). Please shorten it."
ERR_INVALID_PHONE = "Please enter a valid phone number (3–30 characters)."
ERR_INVALID_ACCOUNT = "Please enter a valid account number or IBAN (5–40 characters)."
ERR_WRONG_BUTTON = "Please use one of the buttons below."
ERR_INVALID_PRICE = "Please enter a whole number (e.g. 150)."
ERR_DECIMAL_PRICE = "Please enter a whole number — no decimals (e.g. 150, not 150.50)."
ERR_ZERO_NEGATIVE_PRICE = "The price must be greater than zero."
ERR_INVALID_CURRENCY = "Please enter a 2–4 letter currency code (e.g. CHF)."
ERR_PDF_FAILURE = "❌ Something went wrong generating your invoice. Please try again."

# =============================================================================
# === MID-FLOW ================================================================
# =============================================================================

MID_FLOW_RESTART_PROMPT = (
    "Let's start over. Please complete your profile setup to use the bot."
)
