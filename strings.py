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

# Default VAT rate (onboarding + profile edit)
ASK_VAT_RATE = (
"\U0001f4ca What is your default VAT rate?\n"
"Enter a number \u2014 e.g. 21 for 21%, or 0 if you're not VAT registered.\n"
"_You can override this on any individual invoice._"
)
BTN_VAT_RATE_SKIP = "\u23ed\ufe0f Skip / 0%"
VAT_RATE_LABEL = "\U0001f4ca Default VAT:"
VAT_RATE_SET = "\u2705 Default VAT rate set to {rate}%."
ERR_INVALID_VAT_RATE = (
"Please enter a VAT rate between 0 and 100 (e.g. 21 or 5.5), or tap Skip."
)

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
ASK_CURRENCY_BASE = (
"\U0001f4b1 What is your default currency?\n"
"You can change this per invoice later."
)
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

# Per-invoice VAT rate (override). Prefix \u2014 handler appends "(N%)".
BTN_SET_VAT = "\U0001f4ca VAT rate"
ASK_INVOICE_VAT_RATE = (
"\U0001f4ca VAT rate for this invoice?\n"
"Enter a number \u2014 e.g. 21 for 21%, or 0 for none."
)
INVOICE_VAT_SET = "\u2705 VAT rate set to {rate}% for this invoice."

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
BTN_CURRENCY_RUB = "\u20bd RUB"
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
CURRENCY_LABEL = "\U0001f4b1 Currency:"

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
BTN_EDIT_VAT_RATE = "\U0001f4ca Default VAT"

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
"*\U0001f680 Getting Started*\n"
"Send /start any time to see the main menu. Set up your business profile "
"once and every document you create is filled in automatically.\n\n"
"*\U0001f4dd Quotes*\n"
"Tap \U0001f4dd Create quote to send a client a price proposal before work "
"is confirmed. From \U0001f4c1 My quotes you can send a quote, edit it, or "
"convert an accepted quote straight into an invoice \u2014 line items, "
"amounts and currency all carry over.\n\n"
"*\U0001f9fe Invoices*\n"
"Tap \U0001f9fe Create invoice and follow the prompts: pick a client, add "
"one or more line items, optionally set a due date and VAT rate, then "
"generate a polished PDF.\n\n"
"*\U0001f9fe Receipts*\n"
"Tap \U0001f9fe Create receipt for a standalone receipt, or mark an invoice "
"as paid under \U0001f4cb Track invoices to generate one automatically.\n\n"
"*\u270f\ufe0f Profile*\n"
"Tap \u270f\ufe0f Edit profile to update your business name, phone, email, "
"VAT number, bank details, reference style, and default VAT rate.\n\n"
"*\U0001f4a1 Tips*\n"
"\u2022 Save a client once and reuse them on future documents.\n"
"\u2022 Add several line items to a single invoice or quote.\n"
"\u2022 Send /cancel any time to stop the current flow.\n"
"\u2022 Supported currencies: EUR, USD, RUB, KZT, and any custom 2\u20134 "
"letter code."
)

# Inline "Back to Menu" button shown beneath the Help message.
BTN_HELP_BACK_TO_MENU = "\U0001f3e0 Back to Menu"
CB_HELP_BACK_TO_MENU = "help:back"

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

# =============================================================================
# === LANGUAGE SUPPORT (foundation for Feature 2) =============================
# =============================================================================

# Language-picker buttons. Not yet wired into onboarding — see Feature 2.
BTN_LANG_EN = "\U0001f1ec\U0001f1e7 English"
BTN_LANG_RU = "\U0001f1f7\U0001f1fa \u0420\u0443\u0441\u0441\u043a\u0438\u0439"


def get_string(key: str, lang: str = "en") -> str:
    """Return the string for `key` in `lang`. Falls back to English.

    Used everywhere user-facing copy is needed once Feature 2 lands.
    Lookup rule:
        lang == "ru" -> try `{key}_RU`, then `{key}`, then "".
        otherwise    -> try `{key}`, then "".

    Today, with no `_RU` constants defined, every call returns the
    English version — i.e. behavior is identical to the current
    `strings.FOO` lookups. Safe to start threading through handlers.
    """
    if lang == "ru":
        ru_val = globals().get(f"{key}_RU")
        if ru_val is not None:
            return ru_val
    return globals().get(key, "")

# =============================================================================
# === RUSSIAN TRANSLATIONS ====================================================
# =============================================================================

