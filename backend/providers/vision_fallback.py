"""VisionFallback — screenshot + OCR fallback for response extraction.

When DOM-based extraction fails (e.g. the AI response is rendered in
a canvas, or the selectors are stale), this adapter takes a screenshot
of the response area and runs OCR to extract the text.

Dependencies:
    - ``pytesseract`` (Tesseract OCR Python wrapper)
    - ``Pillow`` (image processing)

These are optional — if not installed, ``VisionFallback`` raises
``ImportError`` on first use.

Usage::

    fallback = VisionFallback()
    text = await fallback.extract_from_screenshot(page, region=(0, 300, 1280, 900))
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy imports — these are optional dependencies
_tesseract_available: bool | None = None
_pil_available: bool | None = None


def _check_tesseract() -> bool:
    global _tesseract_available
    if _tesseract_available is None:
        import importlib.util
        _tesseract_available = importlib.util.find_spec("pytesseract") is not None
    return _tesseract_available


def _check_pil() -> bool:
    global _pil_available
    if _pil_available is None:
        import importlib.util
        _pil_available = importlib.util.find_spec("PIL") is not None
    return _pil_available


class VisionFallback:
    """Screenshot + OCR fallback for response extraction.

    This is a last resort — used only when all DOM selectors fail.
    """

    async def extract_from_screenshot(
        self,
        page: Any,
        region: tuple[int, int, int, int] | None = None,
        language: str = "eng+chi_sim",
    ) -> str:
        """Take a screenshot and extract text via OCR.

        Args:
            page: Playwright Page.
            region: Optional (x, y, width, height) to crop.
            language: Tesseract language codes.

        Returns:
            Extracted text, or empty string if OCR fails.
        """
        if not _check_tesseract():
            logger.warning("VisionFallback: pytesseract not installed")
            return ""
        if not _check_pil():
            logger.warning("VisionFallback: Pillow not installed")
            return ""

        try:
            import pytesseract
            from PIL import Image

            # Take screenshot
            screenshot_bytes = await page.screenshot()
            img = Image.open(io.BytesIO(screenshot_bytes))

            # Crop if region specified
            if region:
                x, y, w, h = region
                img = img.crop((x, y, x + w, y + h))

            # Run OCR in a thread to avoid blocking
            text = await asyncio.to_thread(
                pytesseract.image_to_string, img, lang=language
            )

            return text.strip()

        except Exception as exc:
            logger.warning("VisionFallback: OCR failed: %s", exc)
            return ""

    async def extract_response_region(
        self,
        page: Any,
        response_selector: str = '[data-message-author-role="assistant"]',
    ) -> str:
        """Try to screenshot just the response region and OCR it.

        Falls back to full-page screenshot if the selector isn't found.
        """
        try:
            # Try to find the response element
            element = page.locator(response_selector).last
            if await element.is_visible(timeout=2000):
                # Screenshot just the element
                screenshot_bytes = await element.screenshot()
                if not _check_tesseract() or not _check_pil():
                    return ""
                import pytesseract
                from PIL import Image

                img = Image.open(io.BytesIO(screenshot_bytes))
                text = await asyncio.to_thread(
                    pytesseract.image_to_string, img, lang="eng+chi_sim"
                )
                return text.strip()
        except Exception:
            pass

        # Fallback: full page
        return await self.extract_from_screenshot(page)
