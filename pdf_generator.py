"""PDF invoice generator for the Telegram Invoice Bot.

This module handles all ReportLab PDF generation. Nothing else.
PDFs are saved to the invoices/ subfolder (auto-created if missing).

Public entry point:
    generate_invoice_pdf(...) -> Path

This module does NOT touch profiles.json; all profile reads/writes live
in profile_manager.

Design — "Boutique Stationery" v2 — premium minimalist on A4 portrait:
    1. Masthead         (logo top-left  ·  INVOICE #00001 top-right)
    2. 2x2 info grid    (FROM / BILLED TO  on top row,
                         DETAILS / PAYMENT on bottom row)
    3. Items table      (airy, no per-row separators)
    4. Totals ladder    (optional Subtotal / Discount / VAT rows,
                         then a large right-aligned AMOUNT DUE)
    5. Footer           (hairline + thank-you note + small wordmark)

Panels are very faint tinted rectangles (#F6F6F6) with no border, so
the page reads as airy whitespace with two zones of "soft volume"
rather than a tax form full of boxes.

Fonts: only ReportLab's built-in fonts (Helvetica, Helvetica-Bold,
Courier). The Euro sign and the ellipsis are part of WinAnsi
and render correctly in the built-in fonts. The Tenge sign is NOT
in WinAnsi — for KZT and any other currency without a registered
symbol the 3-letter code is rendered instead.

Logo: optional. Drop a PNG at LOGO_PATH (or pass an override via
``profile["logo_path"]``). If no logo is available, the layout falls
back to a Helvetica-Bold wordmark using the user's org name so the
PDF still generates cleanly.

Backwards compatibility — preserved from the previous generator:
    * Currency is a parameter (defaults to EUR), so EUR / USD / KZT
      and any custom 2-4 letter code render correctly.
    * Payment reference is computed internally from
      ``profile["reference_style"]`` + ``invoice_number`` — no
      caller change required.
    * Optional issuer email from ``profile["email"]`` is rendered in
      the FROM panel under the phone number.
    * Optional issuer VAT number from ``profile["vat_number"]`` is
      rendered in the FROM panel after the email (Fix 3).
    * Optional client details (phone / address / bank / VAT) are
      rendered in the BILLED TO panel below the client name (Fix 4).
    * Optional logo override via ``profile["logo_path"]`` is honored
      for both header and footer.
    * ``due_date`` may be a date object or a pre-formatted string
      (e.g. "30.05.2026", "On receipt"), matching what handlers.py
      currently passes.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# Output location
INVOICES_DIR = Path("invoices")

# Optional logo asset
LOGO_PATH = Path(__file__).parent / "assets" / "illkin_black.png"

# Page geometry (A4 portrait, gently asymmetric margins)
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 22 * mm
MARGIN_RIGHT = 22 * mm
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 25 * mm

CONTENT_LEFT = MARGIN_LEFT
CONTENT_RIGHT = PAGE_WIDTH - MARGIN_RIGHT
CONTENT_WIDTH = CONTENT_RIGHT - CONTENT_LEFT

# Palette (premium neutral, no color accents)
INK: Color = HexColor("#000000")         # logo, headline numbers, total figure
INK_BODY: Color = HexColor("#1A1A1A")    # body text in table and panels
GREY_MID: Color = HexColor("#666666")    # secondary meta (footer note, etc.)
GREY_SOFT: Color = HexColor("#888888")   # tracked uppercase labels
GREY_LINE: Color = HexColor("#D9D9D9")   # hairline rules
PANEL_FILL: Color = HexColor("#F6F6F6")  # very faint tint, no border

# 2x2 info-grid geometry
PANEL_GUTTER = 8           # pt — horizontal gap between left/right panels
PANEL_ROW_GAP = 8          # pt — vertical gap between row 1 and row 2
PANEL_WIDTH = (CONTENT_WIDTH - PANEL_GUTTER) / 2
PANEL_PAD_X = 12           # pt — horizontal interior padding
PANEL_PAD_TOP = 12         # pt — gap from panel top to label baseline-cap
PANEL_PAD_BOTTOM = 14      # pt — gap from last content baseline to panel bottom
PANEL_LABEL_SIZE = 7.5
PANEL_LABEL_TRACK = 2.0
PANEL_LABEL_GAP = 12       # pt — gap from label baseline to first content top

# Items-table column geometry
COL_NUM_W = CONTENT_WIDTH * 0.08
COL_AMOUNT_W = CONTENT_WIDTH * 0.22
COL_DESC_W = CONTENT_WIDTH - COL_NUM_W - COL_AMOUNT_W
COL_NUM_X = CONTENT_LEFT
COL_DESC_X = CONTENT_LEFT + COL_NUM_W
COL_AMOUNT_X = COL_DESC_X + COL_DESC_W
COL_AMOUNT_RIGHT = COL_AMOUNT_X + COL_AMOUNT_W

# Key/value typography (used inside DETAILS + PAYMENT panels)
KV_LABEL_FONT = "Helvetica-Bold"
KV_LABEL_SIZE = 7
KV_LABEL_TRACK = 1.4
KV_LABEL_COL_W = 70        # pt — fixed-width label column; wide enough for "REFERENCE"
KV_VALUE_SIZE = 10
KV_LINE_H = 14             # pt — line height between key/value rows

# Logo sizing
HEADER_LOGO_WIDTH = 32 * mm
FOOTER_LOGO_WIDTH = 14 * mm

# Currency rendering
# Symbols rendered by WinAnsi-encoded built-in fonts. Anything not in
# this table falls back to the 3-letter ISO code (e.g. "KZT 1,000.00").
CURRENCY_SYMBOLS: dict[str, str] = {
    "EUR": "\u20ac",
    "USD": "$",
}


# Reference computation

def _compute_reference(
    profile: dict[str, Any], invoice_number: int
) -> str | None:
    """Return the payment-reference string for this invoice, or None.

    Honors the profile's ``reference_style`` preference:
        - "Standard" (case-insensitive)  -> "INV-00042"
        - anything else, including "None", missing, or blank -> None

    When None, the PAYMENT panel renders only the IBAN row.
    """
    style = str(profile.get("reference_style", "")).strip().lower()
    if style == "standard":
        return f"INV-{int(invoice_number):05d}"
    return None


# Formatting helpers

def _format_money(amount: float, currency: str = "EUR") -> str:
    """Format a number with the given currency.

    "EUR 1,000.00" for recognised symbols, "KZT 1,000.00" otherwise.
    """
    code = (currency or "EUR").upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol} {amount:,.2f}"
    return f"{code} {amount:,.2f}"


def _ensure_invoices_dir() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)


def _build_filename(invoice_date: date) -> str:
    """Filename: Invoice_YYYY-MM-DD_HHMM.pdf — unchanged."""
    date_part = invoice_date.strftime("%Y-%m-%d")
    time_part = datetime.now().strftime("%H%M")
    return f"Invoice_{date_part}_{time_part}.pdf"


def _format_due_date(due_date: Any) -> str:
    """Render a due date value as a string.

    Accepts either a ``date``/``datetime`` (formatted DD.MM.YYYY) or a
    pre-formatted string like "30.05.2026" or "On receipt" — the latter
    is what handlers.py currently passes, so we just return it as-is.
    """
    if isinstance(due_date, (date, datetime)):
        return due_date.strftime("%d.%m.%Y")
    return str(due_date)


# Typography primitives

def _draw_text(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    *,
    font: str,
    size: float,
    color: Color,
    align: str = "left",
) -> None:
    """Plain text draw with explicit font + color + alignment."""
    c.setFont(font, size)
    c.setFillColor(color)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


def _draw_tracked(
    c: canvas.Canvas,
    x: float,
    y: float,
    text: str,
    *,
    font: str,
    size: float,
    tracking: float,
    color: Color,
    align: str = "left",
) -> None:
    """Draw text with positive character spacing ("tracking")."""
    rendered = stringWidth(text, font, size) + tracking * max(len(text) - 1, 0)
    if align == "right":
        start_x = x - rendered
    elif align == "center":
        start_x = x - rendered / 2
    else:
        start_x = x

    t = c.beginText(start_x, y)
    t.setFont(font, size)
    t.setFillColor(color)
    t.setCharSpace(tracking)
    t.textOut(text)
    c.drawText(t)


def _hairline(
    c: canvas.Canvas,
    y: float,
    x1: float | None = None,
    x2: float | None = None,
) -> None:
    """Draw a 0.5pt GREY_LINE hairline. Spans content width by default."""
    if x1 is None:
        x1 = CONTENT_LEFT
    if x2 is None:
        x2 = CONTENT_RIGHT
    c.setStrokeColor(GREY_LINE)
    c.setLineWidth(0.5)
    c.line(x1, y, x2, y)


def _truncate_to_width(
    text: str, font: str, size: float, max_width: float
) -> str:
    """Ellipsis-truncate `text` so it fits within `max_width`."""
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "\u2026"
    for i in range(len(text) - 1, 0, -1):
        candidate = text[:i].rstrip() + ellipsis
        if stringWidth(candidate, font, size) <= max_width:
            return candidate
    return ellipsis


# Header

def _draw_logo(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    width: float,
    fallback_wordmark: str,
    logo_override: str | None = None,
) -> float:
    """Draw a logo at (x, y_top - height). Returns the logo's bottom y."""
    candidates: list[Path] = []
    if logo_override:
        candidates.append(Path(logo_override))
    candidates.append(LOGO_PATH)

    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            img = ImageReader(str(candidate))
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                raise ValueError("Logo has non-positive dimensions")
            scale = width / float(iw)
            drawn_h = ih * scale
            c.drawImage(
                img, x, y_top - drawn_h,
                width=width, height=drawn_h,
                mask="auto", preserveAspectRatio=True,
            )
            return y_top - drawn_h
        except Exception:  # noqa: BLE001 — any ImageReader failure -> next option
            logger.warning(
                "Could not render logo at %s; trying next option.", candidate
            )

    fallback_size = 22
    baseline_y = y_top - fallback_size
    _draw_text(
        c, x, baseline_y, fallback_wordmark,
        font="Helvetica-Bold", size=fallback_size, color=INK,
    )
    return baseline_y


