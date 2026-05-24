"""All user-facing strings for the Telegram Invoice Bot.

Keeping every string here (rather than inline in handlers.py) makes
translation and copy-editing straightforward.
"""

# =============================================================================
# === GENERAL =================================================================
# =============================================================================

WELCOME = (
    "\U0001f44b Welcome to the Invoice Bot!\n"
    "I'll help you create professional PDF invoices in seconds."
)
WELCOME_BACK = "\U0001f44b Welcome back, {org_name}!"
PROFILE_INTRO = (
    "Let's set up your profile first.\n"
    "This takes about a minute and you only need to do it once."
)
RESTARTED = "Something went wrong. Please send /start to begin again."
BACK_TO_MAIN_MENU = "\U0001f3e0 Back to the main menu."
NOTHING_TO_CANCEL = "Nothing to cancel right now."

# Buttons — main menu
BTN_CREATE_INVOICE = "\U0001f9fe Create invoice"
BTN_EDIT_PROFILE = "\u270f\ufe0f Edit profile"
BTN_HELP = "\u2753 Help"

# Shared navigation buttons
BTN_CANCEL = "\u274c Cancel"
BTN_BACK = "\U0001f519 Back"

# =============================================================================
# === ONBOARDING ==============================================================
# =============================================================================

ASK_ORG = "\U0001f3e2 What is your organization or business name?"
ASK_PHONE = "\U0001f4de What is your phone number?"
ASK_EMAIL = (
    "\u2709\ufe0f What is your email address?\n"
    "_Optional — tap Skip if you'd rather not include one._"
)
ASK_ACCOUNT = "\U0001f3e6 What is your bank account number or IBAN?"
ASK_REFERENCES = (
    "\U0001f522 How should invoice references be formatted?\n\n"
    "\u2022 Standard \u2014 e.g. INV-00042\n"
    "\u2022 None \u2014 no reference number on the invoice"
)

# Onboarding reference buttons
BTN_REF_STANDARD = "Standard"
BTN_REF_NONE = "None"

# Email skip button (distinct from BTN_SKIP_SAVE so handlers can route cleanly)
BTN_SKIP_EMAIL = "\u23ed\ufe0f Skip"

PROFILE_CREATED_HEADER = "\u2705 Profile created!"
PROFILE_DETAILS_LABEL = "Here's what I saved:"
EDIT_HINT = "You can change any of this later via \u270f\ufe0f Edit profile."

# =============================================================================
# === INVOICE CREATION ========================================================
# =============================================================================

ASK_CLIENT = "\U0001f464 Who is this invoice for? (Enter client name)"
ASK_DATE = "\U0001f4c5 What is the invoice date?"
CALENDAR_PROMPT = "\U0001f4c5 Pick a date:"
ASK_ITEM_NAME = "\U0001f4e6 What item or service are you invoicing for?"
ASK_ITEM_PRICE = "\U0001f4b6 What is the price for *{item_name}*? (Whole numbers only, e.g. 150)"
ASK_CURRENCY = "\U0001f4b1 Which currency for this invoice?"
ASK_CURRENCY_CUSTOM = "\u270f\ufe0f Enter a currency code (e.g. CHF, SEK, NOK):"
WHATS_NEXT_PROMPT = "What would you like to do next?"
CURRENT_INVOICE_HEADER = "\U0001f4cb *Current invoice:*"
TOTAL_LABEL = "\U0001f4b0 Total:"
ITEM_ADDED_PREFIX = "\u2705 Added: "
GENERATING_PDF = "\u23f3 Generating your invoice\u2026"
INVOICE_DONE = "\u2705 Invoice #{number} is ready!"
STORAGE_HINT = "\U0001f4be Save this PDF \u2014 it won't be stored on the server."

# Save-client feature
BTN_SAVE_CLIENT = "\U0001f4be Save client"
BTN_SKIP_SAVE = "Skip"
CLIENT_SAVED = "\u2705 Client saved."
CLIENT_SAVED_INLINE = "\u2705 Client saved"
SAVED_CLIENTS_HINT = "Or pick a saved client:"

