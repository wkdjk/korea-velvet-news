"""
collect.py — Phase A collection pipeline

Steps:
  1. Load active keywords from Google Sheets Keywords tab
  2. Search Naver + Google News for each keyword
  3. Normalise and deduplicate against existing Google Sheets records
  4. Create new articles in Google Sheets (status=collected)
  5. Extract body text for each new article (trafilatura → newspaper → Naver description fallback)
  6. Classify extracted articles in batches (Haiku)
  7. Update Google Sheets: status=classified or extract_failed

Triggered by collect.yml on Mon/Wed/Fri KST 07:00 and workflow_dispatch.
"""

import os
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()

from src.airtable.client import batch_create_records, create_record, update_record, batch_update_records
from src.classifier.classifier import classify_articles
from src.collector.dedup import cluster_by_title, deduplicate
from src.collector.google_alerts import search_google_alerts
from src.collector.google_news import search_google_news
from src.collector.naver import search_naver
from src.extractor.crawl import extract_body

# Only accept articles published within this many days.
# Prevents the first run from pulling years of back-history.
# Override via COLLECT_MAX_DAYS env var.
_MAX_DAYS = int(os.environ.get("COLLECT_MAX_DAYS", "14"))


def _is_recent(article: dict) -> bool:
    """Return True if article was published within _MAX_DAYS days.

    Articles with no date or an unparseable date are rejected (return False)
    to prevent undated or malformed RSS entries from bypassing the cutoff.
    """
    pub = article.get("published_date", "")
    if not pub:
        return False  # unknown date: reject rather than allow through
    try:
        cutoff = date.today() - timedelta(days=_MAX_DAYS)
        return date.fromisoformat(pub) >= cutoff
    except ValueError:
        return False  # unparseable date: reject


def run():
    from src.airtable.client import get_active_keywords
    keywords = get_active_keywords()
    if not keywords:
        print("No active keywords found. Exiting.")
        return

    print(f"Keywords: {keywords}")
    print(f"Date filter: last {_MAX_DAYS} days (cutoff {date.today() - timedelta(days=_MAX_DAYS)})")

    # Collect from Naver + Google News (30 results per keyword per source)
    raw_articles = []
    for kw in keywords:
        print(f"  Naver: {kw}")
        raw_articles.extend(search_naver(kw, display=30))
        print(f"  Google News: {kw}")
        raw_articles.extend(search_google_news(kw))

    # Collect from Google Alerts RSS feeds (keyword-independent, no loop)
    print("  Google Alerts RSS...")
    raw_articles.extend(search_google_alerts())

    print(f"Raw results: {len(raw_articles)}")

    # Filter by date before dedup to avoid Google Sheets quota waste
    raw_articles = [a for a in raw_articles if _is_recent(a)]
    print(f"After date filter ({_MAX_DAYS}d): {len(raw_articles)}")

    # Deduplicate against Google Sheets and within batch
    new_articles = deduplicate(raw_articles)
    print(f"New after dedup: {len(new_articles)}")

    # Remove same-day same-event duplicates by title similarity
    new_articles = cluster_by_title(new_articles)
    print(f"After title clustering: {len(new_articles)}")

    if not new_articles:
        print("No new articles. Done.")
        return

    # Create records in Sheets (status=collected) — single batch API call
    fields_list = [
        {
            "url": article["url"],
            "title_ko": article.get("title_ko", ""),
            "source_name": article.get("source_name", ""),
            "published_date": article.get("published_date") or str(date.today()),
            "source_type": "auto",
            "status": "collected",
        }
        for article in new_articles
    ]
    records = batch_create_records("Articles", fields_list)
    created = [
        {
            "id": rec["id"],
            "url": art["url"],
            "title_ko": art.get("title_ko", ""),
            "description": art.get("description", ""),
        }
        for rec, art in zip(records, new_articles)
    ]
    print(f"Created in Sheets: {len(created)}")

    # Extract body text and top image URL
    extractable = []
    extract_updates = []
    for article in created:
        body, method, image_url = extract_body(article["url"], article.get("description", ""))
        if body:
            fields: dict = {"body_ko": body, "status": "extracted"}
            if image_url:
                fields["image_url"] = image_url
            extract_updates.append({"id": article["id"], "fields": fields})
            extractable.append({**article, "body_ko": body})
            img_note = f", image={'yes' if image_url else 'no'}"
            print(f"  Extracted ({method}{img_note}): {article['id']}")
        else:
            extract_updates.append({"id": article["id"], "fields": {"status": "extract_failed"}})
            print(f"  Extract failed: {article['id']}")

    if extract_updates:
        batch_update_records("Articles", extract_updates)

    if not extractable:
        print("No extractable articles for classification. Done.")
        return

    # Classify
    print(f"Classifying {len(extractable)} articles...")
    classifications = classify_articles(extractable)

    classify_updates = []
    for cls in classifications:
        score = cls.get("relevance_score", 3)
        # Phase B: score >= 4 queued for review; score <= 3 auto-excluded
        status = "pending_review" if score >= 4 else "auto_excluded"
        fields = {
            "relevance_score": score,
            "recommendation": cls.get("recommendation", ""),
            "tags_internal": cls.get("tags_internal", []),
            "status": status,
        }
        if cls.get("cluster_id"):
            fields["cluster_id"] = cls["cluster_id"]
        if "is_cluster_rep" in cls:
            fields["is_cluster_rep"] = bool(cls["is_cluster_rep"])
        classify_updates.append({"id": cls["id"], "fields": fields})

    if classify_updates:
        batch_update_records("Articles", classify_updates)

    print(f"Collection complete. {len(classify_updates)} articles queued for review.")


if __name__ == "__main__":
    run()