def _draw_header(
    c: canvas.Canvas,
    invoice_number: int,
    profile: dict[str, Any],
) -> float:
    """Logo top-left, INVOICE #00001 top-right, hairline below."""
    header_top = PAGE_HEIGHT - MARGIN_TOP

    fallback = str(profile.get("org_name", "")).strip() or "\u2014"
    logo_override = profile.get("logo_path")

    logo_bottom = _draw_logo(
        c, CONTENT_LEFT, header_top,
        width=HEADER_LOGO_WIDTH,
        fallback_wordmark=fallback,
        logo_override=logo_override,
    )

    band_center = (header_top + logo_bottom) / 2
    label_y = band_center + 8
    number_y = band_center - 12

    _draw_tracked(
        c, CONTENT_RIGHT, label_y, "INVOICE",
        font="Helvetica-Bold", size=7.5, tracking=1.6,
        color=GREY_SOFT, align="right",
    )
    _draw_text(
        c, CONTENT_RIGHT, number_y, f"#{invoice_number:05d}",
        font="Helvetica-Bold", size=22, color=INK, align="right",
    )

    divider_y = min(logo_bottom, number_y - 6) - 10 * mm
    _hairline(c, divider_y)
    return divider_y


# Panel chrome (fill + label)

def _draw_panel_chrome(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    width: float,
    height: float,
    label: str,
) -> tuple[float, float, float]:
    """Fill a tinted rectangle, draw the label, return the content area."""
    c.setFillColor(PANEL_FILL)
    c.rect(x, y_top - height, width, height, stroke=0, fill=1)

    label_baseline = y_top - PANEL_PAD_TOP - PANEL_LABEL_SIZE
    _draw_tracked(
        c, x + PANEL_PAD_X, label_baseline, label,
        font="Helvetica-Bold", size=PANEL_LABEL_SIZE,
        tracking=PANEL_LABEL_TRACK, color=GREY_SOFT,
    )

    content_x = x + PANEL_PAD_X
    content_y_top = label_baseline - PANEL_LABEL_GAP
    content_w = width - 2 * PANEL_PAD_X
    return content_x, content_y_top, content_w


