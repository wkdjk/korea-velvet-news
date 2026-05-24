"""
google_alerts.py — Collect articles from Google Alerts RSS feeds.

Reads a comma-separated list of RSS URLs from the GOOGLE_ALERTS_RSS_URLS
environment variable (set as a GitHub Secret). Each URL is a Google Alerts
RSS feed for a specific keyword.

Returns articles in the same format as naver.py and google_news.py so they
can be passed through the same dedup and classification pipeline.
"""

import os
import re
from datetime import datetime
from urllib.parse import urlparse

import feedparser

_HTML_TAG = re.compile(r'<[^>]+>')


def _clean(text: str) -> str:
    return _HTML_TAG.sub('', text).strip()


def _parse_date(entry) -> str:
    if getattr(entry, 'published_parsed', None):
        return datetime(*entry.published_parsed[:3]).strftime('%Y-%m-%d')
    return ''


def _source_from_url(url: str) -> str:
    netloc = urlparse(url).netloc.replace('www.', '')
    return netloc or 'Google Alerts'


def search_google_alerts() -> list[dict]:
    """Fetch articles from all Google Alerts RSS feeds in GOOGLE_ALERTS_RSS_URLS.

    Returns list of article dicts compatible with the collect pipeline.
    Returns empty list if the env var is not set (allows pipeline to run
    without this source configured).
    """
    raw_urls = os.environ.get('GOOGLE_ALERTS_RSS_URLS', '').strip()
    if not raw_urls:
        return []

    rss_urls = [u.strip() for u in raw_urls.split(',') if u.strip()]
    results = []

    for rss_url in rss_urls:
        try:
            feed = feedparser.parse(rss_url)
            for entry in feed.entries:
                link = entry.get('link', '')
                title = _clean(entry.get('title', ''))
                summary = _clean(entry.get('summary', ''))
                results.append({
                    'url': link,
                    'title_ko': title,
                    'description': summary,
                    'published_date': _parse_date(entry),
                    'source_name': _source_from_url(link),
                    'source_type': 'auto',
                })
        except Exception as e:
            print(f"  Google Alerts RSS error ({rss_url[:60]}...): {e}")

    return results