WELCOME_RU = "👋 Добро пожаловать в Invoice Bot!\nЯ помогу создать профессиональный PDF-счёт за секунды."
WELCOME_NEW_RU = "👋 Привет, {name}! Я помогу создавать профессиональные PDF-счета."
WELCOME_BACK_RU = "👋 С возвращением, {org_name}!"
PROFILE_INTRO_RU = "Давайте настроим ваш профиль.\nЭто займёт около минуты и делается только один раз."
RESTARTED_RU = "Что-то пошло не так. Отправьте /start, чтобы начать заново."
BACK_TO_MAIN_MENU_RU = "🏠 Вернуться в главное меню."
NOTHING_TO_CANCEL_RU = "Нечего отменять."
FALLBACK_HAS_PROFILE_RU = "👋 Привет! Нажмите кнопку ниже или введите /start."
FALLBACK_NO_PROFILE_RU = "👋 Привет! Для начала введите /start"

BTN_CREATE_INVOICE_RU = "🧾 Создать счёт"
BTN_TRACK_INVOICES_RU = "📋 Счета"
BTN_EDIT_PROFILE_RU = "✏️ Редактировать профиль"
BTN_HELP_RU = "❓ Помощь"
BTN_CANCEL_RU = "❌ Отмена"
BTN_BACK_RU = "🔙 Назад"
BTN_SKIP_RU = "⏭️ Пропустить"
BTN_MAIN_MENU_RU = "🏠 Главное меню"
BTN_PROFILE_RU = "✏️ Редактировать профиль"
BTN_SHARE_CONTACT_RU = "📞 Поделиться контактом"

ASK_ORG_RU = "🏢 Как называется ваша организация или бизнес?"
ASK_ORG_NAME_RU = "🏢 Как называется ваша организация или бизнес?"
ASK_PHONE_RU = "📞 Укажите ваш номер телефона."
ASK_EMAIL_RU = "✉️ Укажите email.\n_Необязательно — нажмите Пропустить._"
ASK_VAT_RU = "🏛️ Укажите номер НДС.\n_Необязательно — нажмите Пропустить._"
ASK_ACCOUNT_RU = "🏦 Укажите номер счёта или IBAN."
ASK_REFERENCES_RU = "🔢 Как нумеровать счета?\n\n• Стандартный — напр. INV-00042\n• Без номера"
BTN_REF_STANDARD_RU = "Стандартный"
BTN_REF_NONE_RU = "Без номера"
ASK_VAT_RATE_RU = (
"📊 Какая у вас ставка НДС по умолчанию?\n"
"Введите число — например, 21 для 21%, или 0, если вы не плательщик НДС.\n"
"_Можно изменить для любого счёта._"
)
BTN_VAT_RATE_SKIP_RU = "⏭️ Пропустить / 0%"
VAT_RATE_LABEL_RU = "📊 НДС по умолчанию:"
VAT_RATE_SET_RU = "✅ Ставка НДС по умолчанию: {rate}%."
ERR_INVALID_VAT_RATE_RU = (
"Введите ставку НДС от 0 до 100 (например, 21 или 5.5) или нажмите Пропустить."
)
BTN_SET_VAT_RU = "📊 Ставка НДС"
ASK_INVOICE_VAT_RATE_RU = (
"📊 Ставка НДС для этого счёта?\n"
"Введите число — например, 21 для 21%, или 0."
)
INVOICE_VAT_SET_RU = "✅ Ставка НДС {rate}% для этого счёта."
BTN_EDIT_VAT_RATE_RU = "📊 НДС по умолчанию"
BTN_SKIP_EMAIL_RU = "⏭️ Пропустить"
BTN_SKIP_VAT_RU = "⏭️ Пропустить"
BTN_SKIP_DETAIL_RU = "⏭️ Пропустить"
PROFILE_CREATED_HEADER_RU = "✅ Профиль создан!"
PROFILE_DETAILS_LABEL_RU = "Вот что я сохранил:"
EDIT_HINT_RU = "Изменить можно через ✏️ Редактировать профиль."
ONBOARD_COMPLETE_RU = "✅ Профиль создан! Всё готово.\n\nНажмите 🧾 Создать счёт, чтобы начать."

