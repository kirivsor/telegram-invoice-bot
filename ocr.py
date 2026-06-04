"""Gemini Vision OCR for uploaded receipts/invoices.

Runs entirely in the background (asyncio.create_task). It is fail-soft by
contract: it never raises into the caller and never notifies the user —
the expense is already saved before OCR starts. Rate limiting here is a
cost guard against runaway Gemini spend; all caps come from environment
variables only (never from user input or a DB row).
"""

from __future__ import annotations

import json
import logging
import os

import db

logger = logging.getLogger(__name__)

# --- Cost guards (env-only; never user-writable) --------------------------
_DAILY_USER_CAP = int(os.environ.get("GEMINI_OCR_DAILY_USER_CAP", "20"))
_DAILY_GLOBAL_CAP = int(os.environ.get("GEMINI_OCR_DAILY_GLOBAL_CAP", "500"))

_MODEL = os.environ.get("GEMINI_OCR_MODEL", "gemini-1.5-flash")

_PROMPT = """\
You are a receipt and invoice OCR assistant.
Analyze the image and extract the following fields.
Return ONLY a valid JSON object with no markdown, no explanation.

{
  "merchant": "<business name or null>",
  "total": <total amount as a number or null>,
  "currency": "<3-letter ISO currency code or null>",
  "date": "<date in dd.mm.yyyy format or null>",
  "vat_amount": <VAT/tax amount as a number or null>,
  "line_items": [
    {"description": "<item description>", "amount": <number>}
  ]
}

If a field cannot be determined from the image, use null.
Do not guess. Only extract what is clearly visible.
"""


def _coerce_number(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_gemini_text(text: str) -> dict:
    """Gemini sometimes wraps JSON in ```json fences despite instructions.
    Strip them defensively before parsing."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)
        cleaned = cleaned[1] if len(cleaned) > 1 else ""
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    return json.loads(cleaned.strip())


async def run_ocr_job(attachment_id: str) -> None:
    """Best-effort OCR for one attachment. Never raises."""
    import asyncio

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; skipping OCR for %s", attachment_id)
        return

    try:
        attachment = db.get_attachment(attachment_id)
        if attachment is None:
            logger.warning("run_ocr_job: attachment %s not found", attachment_id)
            return

        user_id = attachment["user_id"]

        # --- Rate guards (env-only caps; trusted user_id from DB row) -----
        try:
            if db.count_ocr_jobs_user_today(user_id) >= _DAILY_USER_CAP:
                logger.warning(
                    "OCR skipped: user %s hit daily cap (%s)", user_id, _DAILY_USER_CAP
                )
                return
            if db.count_ocr_jobs_global_today() >= _DAILY_GLOBAL_CAP:
                logger.warning(
                    "OCR skipped: global daily cap reached (%s)", _DAILY_GLOBAL_CAP
                )
                return
        except Exception:
            logger.exception("OCR rate check failed for %s; skipping", attachment_id)
            return

        image_path = attachment.get("cleaned_path") or attachment.get("original_path")
        if not image_path or not os.path.exists(image_path):
            logger.warning("run_ocr_job: image missing for %s", attachment_id)
            return

        job_id = db.insert_ocr_job(attachment_id)
    except Exception:
        logger.exception("run_ocr_job setup failed for %s", attachment_id)
        return

    try:
        def _blocking_ocr() -> str:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(_MODEL)
            with open(image_path, "rb") as fh:
                image_bytes = fh.read()
            resp = model.generate_content(
                [_PROMPT, {"mime_type": "image/jpeg", "data": image_bytes}]
            )
            return resp.text or ""

        raw_text = await asyncio.to_thread(_blocking_ocr)
        parsed = _parse_gemini_text(raw_text)

        merchant = parsed.get("merchant")
        total = _coerce_number(parsed.get("total"))
        ocr_date = parsed.get("date")

        db.update_ocr_job(
            job_id,
            status="done",
            raw_response=parsed,
            merchant=merchant,
            total=total,
            date=ocr_date,
        )
        db.update_expense_ocr(attachment_id, merchant, total, ocr_date)
        logger.info("OCR done for attachment %s (job %s)", attachment_id, job_id)
    except Exception as exc:
        logger.exception("OCR failed for attachment %s", attachment_id)
        try:
            db.update_ocr_job(job_id, status="failed", error=str(exc))
        except Exception:
            logger.exception("Failed to mark OCR job %s as failed", job_id)
