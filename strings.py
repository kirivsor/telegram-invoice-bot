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
WELCOME_NEW = "\U0001f44b Hi {name}! I'll help you create professional PDF invoices."
WELCOME_BACK = "\U0001f44b Welcome back, {org_name}!"
PROFILE_INTRO = (
"Let's set up your profile first.\n"
"This takes about a minute and you only need to do it once."
)
RESTARTED = "Something went wrong. Please send /start to begin again."
BACK_TO_MAIN_MENU = "\U0001f3e0 Back to the main menu."
NOTHING_TO_CANCEL = "Nothing to cancel right now."

# Fallback for unrecognized text outside any active conversation.
FALLBACK_HAS_PROFILE = (
"\U0001f44b Hi! Tap a button below to continue, "
"or type /start to see the welcome screen."
)
FALLBACK_NO_PROFILE = (
"\U0001f44b Hello! To get started, please type /start"
)

# Buttons — main menu
BTN_CREATE_INVOICE = "\U0001f9fe Create invoice"
BTN_TRACK_INVOICES = "\U0001f4cb Track invoices"
BTN_EDIT_PROFILE = "\u270f\ufe0f Edit profile"
BTN_HELP = "\u2753 Help"

# Shared navigation buttons
BTN_CANCEL = "\u274c Cancel"
BTN_BACK = "\U0001f519 Back"
BTN_SKIP = "\u23ed\ufe0f Skip"
BTN_MAIN_MENU = "\U0001f3e0 Main menu"
BTN_PROFILE = "\u270f\ufe0f Edit profile"
BTN_SHARE_CONTACT = "\U0001f4de Share contact"

# =============================================================================
# === ONBOARDING ==============================================================
# =============================================================================