ASK_CLIENT_RU = "👤 Кому выставляется счёт? (Введите имя клиента)"
ASK_CLIENT_DETAILS_CHOICE_RU = "Хотите добавить данные клиента (телефон, адрес и т.д.)?"
BTN_ADD_CLIENT_DETAILS_RU = "✅ Да"
BTN_SKIP_CLIENT_DETAILS_RU = "⏭️ Нет"
ASK_CLIENT_PHONE_RU = "📞 Телефон клиента?\n_Необязательно — нажмите Пропустить._"
ASK_CLIENT_ADDRESS_RU = "📍 Адрес клиента?\n_Необязательно — нажмите Пропустить._"
ASK_CLIENT_BANK_RU = "🏦 Счёт / IBAN клиента?\n_Необязательно — нажмите Пропустить._"
ASK_CLIENT_VAT_RU = "🏛️ НДС клиента?\n_Необязательно — нажмите Пропустить._"
ASK_DATE_RU = "📅 Укажите дату счёта."
CALENDAR_PROMPT_RU = "📅 Выберите дату:"
ASK_ITEM_NAME_RU = "📦 Какой товар или услугу вы выставляете?"
ASK_ITEM_PRICE_RU = "💶 Какова цена за *{item_name}*? (напр. 150 или 49.99)"
ASK_CURRENCY_RU = "💱 В какой валюте выставить счёт?"
ASK_CURRENCY_BASE_RU = "💱 Выберите валюту по умолчанию.\nВы сможете изменить её для каждого счёта."
ASK_CURRENCY_CUSTOM_RU = "✏️ Введите код валюты (напр. CHF, SEK, NOK):"
WHATS_NEXT_PROMPT_RU = "Что сделаем дальше?"
CURRENT_INVOICE_HEADER_RU = "📋 *Текущий счёт:*"
TOTAL_LABEL_RU = "💰 Итого:"
ITEM_ADDED_PREFIX_RU = "✅ Добавлено: "
GENERATING_PDF_RU = "⏳ Генерируем счёт…"
INVOICE_DONE_RU = "✅ Счёт #{number} готов!"
STORAGE_HINT_RU = "💾 Сохраните PDF — он не хранится на сервере."
BTN_SAVE_CLIENT_RU = "💾 Сохранить клиента"
BTN_SKIP_SAVE_RU = "Пропустить"
CLIENT_SAVED_RU = "✅ Клиент сохранён."
CLIENT_SAVED_INLINE_RU = "✅ Клиент сохранён"
SAVED_CLIENTS_HINT_RU = "Или выберите сохранённого клиента:"
BTN_CHANGE_CURRENCY_RU = "💶 Сменить валюту"
BTN_TODAY_RU = "📅 Сегодня"
BTN_YESTERDAY_RU = "📅 Вчера"
BTN_PICK_DATE_RU = "🗓 Выбрать дату"
BTN_ADD_ANOTHER_RU = "➕ Добавить ещё"
BTN_ADD_ITEM_RU = "➕ Добавить ещё"
BTN_REMOVE_LAST_RU = "❌ Удалить последнее"
BTN_DONE_RU = "✅ Создать счёт"
BTN_CREATE_INVOICE_CONFIRM_RU = "✅ Создать счёт"
BTN_DUE_DATE_RU = "📅 Установить срок оплаты"
BTN_DUE_NET30_RU = "30 дней"
BTN_DUE_NET15_RU = "15 дней"
BTN_DUE_ON_RECEIPT_RU = "По получении"
BTN_DUE_CUSTOM_RU = "📅 Выбрать дату"
BTN_NO_DUE_DATE_RU = "⏭️ Без срока"
ASK_DUE_DATE_RU = "📅 Когда нужно оплатить счёт?"
ASK_DUE_DATE_CUSTOM_RU = "✏️ Введите дату оплаты (в том же формате):"
DUE_DATE_SET_RU = "✅ Срок оплаты: {due_date}"
DUE_DATE_LABEL_RU = "Срок оплаты:"
BTN_NO_NAME_RU = "👤 Без имени"
BTN_CREATE_ANOTHER_RU = "🧾 Создать ещё"
BTN_ALL_DONE_RU = "✅ Готово"
BTN_CURRENCY_EUR_RU = "💶 EUR"
BTN_CURRENCY_USD_RU = "💵 USD"
BTN_CURRENCY_RUB_RU = "₽ RUB"
BTN_CURRENCY_KZT_RU = "₸ KZT"
BTN_CURRENCY_OTHER_RU = "✏️ Другая"
BTN_CURRENCY_CUSTOM_RU = "✏️ Другая"
INVOICE_CANCELLED_RU = "❌ Счёт отменён."
CURRENCY_SET_RU = "✅ Валюта изменена на *{currency}*."