def _panel_chrome_overhead() -> float:
    """Total non-content height a panel needs (padding + label + gap)."""
    return PANEL_PAD_TOP + PANEL_LABEL_SIZE + PANEL_LABEL_GAP + PANEL_PAD_BOTTOM


# FROM panel content
# Identity: org name + phone + (optional) email + (optional) VAT.
# IBAN moved to PAYMENT.

def _measure_from(profile: dict[str, Any]) -> float:
    """Return the height (top to lowest baseline) of the FROM content."""
    h = 11  # org name (11pt)
    if str(profile.get("phone", "")).strip():
        h += 6 + 10  # gap + phone line (10pt)
    if str(profile.get("email", "")).strip():
        h += 6 + 10  # gap + email line (10pt)
    if str(profile.get("vat_number", "")).strip():
        h += 6 + 10  # gap + VAT line (10pt) — Fix 3
    return h


def _draw_from(
    c: canvas.Canvas, x: float, y_top: float, width: float,
    profile: dict[str, Any],
) -> None:
    org = str(profile.get("org_name", "")).strip() or "\u2014"
    y = y_top - 11
    _draw_text(
        c, x, y,
        _truncate_to_width(org, "Helvetica-Bold", 11, width),
        font="Helvetica-Bold", size=11, color=INK,
    )

    phone = str(profile.get("phone", "")).strip()
    if phone:
        y -= 6 + 10
        _draw_text(
            c, x, y,
            _truncate_to_width(phone, "Helvetica", 10, width),
            font="Helvetica", size=10, color=INK_BODY,
        )

    email = str(profile.get("email", "")).strip()
    if email:
        y -= 6 + 10
        _draw_text(
            c, x, y,
            _truncate_to_width(email, "Helvetica", 10, width),
            font="Helvetica", size=10, color=INK_BODY,
        )

    # Fix 3 — issuer VAT number, rendered like phone/email.
    vat = str(profile.get("vat_number", "")).strip()
    if vat:
        y -= 6 + 10
        _draw_text(
            c, x, y,
            _truncate_to_width(f"VAT: {vat}", "Helvetica", 10, width),
            font="Helvetica", size=10, color=INK_BODY,
        )


