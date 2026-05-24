import trafilatura
import requests

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


def _fetch_with_newspaper(url: str) -> str | None:
    """Fallback: attempt extraction using newspaper3k."""
    try:
        from newspaper import Article
        article = Article(url, language="ko")
        article.download()
        article.parse()
        text = article.text.strip()
        return text if len(text) >= _MIN_BODY_LEN else None
    except Exception:
        return None


def extract_body(url: str, naver_description: str = "") -> tuple[str | None, str]:
    """
    Extract article body text from a URL.

    Returns (body_text, method) where method is one of:
    'trafilatura', 'newspaper', 'naver_description', 'failed'

    Fallback chain:
    1. trafilatura
    2. newspaper3k
    3. Naver API description (if >= DESCRIPTION_MIN_LEN chars)
    4. None (extract_failed)
    """
    text = _fetch_with_trafilatura(url)
    if text:
        return text, "trafilatura"

    text = _fetch_with_newspaper(url)
    if text:
        return text, "newspaper"

    if naver_description and len(naver_description) >= _DESCRIPTION_MIN_LEN:
        return naver_description, "naver_description"

    return None, "failed"
