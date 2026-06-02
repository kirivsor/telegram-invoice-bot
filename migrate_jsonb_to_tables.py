"""One-time backfill: legacy JSONB blobs -> normalized tables.

Run ONCE after applying schema.sql, on the live Railway DB:

    python migrate_jsonb_to_tables.py

It reads users.saved_clients / users.invoices / users.quotes and
inserts equivalent rows into saved_clients / invoices(+items) /
quotes(+items). It is **idempotent**: every insert uses
ON CONFLICT DO NOTHING on the natural key, so re-running is safe and
won't duplicate data.

It does NOT delete the JSONB columns — verify the row counts first,
then drop them in a follow-up migration once you're confident.
"""

from __future__ import annotations

import logging

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


def _iso_or_none(value):
    return value if isinstance(value, str) and value else None


def backfill() -> None:
    db.init_pool()

    legacy_users = db.fetch_all(
        "SELECT user_id, saved_clients, invoices, quotes FROM users"
    )
    logger.info("Backfilling %d users", len(legacy_users))

    clients_n = invoices_n = quotes_n = 0

    for u in legacy_users:
        uid = int(u["user_id"])

        # --- saved_clients ---
        for entry in (u.get("saved_clients") or []):
            if isinstance(entry, str):
                name = entry.strip()
                rec = {"name": name} if name else None
            elif isinstance(entry, dict) and str(entry.get("name", "")).strip():
                rec = entry
            else:
                rec = None
            if not rec:
                continue
            db.upsert_saved_client(
                uid, str(rec["name"]).strip(),
                phone=rec.get("phone"), address=rec.get("address"),
                bank=rec.get("bank"), vat=rec.get("vat"),
            )
            clients_n += 1

        # --- invoices ---
        for inv in (u.get("invoices") or []):
            try:
                number = int(inv.get("number"))
            except (TypeError, ValueError):
                logger.warning("Skipping invoice without numeric number for user %s", uid)
                continue
            record = {
                "number": number,
                "client_name": inv.get("client_name"),
                "amount": inv.get("amount") or 0,
                "currency": inv.get("currency") or "EUR",
                "invoice_date": inv.get("invoice_date"),
                "due_date": inv.get("due_date"),
                "sent_at": _iso_or_none(inv.get("sent_at")),
                "paid": bool(inv.get("paid")),
                "reference": inv.get("reference"),
                "tax_rate": inv.get("tax_rate"),
                "client_details": inv.get("client_details"),
                "converted_from_quote": inv.get("converted_from_quote"),
                "payment_method": inv.get("payment_method"),
                "payment_date": inv.get("payment_date"),
                "items": inv.get("items") or [],
            }
            db.insert_invoice(uid, record)
            invoices_n += 1

        # --- quotes ---
        for q in (u.get("quotes") or []):
            try:
                number = int(q.get("number"))
            except (TypeError, ValueError):
                logger.warning("Skipping quote without numeric number for user %s", uid)
                continue
            record = {
                "number": number,
                "client_name": q.get("client_name"),
                "amount": q.get("amount") or 0,
                "currency": q.get("currency") or "EUR",
                "date": q.get("date") or q.get("quote_date"),
                "valid_until": q.get("valid_until"),
                "created_at": q.get("created_at"),
                "status": q.get("status") or "Pending",
                "vat_rate": q.get("vat_rate") if q.get("vat_rate") is not None else q.get("tax_rate"),
                "client_details": q.get("client_details"),
                "converted_invoice_number": q.get("converted_invoice_number"),
                "items": q.get("items") or [],
            }
            db.insert_quote(uid, record)
            quotes_n += 1

    logger.info(
        "Backfill complete: %d clients, %d invoices, %d quotes",
        clients_n, invoices_n, quotes_n,
    )


if __name__ == "__main__":
    backfill()