# Change currency button (prefix — handler appends currency code)
BTN_CHANGE_CURRENCY = "\U0001f4b6 Change currency"

# Date buttons
BTN_TODAY = "\U0001f4c5 Today"
BTN_YESTERDAY = "\U0001f4c5 Yesterday"
BTN_PICK_DATE = "\U0001f5d3 Pick a date"

# Invoice-item buttons
BTN_ADD_ANOTHER = "\u2795 Add another item"
BTN_CREATE_INVOICE_CONFIRM = "\u2705 Create invoice"
BTN_DUE_DATE = "\U0001f4c5 Set due date"
BTN_DUE_NET30 = "30 Days"
BTN_DUE_NET15 = "15 Days"
BTN_DUE_ON_RECEIPT = "On receipt"
BTN_DUE_CUSTOM = "\U0001f4c5 Pick a date"
ASK_DUE_DATE = "\U0001f4c5 When is payment due?"
ASK_DUE_DATE_CUSTOM = "\u270f\ufe0f Enter the due date (same format as invoice date):"
DUE_DATE_SET = "\u2705 Due date set: {due_date}"
DUE_DATE_LABEL = "Due date:"

# No-name button (shown on the client-name keyboard)
BTN_NO_NAME = "\U0001f464 No name"

# After-PDF buttons
BTN_CREATE_ANOTHER = "\U0001f9fe Create another"
BTN_ALL_DONE = "\u2705 All done"

# Currency buttons
BTN_CURRENCY_EUR = "\U0001f4b6 EUR"
BTN_CURRENCY_USD = "\U0001f4b5 USD"
BTN_CURRENCY_KZT = "\u20b8 KZT"
BTN_CURRENCY_OTHER = "\u270f\ufe0f Other"

INVOICE_CANCELLED = "\u274c Invoice cancelled."

# =============================================================================
# === PROFILE EDITING =========================================================
# =============================================================================

PROFILE_HEADER = "\U0001f4cb *Your profile:*"
ORGANIZATION_LABEL = "\U0001f3e2 Organization:"
PHONE_LABEL = "\U0001f4de Phone:"
EMAIL_LABEL = "\u2709\ufe0f Email:"
ACCOUNT_LABEL = "\U0001f3e6 Account:"
REFERENCES_LABEL = "\U0001f522 References:"

EDIT_PROMPT = "Which field would you like to update?"
EDIT_CANCELLED = "\u270f\ufe0f Edit cancelled."
FIELD_UPDATED = "\u2705 {field} updated."
EMAIL_CLEARED = "\u2705 Email cleared."

# =============================================================================
# === HELP ====================================================================
# =============================================================================

HELP_TEXT = (
    "\U0001f916 *Invoice Bot \u2014 Help*\n\n"
    "*Create an invoice:*\n"
    "Tap \U0001f9fe Create invoice and follow the prompts.\n\n"
    "*Edit your profile:*\n"
    "Tap \u270f\ufe0f Edit profile to update your business details.\n\n"
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
ERR_INVALID_PHONE = "Please enter a valid phone number (3\u201330 characters)."
ERR_INVALID_EMAIL = (
    "That doesn't look like a valid email address. "
    "Please try again or tap Skip."
)
ERR_INVALID_ACCOUNT = "Please enter a valid account number or IBAN (5\u201340 characters)."
ERR_WRONG_BUTTON = "Please use one of the buttons below."
ERR_INVALID_PRICE = "Please enter a whole number (e.g. 150)."
ERR_DECIMAL_PRICE = "Please enter a whole number \u2014 no decimals (e.g. 150, not 150.50)."
ERR_ZERO_NEGATIVE_PRICE = "The price must be greater than zero."
ERR_INVALID_CURRENCY = "Please enter a 2\u20134 letter currency code (e.g. CHF)."
ERR_PDF_FAILURE = "\u274c Something went wrong generating your invoice. Please try again."

# =============================================================================
# === MID-FLOW ================================================================
# =============================================================================

MID_FLOW_RESTART_PROMPT = (
    "Let's start over. Please complete your profile setup to use the bot."
)