ASK_ORG = "\U0001f3e2 What is your organization or business name?"
ASK_PHONE = "\U0001f4de What is your phone number?"
ASK_EMAIL = (
"\u2709\ufe0f What is your email address?\n"
"_Optional \u2014 tap Skip if you'd rather not include one._"
)
ASK_VAT = (
"\U0001f3db\ufe0f What is your VAT number?\n"
"_Optional \u2014 tap Skip if you don't have one._"
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

# Skip buttons for optional fields (separate constants so handlers can route cleanly)
BTN_SKIP_EMAIL = "\u23ed\ufe0f Skip"
BTN_SKIP_VAT = "\u23ed\ufe0f Skip"
BTN_SKIP_DETAIL = "\u23ed\ufe0f Skip"

PROFILE_CREATED_HEADER = "\u2705 Profile created!"
PROFILE_DETAILS_LABEL = "Here's what I saved:"
EDIT_HINT = "You can change any of this later via \u270f\ufe0f Edit profile."

# =============================================================================
# === INVOICE CREATION ========================================================
# =============================================================================

ASK_CLIENT = "\U0001f464 Who is this invoice for? (Enter client name)"

# Client-details sub-flow (new)
ASK_CLIENT_DETAILS_CHOICE = "Would you like to add client details (phone, address, etc.)?"
BTN_ADD_CLIENT_DETAILS = "\u2705 Yes"
BTN_SKIP_CLIENT_DETAILS = "\u23ed\ufe0f No"
ASK_CLIENT_PHONE = (
"\U0001f4de Client's phone number?\n"
"_Optional \u2014 tap Skip if you don't have one._"
)
ASK_CLIENT_ADDRESS = (
"\U0001f4cd Client's address?\n"
"_Optional \u2014 tap Skip if you don't have one._"
)
ASK_CLIENT_BANK = (
"\U0001f3e6 Client's bank account / IBAN?\n"
"_Optional \u2014 tap Skip if you don't have one._"
)
ASK_CLIENT_VAT = (
"\U0001f3db\ufe0f Client's VAT number?\n"
"_Optional \u2014 tap Skip if they don't have one._"
)

ASK_DATE = "\U0001f4c5 What is the invoice date?"
CALENDAR_PROMPT = "\U0001f4c5 Pick a date:"
ASK_ITEM_NAME = "\U0001f4e6 What item or service are you invoicing for?"
ASK_ITEM_PRICE = "\U0001f4b6 What is the price for *{item_name}*? (e.g. 150 or 49.99)"
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

# Change currency button (prefix \u2014 handler appends currency code)
BTN_CHANGE_CURRENCY = "\U0001f4b6 Change currency"

# Date buttons
BTN_TODAY = "\U0001f4c5 Today"
BTN_YESTERDAY = "\U0001f4c5 Yesterday"
BTN_PICK_DATE = "\U0001f5d3 Pick a date"

# Invoice-item buttons
BTN_ADD_ANOTHER = "\u2795 Add another item"
BTN_ADD_ITEM = "\u2795 Add another item"
BTN_REMOVE_LAST = "\u274c Remove last item"
BTN_DONE = "\u2705 Create invoice"
BTN_CREATE_INVOICE_CONFIRM = "\u2705 Create invoice"
BTN_DUE_DATE = "\U0001f4c5 Set due date"
BTN_DUE_NET30 = "30 Days"
BTN_DUE_NET15 = "15 Days"
BTN_DUE_30 = "30 Days"
BTN_DUE_60 = "60 Days"
BTN_DUE_ON_RECEIPT = "On receipt"
BTN_DUE_CUSTOM = "\U0001f4c5 Pick a date"
BTN_NO_DUE_DATE = "\u23ed\ufe0f No due date"
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
BTN_CURRENCY_CUSTOM = "\u270f\ufe0f Other"

INVOICE_CANCELLED = "\u274c Invoice cancelled."

# =============================================================================
# === PROFILE EDITING =========================================================
# =============================================================================

PROFILE_HEADER = "\U0001f4cb *Your profile:*"
ORGANIZATION_LABEL = "\U0001f3e2 Organization:"
PHONE_LABEL = "\U0001f4de Phone:"
EMAIL_LABEL = "\u2709\ufe0f Email:"
VAT_LABEL = "\U0001f3db\ufe0f VAT:"
ACCOUNT_LABEL = "\U0001f3e6 Account:"
REFERENCES_LABEL = "\U0001f522 References:"

EDIT_PROMPT = "Which field would you like to update?"
EDIT_CANCELLED = "\u270f\ufe0f Edit cancelled."
FIELD_UPDATED = "\u2705 {field} updated."
EMAIL_CLEARED = "\u2705 Email cleared."
VAT_CLEARED = "\u2705 VAT number cleared."

# Reply-keyboard buttons for the profile-edit menu
BTN_EDIT_ORG = "\U0001f3e2 Organization"
BTN_EDIT_PHONE = "\U0001f4de Phone"
BTN_EDIT_EMAIL = "\u2709\ufe0f Email"
BTN_EDIT_VAT = "\U0001f3db\ufe0f VAT"
BTN_EDIT_ACCOUNT = "\U0001f3e6 Account"
BTN_EDIT_REFERENCES = "\U0001f522 References"

# =============================================================================
# === INVOICE TRACKING ========================================================
# =============================================================================

TRACK_INVOICES_HEADER = "\U0001f4cb *Your invoices*"
TRACK_INVOICES_EMPTY = (
"\U0001f4ed You haven't created any invoices yet.\n\n"
"Tap \U0001f9fe Create invoice to generate your first one."
)
TRACK_INVOICES_ALL_PAID = "\U0001f389 All invoices are marked paid!"
TRACK_MARK_PAID_PROMPT = "Select an invoice to mark as paid:"
BTN_TRACK_MARK_PAID = "\u2705 Mark as paid"
BTN_TRACK_BACK = "\u2b05\ufe0f Back"
INVOICE_MARKED_PAID = "\u2705 Marked as paid."
INVOICE_STATUS_PAID = "\u2705 Paid"
INVOICE_STATUS_UNPAID = "\u23f3 Unpaid"

# =============================================================================
# === HELP ====================================================================
# =============================================================================

HELP_TEXT = (
"\U0001f916 *Invoice Bot \u2014 Help*\n\n"
"*Create an invoice:*\n"
"Tap \U0001f9fe Create invoice and follow the prompts.\n\n"
"*Track invoices:*\n"
"Tap \U0001f4cb Track invoices to see what you've sent and mark items paid.\n\n"
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
ERR_INVALID_VAT = "Please enter a valid VAT number (3\u201320 characters) or tap Skip."
ERR_INVALID_ACCOUNT = "Please enter a valid account number or IBAN (5\u201340 characters)."
ERR_WRONG_BUTTON = "Please use one of the buttons below."
ERR_INVALID_PRICE = "Please enter a valid number (e.g. 150 or 49.99)."
ERR_ZERO_NEGATIVE_PRICE = "The price must be greater than zero."
ERR_INVALID_CURRENCY = "Please enter a 2\u20134 letter currency code (e.g. CHF)."
ERR_PDF_FAILURE = "\u274c Something went wrong generating your invoice. Please try again."

# =============================================================================
# === MID-FLOW ================================================================
# =============================================================================

MID_FLOW_RESTART_PROMPT = (
"Let's start over. Please complete your profile setup to use the bot."
)

# =============================================================================
# === ADDITIONS: TRACKING DISPLAY LABELS & MISSING CONSTANTS ==================
# =============================================================================

# Shown to users who haven't set up a profile yet.
PROMPT_START = "\U0001f44b Hi! Tap /start to set up your account."

# Tracking row labels
NO_CLIENT_LABEL = "No client"
REF_LABEL = "Ref:"
DATE_LABEL = "Date:"
DUE_LABEL = "Due:"

# Invoice-list display
INVOICE_LIST_HEADER = "\U0001f4cb *Your Invoices*"
NO_INVOICES_YET = "No invoices recorded yet."
ALL_INVOICES_PAID = "\U0001f389 All invoices are marked as paid!"
SELECT_INVOICE_TO_MARK = "Select an invoice to mark as paid:"

# Tracking flow buttons
BTN_MARK_AS_PAID = "\u2705 Mark as Paid"
BTN_BACK_TO_MENU = "\u2190 Back to Menu"

# =============================================================================
# === MISSING CONSTANTS (referenced in handlers.py) ===========================
# =============================================================================

# Onboarding
ASK_ORG_NAME = "\U0001f3e2 What is your organization or business name?"
ONBOARD_COMPLETE = (
"\u2705 Profile created! You're all set.\n\n"
"Tap \U0001f9fe Create invoice to get started."
)

# Invoice flow
NO_ITEMS_YET = "_No items added yet._"
ITEM_ADDED_PROMPT = "What would you like to do next?"
ITEM_REMOVED = "\u274c Removed: {name}"
AFTER_PDF_PROMPT = "What would you like to do next?"
PDF_READY = "\U0001f9fe Invoice #{number} is ready! Save it \u2014 it won\u2019t be stored on the server."

CURRENCY_SET = "\u2705 Currency set to *{currency}*."

# Errors
ERR_NO_PROFILE = "\u274c No profile found. Please type /start to set up your account."
ERR_NO_ITEMS = "\u274c No items to remove."
ERR_PRICE_ZERO = "\u274c Price must be greater than zero. Please try again."
ERR_PRICE_INVALID = "\u274c Please enter a valid number (e.g. 150 or 49.99)."
ERR_CURRENCY_INVALID = "\u274c Please enter a valid 2\u20134 letter currency code (e.g. CHF)."

# Profile editing
NOT_SET = "_not set_"
PROFILE_MENU_PROMPT = (
"\U0001f4cb *Your profile:*\n\n"
"\U0001f3e2 {org}\n"
"\U0001f4de {phone}\n"
"\u2709\ufe0f {email}\n"
"\U0001f3db\ufe0f VAT: {vat}\n"
"\U0001f3e6 {account}\n"
"\U0001f522 {references}\n\n"
"Which field would you like to update?"
)
PROFILE_FIELD_LABELS = {
"org": "\U0001f3e2 Organization:",
"phone": "\U0001f4de Phone:",
"email": "\u2709\ufe0f Email:",
"vat": "\U0001f3db\ufe0f VAT:",
"account": "\U0001f3e6 Account:",
"references": "\U0001f522 References:",
}

# General / navigation
MAIN_MENU_PROMPT = "\U0001f3e0 Main menu. What would you like to do?"
CANCELLED = "\u274c Cancelled."
UNKNOWN_MSG = (
"\U0001f44b Tap a button below to continue, or type /start to see the welcome screen."
)

# History command
NO_HISTORY = "\U0001f4ed No invoices recorded yet."
HISTORY_HEADER = "\U0001f4cb *Recent invoices:*"
HISTORY_ROW = "INV-{number:05d} \u2014 {client} \u2014 {amount} \u2014 {date}"
