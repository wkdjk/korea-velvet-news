import trafilatura

_MIN_BODY_LEN = 100
_DESCRIPTION_MIN_LEN = 50


def _fetch_with_trafilatura(url: str) -> str | None:
    """Attempt to extract body text using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False)
        return text if text and len(text) >= _MIN_BODY_LEN else None
    except Exception:
        return None


def _fetch_with_newspaper(url: str) -> tuple[str | None, str]:
    """Fallback: attempt extraction using newspaper3k.

    Returns (body_text_or_None, image_url_or_empty_string).
    """
    try:
        from newspaper import Article
        article = Article(url, language="ko")
        article.download()
        article.parse()
        text = article.text.strip()
        image_url = article.top_image or ""
        body = text if len(text) >= _MIN_BODY_LEN else None
        return body, image_url
    except Exception:
        return None, ""


def _fetch_image_only(url: str) -> str:
    """Fetch top image URL using newspaper3k without requiring a usable body.

    Used when trafilatura already succeeded for body extraction but we still
    want to attempt image discovery.  Returns empty string on any failure.
    """
    try:
        from newspaper import Article
        article = Article(url, language="ko")
        article.download()
        article.parse()
        return article.top_image or ""
    except Exception:
        return ""


def extract_body(url: str, naver_description: str = "") -> tuple[str | None, str, str]:
    """Extract article body text and top image URL from a URL.

    Returns (body_text, method, image_url) where:
      - body_text : extracted text, or None on failure
      - method    : 'trafilatura' | 'newspaper' | 'naver_description' | 'failed'
      - image_url : top image URL string, or '' if none found

    Fallback chain:
    1. trafilatura (body) + newspaper3k (image)
    2. newspaper3k (body + image)
    3. Naver API description (body, no image)
    4. None / failed
    """
    text = _fetch_with_trafilatura(url)
    if text:
        # Body resolved via trafilatura; still try newspaper for the image.
        image_url = _fetch_image_only(url)
        return text, "trafilatura", image_url

    body, image_url = _fetch_with_newspaper(url)
    if body:
        return body, "newspaper", image_url

    if naver_description and len(naver_description) >= _DESCRIPTION_MIN_LEN:
        return naver_description, "naver_description", image_url

    return None, "failed", image_url
