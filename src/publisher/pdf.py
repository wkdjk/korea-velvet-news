"""
pdf.py — Generate a monthly PDF from the archive page and log it to Airtable Reports.

Called once per month, on the 1st, during the build pipeline.
Workflow:
  1. Write the archive HTML to a temp file
  2. Use Playwright headless browser to convert HTML → PDF
  3. Upload PDF to Airtable Reports table as an attachment
  4. Set status=pending_send → Airtable Automation sends the email

Requires: playwright (pip install playwright && playwright install chromium)
"""

import os
import tempfile
from datetime import date
from pathlib import Path

import requests

from src.airtable.client import create_record, update_record


def _upload_attachment(record_id: str, field: str, filename: str, pdf_bytes: bytes) -> str:
    """Upload pdf_bytes as an attachment to an Airtable record field.

    Returns the public URL of the uploaded file, or '' on failure.
    """
    token = os.environ["AIRTABLE_TOKEN"]
    base_id = os.environ["AIRTABLE_BASE_ID"]
    url = f"https://content.airtable.com/v0/{base_id}/{record_id}/{field}/uploadAttachment"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"contentType": "application/pdf", "filename": filename, "file": None},
    )
    # Airtable attachment upload requires multipart; use the standard REST approach
    upload_url = f"https://api.airtable.com/v0/{base_id}/Reports/{record_id}"
    patch_resp = requests.patch(
        upload_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={
            "fields": {
                field: [{"url": f"data:application/pdf;base64,{_b64(pdf_bytes)}", "filename": filename}]
            }
        },
    )
    if patch_resp.ok:
        attachments = patch_resp.json().get("fields", {}).get(field, [])
        if attachments:
            return attachments[0].get("url", "")
    return ""


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("utf-8")


def generate_monthly_pdf(archive_html: str, month: str, article_count: int) -> bool:
    """Convert archive_html string to PDF and log to Airtable Reports.

    Args:
        archive_html: fully rendered HTML of the archive page for this month
        month: 'YYYY-MM' string (e.g. '2026-05')
        article_count: number of articles in this month

    Returns True on success, False on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  PDF: playwright not installed — skipping PDF generation")
        return False

    filename = f"korea-velvet-news-{month}.pdf"

    # Write HTML to a temp file so Playwright can load it
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as f:
        f.write(archive_html)
        tmp_path = f.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file://{tmp_path}")
            page.wait_for_load_state("networkidle")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "18mm", "bottom": "18mm", "left": "20mm", "right": "20mm"},
            )
            browser.close()
    except Exception as e:
        print(f"  PDF: Playwright error: {e}")
        return False
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    print(f"  PDF generated: {len(pdf_bytes):,} bytes")

    # Create Reports row (status=pending_send triggers Airtable Automation email)
    try:
        record = create_record("Reports", {
            "month": month,
            "article_count": article_count,
            "status": "pending_send",
        })
        record_id = record["id"]
    except Exception as e:
        print(f"  PDF: Airtable Reports row creation failed: {e}")
        return False

    # Upload PDF as attachment via direct Airtable REST patch
    token = os.environ["AIRTABLE_TOKEN"]
    base_id = os.environ["AIRTABLE_BASE_ID"]
    patch_url = f"https://api.airtable.com/v0/{base_id}/Reports/{record_id}"

    try:
        resp = requests.patch(
            patch_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "fields": {
                    "pdf_file": [
                        {
                            "url": f"data:application/pdf;base64,{_b64(pdf_bytes)}",
                            "filename": filename,
                        }
                    ]
                }
            },
        )
        resp.raise_for_status()
        attachments = resp.json().get("fields", {}).get("pdf_file", [])
        public_url = attachments[0].get("url", "") if attachments else ""
        if public_url:
            update_record("Reports", record_id, {"pdf_public_url": public_url})
            print(f"  PDF uploaded to Airtable Reports: {record_id}")
        else:
            print("  PDF: attachment uploaded but public URL not returned")
    except Exception as e:
        print(f"  PDF: attachment upload failed: {e}")
        return False

    return True
