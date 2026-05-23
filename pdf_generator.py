"""PDF invoice generator for the Telegram Invoice Bot.

This module handles all ReportLab PDF generation. Nothing else.
PDFs are saved to the invoices/ subfolder (auto-created if missing).

Public entry point:
    generate_invoice_pdf(...) -> Path

Callers (handlers.py) supply the invoice number, date, client name,
items, and the user's profile dict (as produced by
profile_manager.get_profile()). This module does NOT touch
profiles.json; all profile reads/writes live in profile_manager.

Fonts: only ReportLab's built-in fonts (Helvetica, Helvetica-Bold,
Courier) are used so the bot runs on Replit without installing
anything extra. The Euro sign (€, U+20AC) is part of WinAnsi
encoding and renders correctly in the built-in fonts.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

logger = logging.getLogger(__name__)

# ─── Output location ────────────────────────────────────────────────────────
INVOICES_DIR = Path("invoices")

# ─── Page geometry (A4 portrait, 20mm margins) ──────────────────────────────
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - 2 * MARGIN
CONTENT_RIGHT = MARGIN + CONTENT_WIDTH   # x-coordinate of the right edge

# ─── Items-table column widths (10% / 65% / 25%) ────────────────────────────
COL_NUM_W = CONTENT_WIDTH * 0.10
COL_DESC_W = CONTENT_WIDTH * 0.65
COL_AMOUNT_W = CONTENT_WIDTH * 0.25


# ─── Formatting helpers ─────────────────────────────────────────────────────

def _format_eur(amount: float) -> str:
    """Format a number as €X,XXX.XX (€ + comma thousands + 2 decimals)."""
    return f"€{amount:,.2f}"


def _ensure_invoices_dir() -> None:
    """Create invoices/ if it doesn't exist."""
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)


def _build_filename(invoice_date: date) -> str:
    """Filename: Invoice_YYYY-MM-DD_HHMM.pdf

    YYYY-MM-DD is the invoice date; HHMM is the generation time.
    """
    date_part = invoice_date.strftime("%Y-%m-%d")
    time_part = datetime.now().strftime("%H%M")
    return f"Invoice_{date_part}_{time_part}.pdf"


# ─── Drawing primitives ─────────────────────────────────────────────────────

def _draw_header(
    c: canvas.Canvas, invoice_number: int, invoice_date: date
) -> float:
    """Centered title + date. Returns the y-coordinate just below the date."""
    title_y = PAGE_HEIGHT - MARGIN - 18  # 18pt baseline below top margin
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(
        PAGE_WIDTH / 2, title_y, f"INVOICE #{invoice_number:05d}"
    )

    date_y = title_y - 20
    c.setFont("Helvetica", 12)
    c.drawCentredString(
        PAGE_WIDTH / 2, date_y, invoice_date.strftime("%d.%m.%Y")
    )

    return date_y - 28  # leave whitespace before the issuer/recipient blocks


def _draw_issuer(
    c: canvas.Canvas, profile: dict[str, Any], y_top: float
) -> float:
    """'From:' block, top-left. Returns the y-coordinate just below it."""
    x = MARGIN
    y = y_top

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, "From:")
    y -= 16

    c.setFont("Helvetica", 12)
    c.drawString(x, y, str(profile.get("org_name", "")))
    y -= 15

    c.setFont("Helvetica", 11)
    c.drawString(x, y, str(profile.get("phone", "")))
    y -= 14

    c.setFont("Courier", 11)
    c.drawString(x, y, str(profile.get("iban", "")))
    y -= 14

    return y


def _draw_recipient(
    c: canvas.Canvas, client_name: str | None, y_top: float
) -> float:
    """'To:' block, top-right. Returns the y-coordinate just below it."""
    x = CONTENT_RIGHT
    y = y_top

    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(x, y, "To:")
    y -= 16

    c.setFont("Helvetica", 12)
    display_name = client_name if client_name else "—"
    c.drawRightString(x, y, display_name)
    y -= 15

    return y


