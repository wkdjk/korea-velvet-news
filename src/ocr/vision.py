"""
vision.py — Extract articles from a Korean newspaper photo using Claude Vision.

Downloads the image from a URL (e.g. a form attachment URL), encodes it as base64,
and calls Claude Sonnet Vision with the OCR splitter system prompt.

Returns a list of {title_ko, body_ko, photo_quality} dicts, one per article.
Returns an empty list on download failure, API error, or unreadable image.
"""

import base64
import json
import os
import re
from pathlib import Path

import anthropic
import requests

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096
_OCR_MIN_BODY_LEN = 50
_DOWNLOAD_TIMEOUT = 30


def _load_system_prompt() -> str:
    return (_PROMPTS_DIR / "ocr_splitter_system.md").read_text(encoding="utf-8")


def _media_type(url: str, content_type: str) -> str:
    ct = content_type.lower()
    for mime, key in [("image/png", "png"), ("image/gif", "gif"), ("image/webp", "webp")]:
        if key in ct or url.lower().endswith(f".{key}"):
            return mime
    return "image/jpeg"


def ocr_image(image_url: str) -> list[dict]:
    """Download image_url and extract articles using Claude Vision.

    Returns list of {title_ko, body_ko, photo_quality}.
    Returns [] on any failure or if image is unreadable.
    """
    try:
        resp = requests.get(image_url, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        image_b64 = base64.standard_b64encode(resp.content).decode("utf-8")
        media_type = _media_type(image_url, resp.headers.get("content-type", ""))
    except Exception as e:
        print(f"  OCR download failed ({image_url[:60]}): {e}")
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=_load_system_prompt(),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract all news articles from this newspaper photo.",
                        },
                    ],
                }
            ],
        )
    except Exception as e:
        print(f"  OCR API error: {e}")
        return []

    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw).strip()

    try:
        articles = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  OCR JSON parse error: {e} | raw[:200]: {raw[:200]}")
        return []

    if not isinstance(articles, list):
        return []

    return [
        a for a in articles
        if isinstance(a, dict) and len(a.get("body_ko", "")) >= _OCR_MIN_BODY_LEN
    ]
