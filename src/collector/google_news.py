import re
from datetime import datetime
from urllib.parse import quote_plus, urlparse

import feedparser

_RSS_URL = "https://news.google.com/rss/search?q={q}&hl=ko&gl=KR&ceid=KR:ko"


def _parse_date(entry) -> str:
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:3]).strftime("%Y-%m-%d")
    return ""


def search_google_news(keyword: str) -> list[dict]:
    """Search Google News RSS for a keyword. Returns list of article dicts.

    Note: Google News links may go through a Google redirect URL.
    The extractor (crawl.py) follows redirects when fetching body text.
    """
    url = _RSS_URL.format(q=quote_plus(keyword))
    feed = feedparser.parse(url)

    results = []
    for entry in feed.entries:
        link = entry.get("link", "")
        source_title = entry.get("source", {}).get("title", "")
        if not source_title:
            source_title = urlparse(link).netloc.replace("www.", "")
        results.append({
            "url": link,
            "title_ko": entry.get("title", ""),
            "description": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
            "published_date": _parse_date(entry),
            "source_name": source_title,
            "source_type": "auto",
        })
    return results