PROFILE_HEADER_RU = "📋 *Ваш профиль:*"
ORGANIZATION_LABEL_RU = "🏢 Организация:"
PHONE_LABEL_RU = "📞 Телефон:"
EMAIL_LABEL_RU = "✉️ Email:"
VAT_LABEL_RU = "🏛️ НДС:"
ACCOUNT_LABEL_RU = "🏦 Счёт:"
REFERENCES_LABEL_RU = "🔢 Нумерация:"
CURRENCY_LABEL_RU = "💱 Валюта:"
EDIT_PROMPT_RU = "Какое поле хотите изменить?"
EDIT_CANCELLED_RU = "✏️ Редактирование отменено."
FIELD_UPDATED_RU = "✅ {field} обновлено."
EMAIL_CLEARED_RU = "✅ Email удалён."
VAT_CLEARED_RU = "✅ Номер НДС удалён."
BTN_EDIT_ORG_RU = "🏢 Организация"
BTN_EDIT_PHONE_RU = "📞 Телефон"
BTN_EDIT_EMAIL_RU = "✉️ Email"
BTN_EDIT_VAT_RU = "🏛️ НДС"
BTN_EDIT_ACCOUNT_RU = "🏦 Счёт"
BTN_EDIT_REFERENCES_RU = "🔢 Нумерация"

TRACK_INVOICES_HEADER_RU = "📋 *Ваши счета*"
TRACK_INVOICES_EMPTY_RU = "📭 У вас пока нет счетов.\n\nНажмите 🧾 Создать счёт, чтобы начать."
TRACK_INVOICES_ALL_PAID_RU = "🎉 Все счета отмечены как оплаченные!"
TRACK_MARK_PAID_PROMPT_RU = "Выберите счёт, чтобы отметить как оплаченный:"
BTN_TRACK_MARK_PAID_RU = "✅ Отметить как оплаченный"
BTN_TRACK_BACK_RU = "⬅️ Назад"
INVOICE_MARKED_PAID_RU = "✅ Отмечено как оплаченное."
INVOICE_STATUS_PAID_RU = "✅ Оплачено"
INVOICE_STATUS_UNPAID_RU = "⏳ Не оплачено"

HELP_TEXT_RU = (
    "📋 *Справка по Invoice Bot*\n\n"
    "*🚀 Начало работы*\n"
    "Отправьте /start в любой момент, чтобы открыть главное меню. Настройте "
    "профиль один раз — и все документы будут заполняться автоматически.\n\n"
    "*📝 Сметы*\n"
    "Нажмите 📝 Создать смету, чтобы отправить клиенту предложение с ценой до "
    "начала работы. В разделе 📁 Мои сметы можно отправить смету, изменить её "
    "или превратить принятую смету в счёт — позиции, суммы и валюта "
    "переносятся автоматически.\n\n"
    "*🧾 Счета*\n"
    "Нажмите 🧾 Создать счёт и следуйте подсказкам: выберите клиента, добавьте "
    "позиции, при необходимости укажите срок оплаты и ставку НДС, затем "
    "получите готовый PDF.\n\n"
    "*🧾 Квитанции*\n"
    "Нажмите 🧾 Создать квитанцию для отдельной квитанции или отметьте счёт "
    "оплаченным в разделе 📋 Счета, чтобы создать её автоматически.\n\n"
    "*✏️ Профиль*\n"
    "Нажмите ✏️ Редактировать профиль, чтобы изменить название, телефон, "
    "email, номер НДС, банковские реквизиты, формат нумерации и ставку НДС по "
    "умолчанию.\n\n"
    "*💡 Подсказки*\n"
    "• Сохраните клиента один раз и используйте повторно.\n"
    "• Добавляйте несколько позиций в один счёт или смету.\n"
    "• Отправьте /cancel, чтобы прервать текущий процесс.\n"
    "• Валюты: EUR, USD, RUB, KZT и любой код из 2–4 букв."
)

BTN_HELP_BACK_TO_MENU_RU = "🏠 В меню"

