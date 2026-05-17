"""
splitter.py — Public entry point for the OCR pipeline.

Called by form_processor/process.py when a submitted article has source_type='photo'.
Delegates to vision.py for the actual Claude Vision call.
"""

from src.ocr.vision import ocr_image

__all__ = ["split_newspaper_photo"]


def split_newspaper_photo(image_url: str) -> list[dict]:
    """Extract all news articles from a newspaper photo at image_url.

    Returns list of {title_ko, body_ko, photo_quality} dicts.
    Returns [] if the image is unreadable or the call fails.
    """
    return ocr_image(image_url)
