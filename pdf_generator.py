"""PDF invoice generator for the Telegram Invoice Bot.

This module handles all ReportLab PDF generation. Nothing else.
PDFs are saved to the invoices/ subfolder (auto-created if missing).

Public entry point:
    generate_invoice_pdf(...) -> Path

Callers (handlers.py) supply the invoice number, date, client name,
items, currency, and the user's profile dict (as produced by
profile_manager.get_profile()). This module does NOT touch
profiles.json; all profile reads/writes live in profile_manager.

Design: "Boutique Stationery" — premium minimalist on A4 portrait.
Restrained logo top-left, large invoice number top-right, two-column
From/Billed-to block, airy items table with hairline rules, and a
prominent right-aligned Amount Due block.

Fonts: only ReportLab's built-in fonts (Helvetica, Helvetica-Bold,
Courier) are used so the bot runs on Replit without installing
anything extra. The Euro sign (€, U+20AC) is part of WinAnsi
encoding and renders correctly in the built-in fonts. The Tenge sign
(₸, U+20B8) is NOT in WinAnsi — for KZT and any other currency
without a registered symbol we render the 3-letter code instead.

Logo: optional. Drop a PNG (or any ImageReader-compatible format) at
the path defined by LOGO_PATH. If the file is missing or fails to
load, the layout falls back to a Helvetica-Bold org name wordmark so
the PDF still generates cleanly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)

# ─── Output location ────────────────────────────────────────────────────────
INVOICES_DIR = Path("invoices")

# ─── Optional logo asset ────────────────────────────────────────────────────
LOGO_PATH = Path(__file__).parent / "assets" / "illkin_black.png"

# ─── Page geometry (A4 portrait, gently asymmetric margins) ─────────────────
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_LEFT = 22 * mm
MARGIN_RIGHT = 22 * mm
MARGIN_TOP = 25 * mm
MARGIN_BOTTOM = 25 * mm

CONTENT_LEFT = MARGIN_LEFT
CONTENT_RIGHT = PAGE_WIDTH - MARGIN_RIGHT
CONTENT_WIDTH = CONTENT_RIGHT - CONTENT_LEFT

# ─── Palette ────────────────────────────────────────────────────────────────
INK: Color = HexColor("#000000")
INK_BODY: Color = HexColor("#1A1A1A")
GREY_MID: Color = HexColor("#666666")
GREY_SOFT: Color = HexColor("#888888")
GREY_LINE: Color = HexColor("#D9D9D9")

# ─── Items-table column geometry ────────────────────────────────────────────
COL_NUM_W = CONTENT_WIDTH * 0.10
COL_DESC_W = CONTENT_WIDTH * 0.65
COL_AMOUNT_W = CONTENT_WIDTH * 0.25

COL_NUM_X = CONTENT_LEFT
COL_DESC_X = CONTENT_LEFT + COL_NUM_W
COL_AMOUNT_X = CONTENT_LEFT + COL_NUM_W + COL_DESC_W
COL_AMOUNT_RIGHT = COL_AMOUNT_X + COL_AMOUNT_W

# ─── Logo sizing ────────────────────────────────────────────────────────────
HEADER_LOGO_WIDTH = 32 * mm
FOOTER_LOGO_WIDTH = 14 * mm

# ─── Currency rendering ─────────────────────────────────────────────────────
CURRENCY_SYMBOLS: dict[str, str] = {
    "EUR": "€",
    "USD": "$",
}


# ─── Reference computation ──────────────────────────────────────────────────

def _compute_reference(
    profile: dict[str, Any], invoice_number: int
) -> str | None:
    """Return the payment-reference string for this invoice, or None.

    Honors the profile's ``reference_style`` preference:
        - ``"Standard"`` (case-insensitive)  → ``"INV-00042"``
        - anything else, including ``"None"``, missing, or blank → ``None``

    The result is rendered on the PDF only if it is a non-None string,
    so callers don't need to worry about a stray "Reference:" label with
    no value next to it.
    """
    style = str(profile.get("reference_style", "")).strip().lower()
    if style == "standard":
        return f"INV-{int(invoice_number):05d}"
    return None


# ─── Formatting helpers ─────────────────────────────────────────────────────

def _format_money(amount: float, currency: str = "EUR") -> str:
    """Format a number with the given currency."""
    code = (currency or "EUR").upper()
    symbol = CURRENCY_SYMBOLS.get(code)
    if symbol:
        return f"{symbol} {amount:,.2f}"
    return f"{code} {amount:,.2f}"


def _format_eur(amount: float) -> str:
    """Backwards-compatible Euro formatter."""
    return _format_money(amount, "EUR")


def _ensure_invoices_dir() -> None:
    INVOICES_DIR.mkdir(parents=True, exist_ok=True)


def _build_filename(invoice_date: date) -> str:
    date_part = invoice_date.strftime("%Y-%m-%d")
    time_part = datetime.now().strftime("%H%M")
    return f"Invoice_{date_part}_{time_part}.pdf"


# ─── Typography primitives ──────────────────────────────────────────────────

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
    if stringWidth(text, font, size) <= max_width:
        return text
    ellipsis = "…"
    for i in range(len(text) - 1, 0, -1):
        candidate = text[:i].rstrip() + ellipsis
        if stringWidth(candidate, font, size) <= max_width:
            return candidate
    return ellipsis


# ─── Header ─────────────────────────────────────────────────────────────────

def _draw_logo(
    c: canvas.Canvas,
    x: float,
    y_top: float,
    wordmark: str = "",
    logo_override: str | None = None,
) -> tuple[float, float]:
    candidate_paths: list[Path] = []
    if logo_override:
        candidate_paths.append(Path(logo_override))
    candidate_paths.append(LOGO_PATH)

    for candidate in candidate_paths:
        if not candidate.exists():
            continue
        try:
            img = ImageReader(str(candidate))
            iw, ih = img.getSize()
            if iw <= 0 or ih <= 0:
                raise ValueError("Logo has non-positive dimensions")
            scale = HEADER_LOGO_WIDTH / float(iw)
            drawn_h = ih * scale
            c.drawImage(
                img,
                x,
                y_top - drawn_h,
                width=HEADER_LOGO_WIDTH,
                height=drawn_h,
                mask="auto",
                preserveAspectRatio=True,
            )
            return y_top - drawn_h, drawn_h
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not render header logo at %s; trying next option.",
                candidate,
            )

    fallback_size = 22
    baseline_y = y_top - fallback_size
    _draw_text(
        c, x, baseline_y, wordmark,
        font="Helvetica-Bold", size=fallback_size, color=INK,
    )
    return baseline_y, fallback_size


def _draw_header(
    c: canvas.Canvas,
    invoice_number: int,
    invoice_date: date,
    profile: dict[str, Any],
) -> float:
    header_top = PAGE_HEIGHT - MARGIN_TOP

    org_name = str(profile.get("org_name", "")).strip() or "—"
    logo_override = profile.get("logo_path")
    logo_bottom, logo_h = _draw_logo(
        c, CONTENT_LEFT, header_top,
        wordmark=org_name,
        logo_override=logo_override,
    )

    LABEL_SIZE = 7.5
    NUMBER_SIZE = 22
    DATE_SIZE = 10
    CAP = 0.717
    NUMBER_GAP = 7

    band_center = (header_top + logo_bottom) / 2
    number_y = band_center - 4
    label_y = number_y + NUMBER_SIZE * CAP + NUMBER_GAP
    date_y = number_y - NUMBER_GAP - DATE_SIZE * CAP

    _draw_tracked(
        c, CONTENT_RIGHT, label_y, "INVOICE",
        font="Helvetica-Bold", size=LABEL_SIZE, tracking=1.6,
        color=GREY_SOFT, align="right",
    )
    _draw_text(
        c, CONTENT_RIGHT, number_y, f"#{invoice_number:05d}",
        font="Helvetica-Bold", size=NUMBER_SIZE, color=INK, align="right",
    )
    _draw_text(
        c, CONTENT_RIGHT, date_y, invoice_date.strftime("%d.%m.%Y"),
        font="Helvetica", size=DATE_SIZE, color=GREY_MID, align="right",
    )

    divider_y = min(logo_bottom, date_y - 4) - 10 * mm
    _hairline(c, divider_y)
    return divider_y


# ─── From / Billed to ───────────────────────────────────────────────────────

def _draw_parties(
    c: canvas.Canvas,
    profile: dict[str, Any],
    client_name: str | None,
    y_top: float,
    reference: str | None = None,
) -> float:
    """Two-column From / Billed-to block.

    The From column renders, in order, only the fields that have a
    value: org name (always), phone, email, IBAN, and the payment
    reference. Each missing field is silently skipped so the block
    stays tight regardless of which optional fields the user filled in.

    Returns y-coordinate at the bottom of the taller column.
    """
    gutter = 10 * mm
    col_w = (CONTENT_WIDTH - gutter) / 2
    from_x = CONTENT_LEFT
    to_x = CONTENT_LEFT + col_w + gutter

    label_y = y_top - 14
    _draw_tracked(
        c, from_x, label_y, "FROM",
        font="Helvetica-Bold", size=7.5, tracking=2.0,
        color=GREY_SOFT,
    )
    _draw_tracked(
        c, to_x, label_y, "BILLED TO",
        font="Helvetica-Bold", size=7.5, tracking=2.0,
        color=GREY_SOFT,
    )

    # ── From column ──
    y = label_y - 18
    org_name = str(profile.get("org_name", "")).strip() or "—"
    _draw_text(
        c, from_x, y,
        _truncate_to_width(org_name, "Helvetica-Bold", 11, col_w),
        font="Helvetica-Bold", size=11, color=INK,
    )
    y -= 15

    phone = str(profile.get("phone", "")).strip()
    if phone:
        _draw_text(
            c, from_x, y,
            _truncate_to_width(phone, "Helvetica", 10, col_w),
            font="Helvetica", size=10, color=INK_BODY,
        )
        y -= 13

    # Optional issuer email — rendered only when present.
    email = str(profile.get("email", "")).strip()
    if email:
        _draw_text(
            c, from_x, y,
            _truncate_to_width(email, "Helvetica", 10, col_w),
            font="Helvetica", size=10, color=INK_BODY,
        )
        y -= 13

    iban = str(profile.get("iban", "")).strip()
    if iban:
        # Courier deliberately retained for the IBAN — it cues "type me".
        _draw_text(
            c, from_x, y,
            _truncate_to_width(iban, "Courier", 10, col_w),
            font="Courier", size=10, color=INK_BODY,
        )
        y -= 13

    # Payment reference — Courier (same "type me" cue as the IBAN), with
    # a small tracked "REF" label so it reads as payment metadata rather
    # than a second account number.
    if reference:
        ref_line = f"REF: {reference}"
        _draw_text(
            c, from_x, y,
            _truncate_to_width(ref_line, "Courier", 10, col_w),
            font="Courier", size=10, color=INK_BODY,
        )
        y -= 13

    from_bottom = y

    # ── Billed to column ──
    y = label_y - 18
    display_name = (client_name or "").strip() or "—"
    _draw_text(
        c, to_x, y,
        _truncate_to_width(display_name, "Helvetica-Bold", 11, col_w),
        font="Helvetica-Bold", size=11, color=INK,
    )
    y -= 15
    to_bottom = y

    return min(from_bottom, to_bottom)


# ─── Due date row ───────────────────────────────────────────────────────────

def _draw_due_date(
    c: canvas.Canvas,
    due_date: str,
    y_top: float,
) -> float:
    label_y = y_top - 8 * mm
    value_y = label_y - 13

    _draw_tracked(
        c, CONTENT_RIGHT, label_y, "DUE DATE",
        font="Helvetica-Bold", size=7.5, tracking=2.0,
        color=GREY_SOFT, align="right",
    )
    _draw_text(
        c, CONTENT_RIGHT, value_y, due_date,
        font="Helvetica", size=10, color=INK_BODY, align="right",
    )
    return value_y - 4


# ─── Items table ────────────────────────────────────────────────────────────

def _draw_items_table(
    c: canvas.Canvas,
    items: list[dict[str, Any]],
    y_top: float,
    currency: str = "EUR",
) -> tuple[float, float]:
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
    total = 0.0

    for idx, item in enumerate(items, start=1):
        name = str(item.get("name", ""))
        price = float(item.get("price", 0))
        total += price

        lines = simpleSplit(name, body_font, body_size, desc_inner_w)
        if not lines:
            lines = [""]

        first_baseline = y - top_pad - body_size

        _draw_text(
            c, COL_NUM_X + COL_NUM_W / 2, first_baseline,
            str(idx),
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
    return y, total


# ─── Total ──────────────────────────────────────────────────────────────────

def _draw_total(
    c: canvas.Canvas,
    total: float,
    y_top: float,
    currency: str = "EUR",
) -> None:
    label_y = y_top - 12 * mm
    amount_y = label_y - 24

    _draw_tracked(
        c, CONTENT_RIGHT, label_y, "AMOUNT DUE",
        font="Helvetica-Bold", size=8, tracking=2.0,
        color=GREY_SOFT, align="right",
    )
    _draw_text(
        c, CONTENT_RIGHT, amount_y, _format_money(total, currency),
        font="Helvetica-Bold", size=24, color=INK, align="right",
    )


# ─── Footer ─────────────────────────────────────────────────────────────────

def _draw_footer(c: canvas.Canvas, profile: dict[str, Any]) -> None:
    rule_y = MARGIN_BOTTOM + 15 * mm
    _hairline(c, rule_y)

    text_y = rule_y - 14
    _draw_text(
        c, CONTENT_LEFT, text_y, "Thank you for your business!",
        font="Helvetica", size=9, color=GREY_MID,
    )

    logo_override = profile.get("logo_path")
    candidate_paths: list[Path] = []
    if logo_override:
        candidate_paths.append(Path(logo_override))
    candidate_paths.append(LOGO_PATH)

    drew_image = False
    for candidate in candidate_paths:
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
                width=FOOTER_LOGO_WIDTH,
                height=h,
                mask="auto",
                preserveAspectRatio=True,
            )
            drew_image = True
            break
        except Exception:  # noqa: BLE001
            logger.warning(
                "Could not render footer logo at %s; trying next option.",
                candidate,
            )

    if not drew_image:
        org_name = str(profile.get("org_name", "")).strip() or "—"
        _draw_text(
            c, CONTENT_RIGHT, text_y, org_name,
            font="Helvetica-Bold", size=9, color=INK, align="right",
        )


# ─── Public entry point ─────────────────────────────────────────────────────

def generate_invoice_pdf(
    *,
    invoice_number: int,
    invoice_date: date,
    client_name: str | None,
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    currency: str = "EUR",
    due_date: str | None = None,
) -> Path:
    """Generate the invoice PDF and return its absolute file path.

    Reference number: computed internally from ``profile["reference_style"]``
    and ``invoice_number``. When the profile's reference style is
    ``"Standard"``, a line such as ``REF: INV-00042`` is rendered in the
    From column under the IBAN. When it is ``"None"`` (or missing) the
    line is silently omitted — no empty "Reference:" label is shown.

    Issuer email: read from ``profile["email"]`` and rendered in the
    From column under the phone number, but only when present.
    """
    _ensure_invoices_dir()

    out_path = INVOICES_DIR / _build_filename(invoice_date)
    c = canvas.Canvas(str(out_path), pagesize=A4)

    # 1. Masthead (logo + invoice number + date), capped by a hairline.
    y_after_header = _draw_header(c, invoice_number, invoice_date, profile)

    # 2. From / Billed-to two-column block (email + reference are
    #    rendered inside _draw_parties when present).
    reference = _compute_reference(profile, invoice_number)
    y_after_parties = _draw_parties(
        c, profile, client_name, y_after_header, reference=reference,
    )

    # 2b. Optional due date, right-aligned under the parties block.
    if due_date:
        y_after_parties = _draw_due_date(c, due_date, y_after_parties)

    # 3. Items table.
    y_table_top = y_after_parties - 14 * mm
    y_after_table, total = _draw_items_table(
        c, items, y_table_top, currency=currency
    )

    # 4. Refined total block.
    _draw_total(c, total, y_after_table, currency=currency)

    # 5. Hairline footer.
    _draw_footer(c, profile)

    c.showPage()
    c.save()

    logger.info(
        "Wrote invoice PDF #%05d (currency=%s, ref=%s, email=%s) for org=%r to %s",
        invoice_number,
        currency,
        reference or "—",
        "yes" if profile.get("email") else "no",
        profile.get("org_name", ""),
        out_path,
    )
    return out_path
