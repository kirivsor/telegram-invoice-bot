"""Download DejaVuSans.ttf and DejaVuSans-Bold.ttf into assets/.

Run once after cloning the repo:

    python download_fonts.py

Idempotent — skips files that already exist. Uses only the Python
standard library, so no extra requirements.txt entries.

If this script fails (e.g. no network, GitHub down), the bot still
runs — pdf_generator.py falls back to Helvetica. Cyrillic characters
in PDFs simply won't render until the fonts are present.
"""

from __future__ import annotations

import io
import logging
import sys
import tarfile
import urllib.request
from pathlib import Path

logging.basicConfig(
    format="%(asctime)s \u2014 %(levelname)s \u2014 %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("download_fonts")

ASSETS_DIR = Path(__file__).parent / "assets"

# Official DejaVu Fonts release. Bz2 tarball, ~2.5 MB.
RELEASE_URL = (
    "https://github.com/dejavu-fonts/dejavu-fonts/releases/download/"
    "version_2_37/dejavu-fonts-ttf-2.37.tar.bz2"
)

# Files we want from inside the tarball -> destination filenames.
WANTED = {
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans.ttf": "DejaVuSans.ttf",
    "dejavu-fonts-ttf-2.37/ttf/DejaVuSans-Bold.ttf": "DejaVuSans-Bold.ttf",
}


def _already_have_all() -> bool:
    return all((ASSETS_DIR / name).exists() for name in WANTED.values())


def main() -> int:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    if _already_have_all():
        logger.info("All DejaVu font files already present in %s. Nothing to do.", ASSETS_DIR)
        return 0

    logger.info("Downloading DejaVu fonts release from %s ...", RELEASE_URL)
    try:
        with urllib.request.urlopen(RELEASE_URL, timeout=60) as resp:
            archive_bytes = resp.read()
    except Exception:
        logger.exception(
            "Failed to download the DejaVu tarball. "
            "Bot will still run, but Cyrillic characters in PDFs will not render."
        )
        return 1

    logger.info("Downloaded %d bytes. Extracting required TTFs ...", len(archive_bytes))
    extracted = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:bz2") as tar:
            for member_name, dest_name in WANTED.items():
                try:
                    member = tar.getmember(member_name)
                except KeyError:
                    logger.error("Expected member missing from tarball: %s", member_name)
                    continue
                src = tar.extractfile(member)
                if src is None:
                    logger.error("Could not open %s inside tarball.", member_name)
                    continue
                dest = ASSETS_DIR / dest_name
                with dest.open("wb") as out:
                    out.write(src.read())
                logger.info("Wrote %s (%d bytes).", dest, dest.stat().st_size)
                extracted += 1
    except Exception:
        logger.exception("Failed to extract the tarball.")
        return 1

    if extracted == len(WANTED):
        logger.info("All DejaVu fonts installed into %s. You can now generate PDFs with Cyrillic content.", ASSETS_DIR)
        return 0

    logger.warning("Extracted %d of %d expected font files. PDF rendering may be incomplete.", extracted, len(WANTED))
    return 1


if __name__ == "__main__":
    sys.exit(main())