ERR_NOT_TEXT_RU = "Пожалуйста, отправьте текстовое сообщение."
ERR_EMPTY_RU = "Поле не может быть пустым. Попробуйте ещё раз."
ERR_SHORT_TEXT_RU = "Слишком коротко. Введите не менее 2 символов."
ERR_LONG_TEXT_RU = "Слишком длинно (макс. {n} символов)."
ERR_INVALID_PHONE_RU = "Введите корректный номер телефона (3–30 символов)."
ERR_INVALID_EMAIL_RU = "Введите корректный email (напр. name@example.com) или нажмите Пропустить."
ERR_INVALID_VAT_RU = "Введите корректный номер НДС (3–20 символов) или нажмите Пропустить."
ERR_INVALID_ACCOUNT_RU = "Введите корректный номер счёта или IBAN (5–40 символов)."
ERR_WRONG_BUTTON_RU = "Пожалуйста, используйте одну из кнопок ниже."
ERR_INVALID_PRICE_RU = "Введите корректное число (напр. 150 или 49.99)."
ERR_ZERO_NEGATIVE_PRICE_RU = "Цена должна быть больше нуля."
ERR_INVALID_CURRENCY_RU = "Введите код валюты из 2–4 букв (напр. CHF)."
ERR_PDF_FAILURE_RU = "❌ Ошибка при создании счёта. Попробуйте ещё раз."
ERR_NO_PROFILE_RU = "❌ Профиль не найден. Введите /start, чтобы создать аккаунт."
ERR_NO_ITEMS_RU = "❌ Нечего удалять."
ERR_PRICE_ZERO_RU = "❌ Цена должна быть больше нуля."
ERR_PRICE_INVALID_RU = "❌ Введите корректное число (напр. 150 или 49.99)."
ERR_CURRENCY_INVALID_RU = "❌ Введите корректный код валюты из 2–4 букв."

MID_FLOW_RESTART_PROMPT_RU = "🔁 Найден незавершённый счёт.\n\nПродолжить или начать заново?"
PROMPT_START_RU = "👋 Привет! Введите /start, чтобы создать аккаунт."
NO_CLIENT_LABEL_RU = "Без клиента"
REF_LABEL_RU = "Номер:"
DATE_LABEL_RU = "Дата:"
DUE_LABEL_RU = "Срок:"
INVOICE_LIST_HEADER_RU = "📋 *Ваши счета*"
NO_INVOICES_YET_RU = "Счетов пока нет."
ALL_INVOICES_PAID_RU = "🎉 Все счета отмечены как оплаченные!"
SELECT_INVOICE_TO_MARK_RU = "Выберите счёт, чтобы отметить как оплаченный:"
BTN_MARK_AS_PAID_RU = "✅ Отметить как оплаченный"
BTN_BACK_TO_MENU_RU = "← В меню"
NO_ITEMS_YET_RU = "_Позиции ещё не добавлены._"
ITEM_ADDED_PROMPT_RU = "Что сделаем дальше?"
ITEM_REMOVED_RU = "❌ Удалено: {name}"
AFTER_PDF_PROMPT_RU = "Что сделаем дальше?"
PDF_READY_RU = "🧾 Счёт #{number} готов! Сохраните — он не хранится на сервере."
NOT_SET_RU = "_не указано_"
MAIN_MENU_PROMPT_RU = "🏠 Главное меню. Что сделаем?"
CANCELLED_RU = "❌ Отменено."
UNKNOWN_MSG_RU = "👋 Нажмите кнопку ниже или введите /start."
NO_HISTORY_RU = "📭 Счетов пока нет."
HISTORY_HEADER_RU = "📋 *Последние счета:*"
HISTORY_ROW_RU = "INV-{number:05d} — {client} — {amount} — {date}"

# =============================================================================
# === QUOTES (Goal 1) =========================================================
# =============================================================================

# --- Main-menu buttons ---
BTN_CREATE_QUOTE = "\U0001f4dd Create quote"
BTN_MY_QUOTES = "\U0001f4c1 My quotes"

# --- Quote creation flow (mirrors the invoice flow) ---
QUOTE_ASK_CLIENT = "\U0001f464 Who is this quote for? (Enter client name)"
QUOTE_ASK_DATE = "\U0001f4c5 What is the quote date?"
QUOTE_ASK_ITEM_NAME = "\U0001f4e6 What item or service are you quoting for?"
QUOTE_ASK_ITEM_PRICE = "\U0001f4b6 What is the price for *{item_name}*? (e.g. 150 or 49.99)"
QUOTE_CURRENT_HEADER = "\U0001f4dd *Current quote:*"
QUOTE_GENERATING = "\u23f3 Generating your quote\u2026"
QUOTE_DONE = "\u2705 Quote Q-{number} is ready!"
QUOTE_STORAGE_HINT = "\U0001f4be Save this PDF \u2014 it won't be stored on the server."
QUOTE_CANCELLED = "\u274c Quote cancelled."