# BILLED TO panel content
# Client name + (optional) phone, address, bank, VAT. Fix 4.

# Mapping from client_details key -> label prefix shown on the PDF.
# Order is preserved (Python dicts since 3.7) — phone, address, bank, VAT.
_CLIENT_DETAIL_LABELS: dict[str, str] = {
    "phone": "Tel:",
    "address": "",       # address has no prefix; it speaks for itself
    "bank": "IBAN:",
    "vat": "VAT:",
}


def _client_detail_lines(client_details: dict[str, Any] | None) -> list[str]:
    """Build the list of rendered detail lines, in order, skipping empties."""
    details = client_details or {}
    lines: list[str] = []
    for key, prefix in _CLIENT_DETAIL_LABELS.items():
        raw = details.get(key)
        val = str(raw).strip() if raw else ""
        if not val:
            continue
        lines.append(f"{prefix} {val}".strip() if prefix else val)
    return lines


def _measure_billed_to(
    client_name: str | None,
    client_details: dict[str, Any] | None = None,
) -> float:
    """Return the height of the BILLED TO content (name + optional detail rows)."""
    h = 11  # name
    for _ in _client_detail_lines(client_details):
        h += 6 + 10  # gap + detail line
    return h


def _draw_billed_to(
    c: canvas.Canvas, x: float, y_top: float, width: float,
    client_name: str | None,
    client_details: dict[str, Any] | None = None,
) -> None:
    name = (client_name or "").strip() or "\u2014"
    y = y_top - 11
    _draw_text(
        c, x, y,
        _truncate_to_width(name, "Helvetica-Bold", 11, width),
        font="Helvetica-Bold", size=11, color=INK,
    )

    for line in _client_detail_lines(client_details):
        y -= 6 + 10
        _draw_text(
            c, x, y,
            _truncate_to_width(line, "Helvetica", 10, width),
            font="Helvetica", size=10, color=INK_BODY,
        )


