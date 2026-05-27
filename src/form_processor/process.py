"""
process.py — Handle articles submitted via the Airtable form.

Phase B: supports three input types set by the submitter via input_type field:
  - url    → extract body text from URL (Phase A behaviour)
  - photo  → OCR via Claude Vision → may produce multiple articles
  - text   → direct text, no extraction needed

All form submissions skip classification and go straight to pending_review.
"""

from src.airtable.client import create_record, get_records, batch_update_records
from src.extractor.crawl import extract_body
from src.ocr.splitter import split_newspaper_photo


def process_submitted_urls():
    """Process all articles with status='submitted'."""
    submitted = get_records(
        "Articles",
        filter_formula="{status}='submitted'",
        fields=["url", "title_ko", "input_type", "photo_attachment", "direct_text"],
    )
    if not submitted:
        return

    print(f"Processing {len(submitted)} submitted articles...")
    updates = []

    for record in submitted:
        f = record["fields"]
        input_type = f.get("input_type", "url") or "url"

        if input_type == "text":
            _process_text(record, f, updates)
        elif input_type == "photo":
            _process_photo(record, f, updates)
        else:
            _process_url(record, f, updates)

    if updates:
        batch_update_records("Articles", updates)
    print("Form processing complete.")


def _process_url(record: dict, fields: dict, updates: list) -> None:
    url = fields.get("url", "")
    if not url:
        updates.append({"id": record["id"], "fields": {"status": "extract_failed"}})
        return

    body, method, image_url = extract_body(url)
    if body:
        fields_to_update = {
            "body_ko": body,
            "source_type": "form",
            "status": "pending_review",
        }
        if image_url:
            fields_to_update["image_url"] = image_url
        updates.append({
            "id": record["id"],
            "fields": fields_to_update,
        })
        print(f"  URL extracted ({method}): {record['id']}")
    else:
        updates.append({"id": record["id"], "fields": {"status": "extract_failed"}})
        print(f"  URL extract failed: {record['id']}")


def _process_text(record: dict, fields: dict, updates: list) -> None:
    body = (fields.get("direct_text") or "").strip()
    if not body:
        updates.append({"id": record["id"], "fields": {"status": "extract_failed"}})
        print(f"  Text empty: {record['id']}")
        return

    updates.append({
        "id": record["id"],
        "fields": {
            "body_ko": body,
            "source_type": "form",
            "status": "pending_review",
        },
    })
    print(f"  Text accepted: {record['id']}")


def _process_photo(record: dict, fields: dict, updates: list) -> None:
    attachments = fields.get("photo_attachment") or []
    if not attachments:
        updates.append({"id": record["id"], "fields": {"status": "ocr_failed"}})
        print(f"  No photo attachment: {record['id']}")
        return

    image_url = attachments[0].get("url", "")
    articles = split_newspaper_photo(image_url)

    if not articles:
        updates.append({"id": record["id"], "fields": {"status": "ocr_failed"}})
        print(f"  OCR failed: {record['id']}")
        return

    # First article updates the original record
    first = articles[0]
    updates.append({
        "id": record["id"],
        "fields": {
            "title_ko": first.get("title_ko", fields.get("title_ko", "")),
            "body_ko": first["body_ko"],
            "source_type": "form",
            "status": "pending_review",
        },
    })
    print(f"  OCR article 1/{len(articles)}: {record['id']}")

    # Additional articles create new records
    for i, article in enumerate(articles[1:], start=2):
        create_record("Articles", {
            "title_ko": article.get("title_ko", ""),
            "body_ko": article["body_ko"],
            "source_type": "form",
            "status": "pending_review",
            "published_date": fields.get("published_date", ""),
            "source_name": fields.get("source_name", ""),
        })
        print(f"  OCR article {i}/{len(articles)}: new record created")