# Valid-until step
QUOTE_ASK_VALID_UNTIL = "\U0001f4c5 How long is this quote valid?"
QUOTE_ASK_VALID_UNTIL_CUSTOM = "\u270f\ufe0f Enter the valid-until date (same format as the quote date):"
QUOTE_VALID_UNTIL_SET = "\u2705 Valid until: {date}"
BTN_QUOTE_VALID_14 = "14 Days"
BTN_QUOTE_VALID_30 = "30 Days"
BTN_QUOTE_VALID_60 = "60 Days"
BTN_QUOTE_VALID_CUSTOM = "\U0001f4c5 Pick a date"
BTN_QUOTE_NO_VALID = "\u23ed\ufe0f No expiry"

# After-items buttons (quote)
BTN_QUOTE_SET_VALID = "\U0001f4c5 Valid until"
BTN_CREATE_QUOTE_CONFIRM = "\u2705 Create quote"

# Per-quote VAT (reuses the invoice VAT prompt/labels where possible)
QUOTE_ASK_VAT_RATE = (
"\U0001f4ca VAT rate for this quote?\n"
"Enter a number \u2014 e.g. 21 for 21%, or 0 for none."
)
QUOTE_VAT_SET = "\u2705 VAT rate set to {rate}% for this quote."

# --- My-quotes list + per-quote view ---
QUOTE_LIST_HEADER = "\U0001f4c1 *Your quotes*"
QUOTE_LIST_EMPTY = (
"\U0001f4ed You haven't created any quotes yet.\n\n"
"Tap \U0001f4dd Create quote to make your first one."
)
QUOTE_SELECT_PROMPT = "Tap a quote to view it:"
QUOTE_VIEW_HEADER = "\U0001f4dd *Quote Q-{number}*"
QUOTE_STATUS_LABEL = "Status:"
QUOTE_VALID_LABEL = "Valid until:"

# Quote statuses (display)
QUOTE_STATUS_PENDING = "Pending"
QUOTE_STATUS_ACCEPTED = "Accepted"
QUOTE_STATUS_CONVERTED = "Converted"

# --- Per-quote action buttons (inline) ---
BTN_QUOTE_SEND = "\U0001f4e4 Send to client"
BTN_QUOTE_CONVERT = "\U0001f9fe Convert to invoice"
BTN_QUOTE_MARK_ACCEPTED = "\u2705 Mark accepted"
BTN_QUOTE_EDIT = "\u270f\ufe0f Edit"
BTN_QUOTE_DELETE = "\U0001f5d1\ufe0f Delete"
BTN_QUOTE_BACK = "\u2b05\ufe0f Back to quotes"

# --- Conversion + status messages ---
QUOTE_SENT = "\u2705 Quote Q-{number} sent."
QUOTE_RESENDING = "\u23f3 Re-generating quote Q-{number}\u2026"
QUOTE_MARKED_ACCEPTED = "\u2705 Quote Q-{number} marked as accepted."
QUOTE_CONVERTING = "\u23f3 Converting quote Q-{number} to an invoice\u2026"
QUOTE_CONVERTED_MSG = (
"\u2705 Quote Q-{qnumber} converted.\n"
"Review the invoice below and tap \u2705 Create invoice to send it."
)
QUOTE_ALREADY_CONVERTED = (
"\u26a0\ufe0f Quote Q-{number} was already converted to an invoice "
"and can't be converted again."
)
QUOTE_DELETED = "\U0001f5d1\ufe0f Quote Q-{number} deleted."
QUOTE_NOT_FOUND = "\u274c That quote could not be found."

# Errors
ERR_QUOTE_PDF_FAILURE = "\u274c Something went wrong generating your quote. Please try again."

# =============================================================================
# === RECEIPTS (Feature 1 / 2 / 3) ============================================
# =============================================================================

# --- Main-menu button ---
BTN_CREATE_RECEIPT = "\U0001f9fe Create receipt"   # 🧾

