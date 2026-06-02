-- =====================================================================
-- Telegram Invoice Bot — Stage 1 schema
-- Source of truth: PostgreSQL on Railway (DATABASE_URL).
--
-- This file is idempotent: safe to run on every deploy.
-- It promotes the legacy JSONB blobs (users.invoices / users.quotes /
-- users.saved_clients) into normalized tables with stable IDs, real
-- statuses, and audit columns — the precondition for reconciliation
-- and 1C export later.
--
-- Run once to initialize (or on every deploy; all statements are
-- CREATE ... IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).
-- The one-time data backfill lives in migrate_jsonb_to_tables.py.
-- =====================================================================

-- Needed for gen_random_uuid(). Available on Railway's Postgres.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------
-- updated_at trigger helper (one function, reused by every table)
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------
-- users
-- Telegram user == one business profile. user_id is the Telegram id.
-- We keep the counters here (atomic UPDATE ... RETURNING already works).
-- The JSONB columns (saved_clients/invoices/quotes) are intentionally
-- LEFT IN PLACE so the backfill can read them; new code never writes
-- them. Drop them in a later migration once backfill is verified.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id              BIGINT PRIMARY KEY,
    org_name             TEXT,
    phone                TEXT,
    email                TEXT        DEFAULT '',
    vat_number           TEXT        DEFAULT '',
    iban                 TEXT,
    reference_style      TEXT        DEFAULT 'Standard',
    last_invoice_number  INT         DEFAULT 0,
    last_quote_number    INT         DEFAULT 0,
    last_receipt_number  INT         DEFAULT 0,
    currency             TEXT        DEFAULT 'EUR',
    language             TEXT        DEFAULT 'en',
    default_vat_rate     NUMERIC(5,2) DEFAULT 0.0,
    -- legacy blobs (read-only after backfill; do not write going forward)
    saved_clients        JSONB       DEFAULT '[]',
    invoices             JSONB       DEFAULT '[]',
    quotes               JSONB       DEFAULT '[]',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Older deploys created users WITHOUT created_at/updated_at. Add them.
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- saved_clients
-- Was: users.saved_clients JSONB (capped at 3). Now a real table.
-- A client is scoped to the user who saved it.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_clients (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    name        TEXT   NOT NULL,
    phone       TEXT,
    address     TEXT,
    bank        TEXT,
    vat         TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One client name per user (case-insensitive), matching old no-dup rule.
CREATE UNIQUE INDEX IF NOT EXISTS uq_saved_clients_user_name
    ON saved_clients (user_id, lower(name));
CREATE INDEX IF NOT EXISTS ix_saved_clients_user
    ON saved_clients (user_id, created_at);

DROP TRIGGER IF EXISTS trg_saved_clients_updated_at ON saved_clients;
CREATE TRIGGER trg_saved_clients_updated_at
    BEFORE UPDATE ON saved_clients
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- invoices
-- Was: an element inside users.invoices JSONB array. Now one row each.
-- `number` is the per-user invoice number (INV-#####). It is unique
-- PER USER, not globally. `status` replaces the old boolean `paid`
-- (explicit status > hidden boolean, per accountant-safety principle).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoices (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                  BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    number                   INT    NOT NULL,
    client_name              TEXT,
    amount                   NUMERIC(14,2) NOT NULL DEFAULT 0,
    currency                 TEXT   NOT NULL DEFAULT 'EUR',
    invoice_date             TEXT,           -- kept as display string ("dd.mm.yyyy") to preserve behavior
    due_date                 TEXT,
    sent_at                  TIMESTAMPTZ,    -- when the invoice was generated/sent
    status                   TEXT   NOT NULL DEFAULT 'unpaid',  -- 'unpaid' | 'paid'
    reference                TEXT,
    tax_rate                 NUMERIC(5,2),   -- percentage; NULL == no VAT
    client_details           JSONB,          -- {"phone","address","bank","vat"} snapshot at send time
    payment_method           TEXT,
    payment_date             TEXT,
    -- link back to the quote this invoice was converted from (nullable)
    source_quote_number      INT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, number)
);

CREATE INDEX IF NOT EXISTS ix_invoices_user        ON invoices (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_invoices_user_status ON invoices (user_id, status);

DROP TRIGGER IF EXISTS trg_invoices_updated_at ON invoices;
CREATE TRIGGER trg_invoices_updated_at
    BEFORE UPDATE ON invoices
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- invoice_items
-- Was: invoice["items"] = [{"name","price"}, ...] nested in JSONB.
-- Now normalized: one row per line item, FK to its invoice.
-- position preserves the original ordering.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS invoice_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id  UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    position    INT  NOT NULL DEFAULT 0,
    name        TEXT NOT NULL,
    price       NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_invoice_items_invoice
    ON invoice_items (invoice_id, position);

-- ---------------------------------------------------------------------
-- quotes
-- Was: an element inside users.quotes JSONB array.
-- `status` is the canonical Pending | Accepted | Converted.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quotes (
    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    number                     INT    NOT NULL,
    client_name                TEXT,
    amount                     NUMERIC(14,2) NOT NULL DEFAULT 0,
    currency                   TEXT   NOT NULL DEFAULT 'EUR',
    quote_date                 TEXT,
    valid_until                TEXT,
    created_at_label           TEXT,          -- preserves any pre-formatted "created_at" string the handler stored
    status                     TEXT   NOT NULL DEFAULT 'Pending',
    tax_rate                   NUMERIC(5,2),
    client_details             JSONB,
    converted_invoice_number   INT,           -- set when status -> Converted
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, number)
);

CREATE INDEX IF NOT EXISTS ix_quotes_user        ON quotes (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_quotes_user_status ON quotes (user_id, status);

DROP TRIGGER IF EXISTS trg_quotes_updated_at ON quotes;
CREATE TRIGGER trg_quotes_updated_at
    BEFORE UPDATE ON quotes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------
-- quote_items
-- Was: quote["items"] nested in JSONB.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS quote_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    quote_id    UUID NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    position    INT  NOT NULL DEFAULT 0,
    name        TEXT NOT NULL,
    price       NUMERIC(14,2) NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_quote_items_quote
    ON quote_items (quote_id, position);