# Generic key/value rows (used by DETAILS + PAYMENT)

def _kv_content_height(n_rows: int) -> float:
    """Height of an n-row k/v block from top-of-cap to last baseline."""
    if n_rows <= 0:
        return 0
    return KV_VALUE_SIZE + (n_rows - 1) * KV_LINE_H


def _draw_kv_rows(
    c: canvas.Canvas, x: float, y_top: float, width: float,
    rows: list[tuple[str, str] | tuple[str, str, str]],
) -> None:
    """Render a list of (label, value, [value_font]) rows."""
    for i, row in enumerate(rows):
        if len(row) == 3:
            label, value, vfont = row
        else:
            label, value = row  # type: ignore[misc]
            vfont = "Helvetica"
        baseline = y_top - KV_VALUE_SIZE - i * KV_LINE_H

        _draw_tracked(
            c, x, baseline, label.upper(),
            font=KV_LABEL_FONT, size=KV_LABEL_SIZE,
            tracking=KV_LABEL_TRACK, color=GREY_SOFT,
        )

        value_x = x + KV_LABEL_COL_W
        value_max_w = width - KV_LABEL_COL_W
        _draw_text(
            c, value_x, baseline,
            _truncate_to_width(str(value), vfont, KV_VALUE_SIZE, value_max_w),
            font=vfont, size=KV_VALUE_SIZE, color=INK_BODY,
        )


# DETAILS panel content
# Invoice metadata — issued date and (optional) due date. NOT how to pay.