# --- Standalone receipt flow: Bill-to ---
RCP_ASK_BILL_TO = "\U0001f464 Who is this receipt for? Pick a saved client or type a name."
RCP_ASK_CLIENT_ADDRESS = (
    "\U0001f4cd Client's address?\n_Optional — tap Skip if you don't have one._"
)
RCP_ASK_CLIENT_EMAIL = (
    "\u2709\ufe0f Client's email?\n_Optional — tap Skip if you don't have one._"
)

# --- Linked invoice + dates ---
RCP_ASK_INVOICE_REF = (
    "\U0001f517 Link an invoice number? Send it (e.g. 42) or tap Skip."
)
RCP_ASK_DATE_PAID = "\U0001f4c5 What date was this paid?"

# --- Line items ---
RCP_ASK_ITEM_DESC = "\U0001f4e6 Item / service description?"
RCP_ASK_ITEM_QTY = "\U0001f522 Quantity for *{desc}*? (e.g. 1, 2.5)"
RCP_ASK_ITEM_PRICE = "\U0001f4b6 Unit price for *{desc}*? (e.g. 150 or 49.99)"
RCP_ASK_ITEM_VAT = "\U0001f3db\ufe0f VAT %% for *{desc}*? (e.g. 21, or 0 for none)"
RCP_ITEM_ADDED = "\u2705 Added: {desc}"

# --- Amount paid + payment ---
RCP_ASK_AMOUNT_PAID = (
    "\U0001f4b0 Amount paid? Send a number, or tap \u201cFull total\u201d to use {total}."
)
RCP_ASK_PAYMENT_METHOD = "\U0001f4b3 How was this paid?"
RCP_ASK_PAYMENT_OTHER = "\u270f\ufe0f Type the payment method:"
RCP_ASK_PAYMENT_DATE = "\U0001f4c5 Payment date?"

# --- Summary / done ---
RCP_CURRENT_HEADER = "\U0001f9fe *Current receipt:*"
RCP_GENERATING = "\u23f3 Generating your receipt\u2026"
RCP_DONE = "\u2705 Receipt {number} is ready!"
RCP_STORAGE_HINT = "\U0001f4be Save this PDF \u2014 it won't be stored on the server."
RCP_CANCELLED = "\u274c Receipt cancelled."
RCP_NO_ITEMS = "Please add at least one line item first."

# --- Receipt-flow buttons ---
BTN_RCP_ADD_ANOTHER = "\u2795 Add another item"
BTN_RCP_DONE_ITEMS = "\u2705 Done adding items"
BTN_RCP_FULL_TOTAL = "\U0001f4b0 Full total"
BTN_RCP_SKIP = "\u23ed\ufe0f Skip"

# --- Payment-method labels (shared by Feature 1 + Feature 2 inline keyboard) ---
PM_BANK_TRANSFER = "\U0001f3e6 Bank Transfer"
PM_CREDIT_CARD = "\U0001f4b3 Credit Card"
PM_CASH = "\U0001f4b5 Cash"
PM_PAYPAL = "\U0001f17f\ufe0f PayPal"
PM_STRIPE = "\U0001f4a0 Stripe"
PM_OTHER = "\u270f\ufe0f Other"

# --- Feature 2: auto-receipt on mark-as-paid ---
TRACK_ASK_PAYMENT_METHOD = "How was this invoice paid?"
TRACK_RECEIPT_GENERATING = "\u23f3 Generating receipt\u2026"
TRACK_RECEIPT_SENT = "\u2705 Receipt {number} generated for invoice #{invoice}."
TRACK_RECEIPT_FAILED = (
    "\u2705 Invoice marked paid, but the receipt PDF could not be generated."
)

# --- Feature 3: paid-invoice view ---
BTN_VIEW_PAID = "\U0001f4c1 View paid invoices"
TRACK_PAID_HEADER = "\U0001f4c1 *Paid invoices*"
TRACK_NO_PAID = "No paid invoices yet."
BTN_TRACK_BACK_TO_OPEN = "\u2b05\ufe0f Back to open invoices"

# Errors specific to receipts
ERR_RCP_INVALID_QTY = "Please enter a valid quantity (e.g. 1 or 2.5)."
ERR_RCP_INVALID_VAT = "Please enter a VAT percentage 0–100 (e.g. 21)."
ERR_RCP_PDF_FAILURE = "\u274c Something went wrong generating your receipt. Please try again."

# =============================================================================
# === QUOTES — RUSSIAN (Goal 1) ===============================================
# =============================================================================

