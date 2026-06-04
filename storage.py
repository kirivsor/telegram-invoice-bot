"""File-storage helper for uploaded receipt/invoice images.

All images live under the Railway Volume mount (/app/data). This module
owns every path decision and every disk touch so handlers never build
paths by hand. Image cleaning is best-effort: any failure returns None
and the caller falls back to the original — ingestion must never break
because OpenCV had a bad day.
"""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

# Root mount path is configurable so the same code runs locally and on
# Railway. Defaults to the documented Railway Volume mount.
DATA_ROOT = os.environ.get("DATA_ROOT", "/app/data")
RECEIPTS_DIR = os.path.join(DATA_ROOT, "uploads", "receipts")
ORIGINAL_DIR = os.path.join(RECEIPTS_DIR, "original")
CLEANED_DIR = os.path.join(RECEIPTS_DIR, "cleaned")


def ensure_dirs() -> None:
    """Create the upload directory tree if absent. Called once at startup."""
    for path in (ORIGINAL_DIR, CLEANED_DIR):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            logger.exception("Failed to create storage directory: %s", path)


def save_telegram_photo(
    file_bytes: bytes, user_id: int, file_unique_id: str
) -> tuple[str, str]:
    """Persist raw photo bytes to the originals dir.

    Filename is <user_id>_<timestamp>_<file_unique_id>.jpg. file_unique_id
    is Telegram-issued (opaque, no path separators) but we still sanitize
    it defensively so it can never escape the directory.
    Returns (original_path, filename).
    """
    ensure_dirs()
    safe_uid = "".join(c for c in str(file_unique_id) if c.isalnum() or c in "-_")
    filename = f"{int(user_id)}_{int(time.time())}_{safe_uid}.jpg"
    original_path = os.path.join(ORIGINAL_DIR, filename)
    with open(original_path, "wb") as fh:
        fh.write(file_bytes)
    return original_path, filename


def clean_image(original_path: str) -> str | None:
    """Produce a cleaned copy for better OCR. Returns the cleaned path,
    or None on any failure (caller falls back to the original).

    Pipeline: grayscale -> CLAHE contrast -> Otsu threshold -> deskew.
    """
    try:
        import cv2  # imported lazily so a missing/broken OpenCV never
        import numpy as np  # crashes the bot at import time
    except Exception:
        logger.warning("OpenCV/numpy unavailable; skipping image cleaning.")
        return None

    try:
        img = cv2.imread(original_path)
        if img is None:
            logger.warning("clean_image: could not read %s", original_path)
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        _, thresh = cv2.threshold(
            gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Estimate skew from the dark (text) pixels and rotate if material.
        coords = np.column_stack(np.where(thresh < 128))
        if coords.size:
            angle = cv2.minAreaRect(coords)[-1]
            if angle < -45:
                angle = 90 + angle
            if abs(angle) > 0.5:
                h, w = thresh.shape[:2]
                m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
                thresh = cv2.warpAffine(
                    thresh, m, (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )

        filename = os.path.basename(original_path)
        cleaned_path = os.path.join(CLEANED_DIR, filename)
        os.makedirs(CLEANED_DIR, exist_ok=True)
        if not cv2.imwrite(cleaned_path, thresh):
            logger.warning("clean_image: imwrite failed for %s", cleaned_path)
            return None
        return cleaned_path
    except Exception:
        logger.exception("clean_image failed for %s", original_path)
        return None


def delete_files(original_path: str, cleaned_path: str | None) -> None:
    """Silently remove both files (used on expense cancel)."""
    for path in (original_path, cleaned_path):
        if not path:
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.exception("Failed to delete file: %s", path)