def _build_items_table(
    items: list[dict[str, Any]],
) -> tuple[Table, float]:
    """Build the items Table flowable and compute the total."""
    header = ["#", "Description", "Amount"]
    data: list[list[str]] = [header]
    total = 0.0

    for idx, item in enumerate(items, start=1):
        name = str(item.get("name", ""))
        price = float(item.get("price", 0))
        total += price
        data.append([str(idx), name, _format_eur(price)])

    table = Table(
        data,
        colWidths=[COL_NUM_W, COL_DESC_W, COL_AMOUNT_W],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                # Header row
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.black),
                # Body rows
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 11),
                # Thin separator between item rows (optional in spec)
                ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.lightgrey),
                # Alignment
                ("ALIGN", (0, 0), (0, -1), "CENTER"),   # # column
                ("ALIGN", (1, 0), (1, -1), "LEFT"),     # description
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),    # amount
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # Padding
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table, total


def _draw_total(c: canvas.Canvas, total: float, y_top: float) -> None:
    """Right-aligned 'TOTAL: €X.XX' line below the items table."""
    c.setFont("Helvetica-Bold", 13)
    label_x = CONTENT_RIGHT - COL_AMOUNT_W
    c.drawRightString(label_x - 6, y_top, "TOTAL:")
    c.drawRightString(CONTENT_RIGHT - 4, y_top, _format_eur(total))


def _draw_footer(c: canvas.Canvas) -> None:
    """Centered footer at the very bottom of the page."""
    c.setFont("Helvetica", 9)
    c.drawCentredString(
        PAGE_WIDTH / 2, MARGIN, "Thank you for your business!"
    )


# ─── Public entry point ─────────────────────────────────────────────────────

def generate_invoice_pdf(
    *,
    invoice_number: int,
    invoice_date: date,
    client_name: str | None,
    items: list[dict[str, Any]],
    profile: dict[str, Any],
) -> Path:
    """Generate the invoice PDF and return its absolute file path.

    Args:
        invoice_number: Sequential invoice number; rendered zero-padded
            to 5 digits (e.g. 7 -> "INVOICE #00007").
        invoice_date: Date printed on the invoice (DD.MM.YYYY). Also
            used in the filename.
        client_name: Recipient's name; pass None (or "") to render "-".
        items: List of {"name": str, "price": int | float} dicts in
            the order the user added them.
        profile: User's profile dict as returned by
            profile_manager.get_profile(). Must contain "org_name",
            "phone", and "iban".

    Returns:
        Path to the generated PDF inside the invoices/ directory.

    Raises:
        OSError: if the invoices/ directory cannot be created or the
            PDF cannot be written. Callers should catch this and show
            ERR_PDF_FAILURE to the user.
    """
    _ensure_invoices_dir()

    out_path = INVOICES_DIR / _build_filename(invoice_date)

    c = canvas.Canvas(str(out_path), pagesize=A4)

    # Header
    y_after_header = _draw_header(c, invoice_number, invoice_date)

    # Issuer and recipient share the same top y so they read side-by-side
    y_issuer_bottom = _draw_issuer(c, profile, y_after_header)
    y_recipient_bottom = _draw_recipient(c, client_name, y_after_header)
    y_blocks_bottom = min(y_issuer_bottom, y_recipient_bottom)

    # Items table, placed below whichever side ended lower
    table, total = _build_items_table(items)
    available_height = y_blocks_bottom - MARGIN - 60  # leave room for total + footer
    _, table_height = table.wrap(CONTENT_WIDTH, available_height)
    table_y = (y_blocks_bottom - 24) - table_height
    table.drawOn(c, MARGIN, table_y)

    # Total directly under the table, right-aligned
    _draw_total(c, total, table_y - 20)

    # Footer
    _draw_footer(c)

    c.showPage()
    c.save()

    logger.info(
        "Wrote invoice PDF #%05d for org=%r to %s",
        invoice_number,
        profile.get("org_name", ""),
        out_path,
    )
    return out_path