BTN_CREATE_QUOTE_RU = "📝 Создать смету"
BTN_MY_QUOTES_RU = "📁 Мои сметы"

QUOTE_ASK_CLIENT_RU = "👤 Для кого эта смета? (Введите имя клиента)"
QUOTE_ASK_DATE_RU = "📅 Укажите дату сметы."
QUOTE_ASK_ITEM_NAME_RU = "📦 Какой товар или услугу включить в смету?"
QUOTE_ASK_ITEM_PRICE_RU = "💶 Цена за *{item_name}*? (напр. 150 или 49.99)"
QUOTE_CURRENT_HEADER_RU = "📝 *Текущая смета:*"
QUOTE_GENERATING_RU = "⏳ Генерируем смету…"
QUOTE_DONE_RU = "✅ Смета Q-{number} готова!"
QUOTE_STORAGE_HINT_RU = "💾 Сохраните PDF — он не хранится на сервере."
QUOTE_CANCELLED_RU = "❌ Создание сметы отменено."

QUOTE_ASK_VALID_UNTIL_RU = "📅 Сколько действует эта смета?"
QUOTE_ASK_VALID_UNTIL_CUSTOM_RU = "✏️ Введите дату действия (в том же формате):"
QUOTE_VALID_UNTIL_SET_RU = "✅ Действует до: {date}"
BTN_QUOTE_VALID_14_RU = "14 дней"
BTN_QUOTE_VALID_30_RU = "30 дней"
BTN_QUOTE_VALID_60_RU = "60 дней"
BTN_QUOTE_VALID_CUSTOM_RU = "📅 Выбрать дату"
BTN_QUOTE_NO_VALID_RU = "⏭️ Без срока"

BTN_QUOTE_SET_VALID_RU = "📅 Срок действия"
BTN_CREATE_QUOTE_CONFIRM_RU = "✅ Создать смету"

QUOTE_ASK_VAT_RATE_RU = "📊 Ставка НДС для этой сметы?\nВведите число — напр. 21 для 21%, или 0."
QUOTE_VAT_SET_RU = "✅ Ставка НДС {rate}% для этой сметы."

QUOTE_LIST_HEADER_RU = "📁 *Ваши сметы*"
QUOTE_LIST_EMPTY_RU = "📭 У вас пока нет смет.\n\nНажмите 📝 Создать смету, чтобы начать."
QUOTE_SELECT_PROMPT_RU = "Нажмите на смету, чтобы открыть:"
QUOTE_VIEW_HEADER_RU = "📝 *Смета Q-{number}*"
QUOTE_STATUS_LABEL_RU = "Статус:"
QUOTE_VALID_LABEL_RU = "Действует до:"

QUOTE_STATUS_PENDING_RU = "Ожидает"
QUOTE_STATUS_ACCEPTED_RU = "Принята"
QUOTE_STATUS_CONVERTED_RU = "Преобразована"

BTN_QUOTE_SEND_RU = "📤 Отправить клиенту"
BTN_QUOTE_CONVERT_RU = "🧾 Преобразовать в счёт"
BTN_QUOTE_MARK_ACCEPTED_RU = "✅ Отметить принятой"
BTN_QUOTE_EDIT_RU = "✏️ Изменить"
BTN_QUOTE_DELETE_RU = "🗑️ Удалить"
BTN_QUOTE_BACK_RU = "⬅️ К сметам"

QUOTE_SENT_RU = "✅ Смета Q-{number} отправлена."
QUOTE_RESENDING_RU = "⏳ Повторная генерация сметы Q-{number}…"
QUOTE_MARKED_ACCEPTED_RU = "✅ Смета Q-{number} отмечена как принятая."
QUOTE_CONVERTING_RU = "⏳ Преобразуем смету Q-{number} в счёт…"
QUOTE_CONVERTED_MSG_RU = (
"✅ Смета Q-{qnumber} преобразована.\n"
"Проверьте счёт ниже и нажмите ✅ Создать счёт, чтобы отправить его."
)
QUOTE_ALREADY_CONVERTED_RU = (
"⚠️ Смета Q-{number} уже была преобразована в счёт и не может быть преобразована повторно."
)
QUOTE_DELETED_RU = "🗑️ Смета Q-{number} удалена."
QUOTE_NOT_FOUND_RU = "❌ Смета не найдена."

ERR_QUOTE_PDF_FAILURE_RU = "❌ Ошибка при создании сметы. Попробуйте ещё раз."