def _details_rows(
    invoice_date: date, due_date: Any
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [("Issued", invoice_date.strftime("%d.%m.%Y"))]
    if due_date:
        rows.append(("Due", _format_due_date(due_date)))
    return rows


def _measure_details(invoice_date: date, due_date: Any) -> float:
    return _kv_content_height(len(_details_rows(invoice_date, due_date)))


def _draw_details(
    c: canvas.Canvas, x: float, y_top: float, width: float,
    invoice_date: date, due_date: Any,
) -> None:
    _draw_kv_rows(c, x, y_top, width, _details_rows(invoice_date, due_date))


# PAYMENT panel content
# Everything the client needs to actually send money: IBAN + reference.

def _payment_rows(
    profile: dict[str, Any], payment_reference: str | None
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    iban = str(profile.get("iban", "")).strip()
    rows.append(("IBAN", iban or "\u2014", "Courier"))

    ref = (payment_reference or "").strip()
    if ref:
        rows.append(("Reference", ref, "Courier"))
    return rows


def _measure_payment(
    profile: dict[str, Any], payment_reference: str | None
) -> float:
    return _kv_content_height(len(_payment_rows(profile, payment_reference)))


def _draw_payment(
    c: canvas.Canvas, x: float, y_top: float, width: float,
    profile: dict[str, Any], payment_reference: str | None,
) -> None:
    _draw_kv_rows(c, x, y_top, width, _payment_rows(profile, payment_reference))


# 2x2 info grid

def _draw_info_grid(
    c: canvas.Canvas,
    y_top: float,
    profile: dict[str, Any],
    client_name: str | None,
    invoice_date: date,
    due_date: Any,
    payment_reference: str | None,
    client_details: dict[str, Any] | None = None,
) -> float:
    """Render the four panels and return the y at the grid's bottom."""
    chrome = _panel_chrome_overhead()
    row1_h = chrome + max(
        _measure_from(profile),
        _measure_billed_to(client_name, client_details),
    )
    row2_h = chrome + max(
        _measure_details(invoice_date, due_date),
        _measure_payment(profile, payment_reference),
    )

    left_x = CONTENT_LEFT
    right_x = CONTENT_LEFT + PANEL_WIDTH + PANEL_GUTTER

    # Row 1 — FROM | BILLED TO
    cx, cy, cw = _draw_panel_chrome(c, left_x, y_top, PANEL_WIDTH, row1_h, "FROM")
    _draw_from(c, cx, cy, cw, profile)

    cx, cy, cw = _draw_panel_chrome(c, right_x, y_top, PANEL_WIDTH, row1_h, "BILLED TO")
    _draw_billed_to(c, cx, cy, cw, client_name, client_details)

    # Row 2 — DETAILS | PAYMENT
    row2_top = y_top - row1_h - PANEL_ROW_GAP

    cx, cy, cw = _draw_panel_chrome(c, left_x, row2_top, PANEL_WIDTH, row2_h, "DETAILS")
    _draw_details(c, cx, cy, cw, invoice_date, due_date)

    cx, cy, cw = _draw_panel_chrome(c, right_x, row2_top, PANEL_WIDTH, row2_h, "PAYMENT")
    _draw_payment(c, cx, cy, cw, profile, payment_reference)

    return row2_top - row2_h


# Items table

def _draw_items_table(
    c: canvas.Canvas,
    items: list[dict[str, Any]],
    y_top: float,
    currency: str = "EUR",
) -> tuple[float, float]:
    """Draw the items table starting at y_top.

    Returns ``(y_bottom, subtotal)``. Long descriptions wrap with
    simpleSplit and the row grows to fit; no per-row separators, only
    hairlines above and below the body — whitespace holds the table
    together.
    """
    header_baseline = y_top - 10
    _draw_tracked(
        c, COL_NUM_X + COL_NUM_W / 2, header_baseline, "#",
        font="Helvetica-Bold", size=7.5, tracking=1.5,
        color=GREY_SOFT, align="center",
    )
    _draw_tracked(
        c, COL_DESC_X, header_baseline, "DESCRIPTION",
        font="Helvetica-Bold", size=7.5, tracking=1.5,
        color=GREY_SOFT,
    )
    _draw_tracked(
        c, COL_AMOUNT_RIGHT, header_baseline, "AMOUNT",
        font="Helvetica-Bold", size=7.5, tracking=1.5,
        color=GREY_SOFT, align="right",
    )

    rule_y = header_baseline - 8
    _hairline(c, rule_y)

    body_font = "Helvetica"
    amount_font = "Helvetica-Bold"
    body_size = 11
    line_h = 14
    top_pad = 12
    bottom_pad = 12
    desc_inner_w = COL_DESC_W - 6 * mm

    y = rule_y
    subtotal = 0.0

    for idx, item in enumerate(items, start=1):
        name = str(item.get("name", ""))
        price = float(item.get("price", 0))
        subtotal += price

        lines = simpleSplit(name, body_font, body_size, desc_inner_w)
        if not lines:
            lines = [""]

        first_baseline = y - top_pad - body_size

        _draw_text(
            c, COL_NUM_X + COL_NUM_W / 2, first_baseline, str(idx),
            font=body_font, size=body_size, color=INK_BODY, align="center",
        )

        for i, line in enumerate(lines):
            _draw_text(
                c, COL_DESC_X, first_baseline - i * line_h, line,
                font=body_font, size=body_size, color=INK_BODY,
            )

        _draw_text(
            c, COL_AMOUNT_RIGHT, first_baseline,
            _format_money(price, currency),
            font=amount_font, size=body_size, color=INK, align="right",
        )

        row_h = top_pad + body_size + line_h * (len(lines) - 1) + bottom_pad
        y -= row_h

    _hairline(c, y)
    return y, subtotal


# Totals ladder + AMOUNT DUE

def _draw_totals(
    c: canvas.Canvas,
    subtotal: float,
    y_top: float,
    *,
    currency: str = "EUR",
    tax_rate: float | None = None,
    discount: float = 0.0,
) -> float:
    """Right-aligned totals ladder + large AMOUNT DUE figure."""
    label_x = COL_AMOUNT_RIGHT - 30 * mm
    has_ladder = (tax_rate and tax_rate > 0) or (discount and discount != 0)

    y = y_top - 12 * mm
    total = subtotal

    if has_ladder:
        _draw_text(
            c, label_x, y, "Subtotal",
            font="Helvetica", size=10, color=GREY_MID, align="right",
        )
        _draw_text(
            c, COL_AMOUNT_RIGHT, y, _format_money(subtotal, currency),
            font="Helvetica", size=10, color=INK_BODY, align="right",
        )
        y -= 16

        if discount:
            _draw_text(
                c, label_x, y, "Discount",
                font="Helvetica", size=10, color=GREY_MID, align="right",
            )
            _draw_text(
                c, COL_AMOUNT_RIGHT, y, "\u2212 " + _format_money(discount, currency),
                font="Helvetica", size=10, color=INK_BODY, align="right",
            )
            y -= 16
            total = subtotal - discount

        if tax_rate and tax_rate > 0:
            after_discount = subtotal - (discount or 0)
            tax = after_discount * tax_rate
            tax_label = f"VAT {tax_rate * 100:g}%"
            _draw_text(
                c, label_x, y, tax_label,
                font="Helvetica", size=10, color=GREY_MID, align="right",
            )
            _draw_text(
                c, COL_AMOUNT_RIGHT, y, _format_money(tax, currency),
                font="Helvetica", size=10, color=INK_BODY, align="right",
            )
            y -= 16
            total = after_discount + tax

        _hairline(c, y + 6, x1=label_x - 4 * mm, x2=COL_AMOUNT_RIGHT)
        y -= 4

    _draw_tracked(
        c, COL_AMOUNT_RIGHT, y - 8, "AMOUNT DUE",
        font="Helvetica-Bold", size=8, tracking=2.0,
        color=GREY_SOFT, align="right",
    )
    _draw_text(
        c, COL_AMOUNT_RIGHT, y - 8 - 26, _format_money(total, currency),
        font="Helvetica-Bold", size=24, color=INK, align="right",
    )

    return total


# Footer

def _draw_footer(c: canvas.Canvas, profile: dict[str, Any]) -> None:
    """Hairline + 'Thank you for your business!' left, small wordmark right."""
    rule_y = MARGIN_BOTTOM + 15 * mm
    _hairline(c, rule_y)

    text_y = rule_y - 14
    _draw_text(
        c, CONTENT_LEFT, text_y, "Thank you for your business!",
        font="Helvetica", size=9, color=GREY_MID,
    )

    fallback = str(profile.get("org_name", "")).strip() or "\u2014"
    logo_override = profile.get("logo_path")

    candidates: list[Path] = []
    if logo_override:
        candidates.append(Path(logo_override))
    candidates.append(LOGO_PATH)

    drew_image = False
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            img = ImageReader(str(candidate))
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                raise ValueError("Logo has non-positive dimensions")
            scale = FOOTER_LOGO_WIDTH / float(iw)
            h = ih * scale
            c.drawImage(
                img,
                CONTENT_RIGHT - FOOTER_LOGO_WIDTH,
                text_y - h * 0.25,
                width=FOOTER_LOGO_WIDTH, height=h,
                mask="auto", preserveAspectRatio=True,
            )
            drew_image = True
            break
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not render footer logo at %s; trying next option.",
                candidate,
            )

    if not drew_image:
        _draw_text(
            c, CONTENT_RIGHT, text_y, fallback,
            font="Helvetica-Bold", size=9, color=INK, align="right",
        )


# Public entry point

def generate_invoice_pdf(
    *,
    invoice_number: int,
    invoice_date: date,
    client_name: str | None,
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    currency: str = "EUR",
    due_date: Any | None = None,
    payment_reference: str | None = None,
    tax_rate: float | None = None,
    discount_amount: float = 0.0,
    client_details: dict[str, Any] | None = None,
) -> Path:
    """Generate the invoice PDF and return its absolute file path.

    Args:
        invoice_number: Sequential invoice number; rendered zero-padded
            to 5 digits (e.g. 7 -> "#00007").
        invoice_date: Date printed on the invoice (DD.MM.YYYY). Also
            used in the filename.
        client_name: Recipient's name; pass None (or "") to render "—".
        items: List of {"name": str, "price": int | float} dicts in
            the order the user added them.
        profile: User's profile dict as returned by
            profile_manager.get_profile(). Recognised keys: "org_name",
            "phone", "email" (optional), "vat_number" (optional),
            "iban", "reference_style", "logo_path" (optional).
        currency: ISO code (e.g. "EUR", "USD", "KZT", "CHF"). Used in
            both item rows and the totals block.
        due_date: Optional due date.
        payment_reference: Optional payment reference.
        tax_rate: Optional VAT rate as a decimal.
        discount_amount: Optional flat discount in the same currency.
        client_details: Optional dict with keys 'phone', 'address',
            'bank', 'vat'. Each present-and-non-empty value is rendered
            in the BILLED TO panel below the client name (Fix 4).

    Returns:
        Path to the generated PDF inside the invoices/ directory.

    Raises:
        OSError: if the invoices/ directory cannot be created or the
            PDF cannot be written.
    """
    _ensure_invoices_dir()

    reference = (
        payment_reference
        if payment_reference is not None
        else _compute_reference(profile, invoice_number)
    )

    out_path = INVOICES_DIR / _build_filename(invoice_date)
    c = canvas.Canvas(str(out_path), pagesize=A4)

    # 1. Masthead — logo + invoice number, hairline below.
    y = _draw_header(c, invoice_number, profile)

    # 2. 2x2 info grid — FROM / BILLED TO  ·  DETAILS / PAYMENT.
    y = y - 12 * mm
    y = _draw_info_grid(
        c, y, profile, client_name,
        invoice_date, due_date, reference,
        client_details=client_details,
    )

    # 3. Items table.
    y = y - 14 * mm
    y, subtotal = _draw_items_table(c, items, y, currency=currency)

    # 4. Totals ladder (optional) + big AMOUNT DUE.
    total = _draw_totals(
        c, subtotal, y,
        currency=currency,
        tax_rate=tax_rate,
        discount=discount_amount,
    )

    # 5. Footer.
    _draw_footer(c, profile)

    c.showPage()
    c.save()

    logger.info(
        "Wrote invoice PDF #%05d (currency=%s, ref=%s, email=%s, vat=%s, "
        "client_details=%s, total=%s) for org=%r to %s",
        invoice_number,
        currency,
        reference or "\u2014",
        "yes" if profile.get("email") else "no",
        "yes" if profile.get("vat_number") else "no",
        "yes" if client_details and any(client_details.values()) else "no",
        _format_money(total, currency),
        profile.get("org_name", ""),
        out_path,
    )
    return out_path
