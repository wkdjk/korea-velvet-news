import os
import re
from datetime import datetime
from urllib.parse import urlparse

import requests

_API_URL = "https://openapi.naver.com/v1/search/news.json"
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'"}


def _clean(text: str) -> str:
    text = _HTML_TAG.sub("", text)
    for entity, char in _HTML_ENTITIES.items():
        text = text.replace(entity, char)
    return text.strip()


def _parse_date(pub_date: str) -> str:
    try:
        dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return ""


def search_naver(keyword: str, display: int = 100) -> list[dict]:
    """Search Naver News API for a keyword. Returns list of article dicts."""
    headers = {
        "X-Naver-Client-Id": os.environ["NAVER_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_CLIENT_SECRET"],
    }
    params = {"query": keyword, "display": min(display, 100), "sort": "date"}
    resp = requests.get(_API_URL, headers=headers, params=params, timeout=10)
    resp.raise_for_status()

    results = []
    for item in resp.json().get("items", []):
        url = item.get("originallink") or item.get("link", "")
        netloc = urlparse(url).netloc.replace("www.", "")
        results.append({
            "url": url,
            "title_ko": _clean(item.get("title", "")),
            "description": _clean(item.get("description", "")),
            "published_date": _parse_date(item.get("pubDate", "")),
            "source_name": netloc,
            "source_type": "auto",
        })
    return results
