"""
build.py — Daily build pipeline

Steps:
  1. Process submitted form articles (URL / photo / text)
  2. Translate approved articles (status=approved → translated)
  3. Generate HTML main page
  4. On the 1st of the month: generate archive for previous month + PDF + Reports row
  5. Deploy to gh-pages
  6. Mark translated articles as published in Airtable

Triggered by build.yml daily at KST 07:00 and workflow_dispatch.
"""

from datetime import date, timedelta
from dotenv import load_dotenv
load_dotenv()

from src.airtable.client import get_records, batch_update_records
from src.form_processor.process import process_submitted_urls
from src.publisher.deploy import deploy
from src.publisher.generate import generate_archive_html, generate_html
from src.publisher.pdf import generate_monthly_pdf
from src.translator.translator import translate_article


def _previous_month_key(today: date) -> str:
    """Return 'YYYY-MM' for the month before today."""
    first_of_this_month = today.replace(day=1)
    last_of_prev = first_of_this_month - timedelta(days=1)
    return last_of_prev.strftime("%Y-%m")


def run():
    today = date.today()
    is_first_of_month = today.day == 1

    # Step 1: Process submitted form articles (URL / photo / text)
    process_submitted_urls()

    # Step 2: Translate approved articles
    approved = get_records(
        "Articles",
        filter_formula="{status}='approved'",
        fields=["url", "title_ko", "body_ko"],
    )
    print(f"Translating {len(approved)} approved articles...")
    translate_updates = []
    for record in approved:
        f = record["fields"]
        result = translate_article({
            "id": record["id"],
            "title_ko": f.get("title_ko", ""),
            "body_ko": f.get("body_ko", ""),
        })
        if result.get("status") == "translate_failed":
            translate_updates.append({"id": record["id"], "fields": {"status": "translate_failed"}})
            print(f"  Translate failed: {record['id']}")
        else:
            translate_updates.append({
                "id": record["id"],
                "fields": {
                    "title_en": result["title_en"],
                    "body_en": result["body_en"],
                    "status": "translated",
                },
            })
            print(f"  Translated: {record['id']}")

    if translate_updates:
        batch_update_records("Articles", translate_updates)

    # Step 3: Generate current month's main page
    generate_html()

    # Step 4: On the 1st — archive previous month + generate PDF
    if is_first_of_month:
        prev_month = _previous_month_key(today)
        print(f"1st of month: archiving {prev_month}...")

        archive_path, archived_articles = generate_archive_html(prev_month)
        archive_html = archive_path.read_text(encoding="utf-8")

        pdf_ok = generate_monthly_pdf(
            archive_html=archive_html,
            month=prev_month,
            article_count=len(archived_articles),
        )
        if pdf_ok:
            print(f"  Archive + PDF complete for {prev_month}.")
        else:
            print(f"  Archive generated but PDF failed for {prev_month}.")
    else:
        print(f"Not 1st of month (today={today}) — skipping archive/PDF step.")

    # Step 5: Deploy to gh-pages
    deploy()

    # Step 6: Mark translated articles as published
    translated = get_records(
        "Articles",
        filter_formula="{status}='translated'",
        fields=["url"],
    )
    if translated:
        publish_updates = [{"id": r["id"], "fields": {"status": "published"}} for r in translated]
        batch_update_records("Articles", publish_updates)
        print(f"Marked {len(translated)} articles as published.")

    print("Build complete.")


if __name__ == "__main__":
    run()
