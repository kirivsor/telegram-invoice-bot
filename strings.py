"""User-facing text constants for the Telegram Invoice Bot.

All text shown to users lives in this module. Use these exact strings;
do not paraphrase.

Template placeholders use Python str.format() / f-string syntax with
{name}. The source specification documents these as [name] — they are
rendered here as {name} so callers can do, e.g.:
    strings.WELCOME_BACK.format(org_name="Acme")
"""

# ─── Onboarding ──────────────────────────────────────────────────────────────
WELCOME = "👋 Welcome! I can create invoices as PDF."
PROFILE_INTRO = (
    "First, let's set up your profile. You only need to do this once, "
    "and all the information you enter will appear on every invoice "
    "automatically."
)
ASK_ORG = "What's the name of your organization?"
ASK_PHONE = "Great! What's your phone number?"
ASK_ACCOUNT = "What's your bank account number (IBAN)?"
ASK_REFERENCES = "Should I include a reference section on your invoices?"
PROFILE_CREATED_HEADER = "✅ Profile created!"
PROFILE_DETAILS_LABEL = "📋 Your details:"
ORGANIZATION_LABEL = "Organization:"
PHONE_LABEL = "Phone:"
ACCOUNT_LABEL = "Account:"
REFERENCES_LABEL = "References:"
EDIT_HINT = "You can edit these anytime via ✏️ Edit profile."

# ─── Main menu ───────────────────────────────────────────────────────────────
WELCOME_BACK = "👋 Hello, {org_name}!"
BTN_CREATE_INVOICE = "🧾 Create invoice"
BTN_EDIT_PROFILE = "✏️ Edit profile"
BTN_HELP = "❓ Help"

# ─── Onboarding references buttons ──────────────────────────────────────────
# Labels named in the keyboards section of the spec (Onboarding Step 5).
# Not listed in the English language reference, but required by the
# keyboard layout. Flagged in SELF-CHECK below.
BTN_REF_STANDARD = "Standard Form"
BTN_REF_NONE = "None needed"

# ─── Invoice creation ────────────────────────────────────────────────────────
ASK_CLIENT = (
    "Who is this invoice for?\n\n"
    "Enter the client's name or company name."
)
BTN_NO_NAME = "⛔️ No name"
SAVED_CLIENTS_HINT = "Or pick a saved client:"
ASK_DATE = "What's the invoice date?"
BTN_TODAY = "📅 Today"
BTN_YESTERDAY = "📅 Yesterday"
BTN_NEXT_MONDAY = "📅 Next Monday"
BTN_NEXT_FRIDAY = "📅 Next Friday"
BTN_PICK_DATE = "📆 Pick a date"
CALENDAR_PROMPT = "Pick a date:"
ASK_ITEM_NAME = (
    "What's the item or service name?\n\n"
    'For example: "Web design" or "Consultation"'
)
ASK_ITEM_PRICE = 'Price for "{item_name}"?\n\nJust the number. Example: 50000'
ITEM_ADDED_PREFIX = "✅ Added: "
CURRENT_INVOICE_HEADER = "📋 Current invoice:"
TOTAL_LABEL = "Total:"
WHATS_NEXT_PROMPT = "What's next?"
BTN_ADD_ANOTHER = "➕ Add another"
BTN_CREATE_INVOICE_CONFIRM = "✅ Create invoice"
BTN_CANCEL = "❌ Cancel"
GENERATING_PDF = "⏳ Creating your invoice, just a moment..."
INVOICE_DONE = "✅ Done! Invoice #{number}."
STORAGE_HINT = (
    "💡 All your invoices stay in this chat — "
    "use Telegram's search to find old ones."
)
BTN_CREATE_ANOTHER = "🧾 Create another"
BTN_ALL_DONE = "✅ All done"
BACK_TO_MAIN_MENU = "Back to main menu."
# ─── Save-client prompt (post-PDF) ───────────────────────────────────────────
ASK_SAVE_CLIENT = 'Save "{client_name}" for future invoices?'
BTN_SAVE_CLIENT = "💾 Save client"
BTN_SKIP_SAVE = "Skip"
CLIENT_SAVED = "✅ Client saved."
# ─── Calendar day-of-week headers ────────────────────────────────────────────
# Non-interactive header labels for the inline calendar keyboard.
# Named in the keyboards section of the spec; flagged in SELF-CHECK.
DOW_HEADERS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ─── Error messages ──────────────────────────────────────────────────────────
ERR_SHORT_TEXT = "Too short, try again."
ERR_LONG_TEXT = "Too long, please shorten to {n} characters."
ERR_EMPTY = "Can't be empty."
ERR_NOT_TEXT = "Please send your answer as text or use the buttons."
ERR_INVALID_PHONE = "Please send a valid phone number."
ERR_INVALID_ACCOUNT = "Please send a valid account number."
ERR_INVALID_PRICE = "That doesn't look like a number. Try again."
ERR_DECIMAL_PRICE = "Please use whole numbers only."
ERR_ZERO_NEGATIVE_PRICE = "Price must be greater than zero."
ERR_WRONG_BUTTON = "Please choose from the buttons below."
ERR_PDF_FAILURE = (
    "❌ Something went wrong creating your invoice. "
    "Please try again or send /start."
)

# ─── Cancel and restart ──────────────────────────────────────────────────────
INVOICE_CANCELLED = "❌ Invoice creation cancelled."
EDIT_CANCELLED = "❌ Edit cancelled."
NOTHING_TO_CANCEL = "Nothing to cancel. You're at the main menu."
RESTARTED = "Looks like I restarted. Let's start fresh."
MID_FLOW_RESTART_PROMPT = (
    "You need to complete the profile to use the bot. Should we start over?"
)

# ─── Profile editing ─────────────────────────────────────────────────────────
PROFILE_HEADER = "📋 Your profile:"
EDIT_PROMPT = "What would you like to change?"
BTN_EDIT_NAME = "✏️ Name"
BTN_EDIT_PHONE = "✏️ Phone"
BTN_EDIT_ACCOUNT = "✏️ Account"
BTN_EDIT_REFERENCES = "✏️ References"
BTN_DONE = "✅ Done"
FIELD_UPDATED = "✅ {field} updated!"

# Future feature — not wired yet. Reserved label for the planned
# logo-upload entry in the profile-edit menu.
BTN_UPLOAD_LOGO = "🖼 Upload logo"

# ─── Help text ───────────────────────────────────────────────────────────────
HELP_TEXT = (
    "👋 I help you create PDF invoices.\n"
    "What I do: 🧾 Create invoices with your business details "
    "✏️ Save your profile (business name, phone, account, references) "
    "📅 Help you pick the invoice date 📦 Add multiple items to one invoice\n"
    "Commands: /start — return to main menu "
    "/profile — view and edit your profile "
    "/cancel — cancel current action /help — this message\n"
    "Tip: all your invoices stay in this chat. "
    "Use Telegram's search to quickly find any invoice."
)
