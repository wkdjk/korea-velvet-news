import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from src.airtable.client import url_exists

_KO_STOP = {'은', '는', '이', '가', '을', '를', '의', '에', '로', '도', '와', '과', '및', '한', '그'}

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "referer",
}


def normalise_url(url: str) -> str:
    """Strip tracking params and normalise scheme/netloc."""
    parsed = urlparse(url)
    params = {k: v for k, v in parse_qs(parsed.query).items() if k not in _TRACKING_PARAMS}
    clean_query = urlencode({k: v[0] for k, v in params.items()})
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower().replace("www.", ""),
        parsed.path.rstrip("/"),
        "",
        clean_query,
        "",
    ))


def _title_tokens(title: str) -> frozenset:
    tokens = re.findall(r'[가-힣a-zA-Z0-9]{2,}', title)
    return frozenset(t for t in tokens if t not in _KO_STOP)


def cluster_by_title(articles: list[dict], threshold: float = 0.5) -> list[dict]:
    """Remove near-duplicate articles by title token overlap within the same publication date.
    Keeps the first occurrence; threshold is overlap ratio on the shorter title's tokens."""
    kept = []
    for article in articles:
        tokens = _title_tokens(article.get('title_ko', ''))
        pub_date = article.get('published_date', '')
        duplicate = False
        for prior in kept:
            if prior.get('published_date', '') != pub_date:
                continue
            prior_tokens = _title_tokens(prior.get('title_ko', ''))
            if not tokens or not prior_tokens:
                continue
            overlap = len(tokens & prior_tokens) / min(len(tokens), len(prior_tokens))
            if overlap >= threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(article)
    return kept


def deduplicate(articles: list[dict]) -> list[dict]:
    """
    Remove articles whose normalised URL already exists in Airtable or appeared
    earlier in this batch. Mutates each article's 'url' field to the normalised form.
    """
    seen = set()
    unique = []
    for article in articles:
        norm = normalise_url(article["url"])
        if norm in seen:
            continue
        seen.add(norm)
        if url_exists(norm):
            continue
        article["url"] = norm
        unique.append(article)
    return unique
