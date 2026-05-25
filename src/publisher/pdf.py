"""
pdf.py — Generate a monthly PDF from the archive page and log it to the Reports sheet.

Called once per month, on the 1st, during the build pipeline.
Workflow:
  1. Write the archive HTML to a temp file.
  2. Use Playwright headless browser to convert HTML → PDF.
  3. Save PDF to data/pdfs/ in the repo.
  4. Create a row in the Reports sheet (Google Sheets via src.airtable.client).

Requires: playwright (pip install playwright && playwright install chromium)
"""

import tempfile
from datetime import date
from pathlib import Path

from src.airtable.client import create_record


_PDF_DIR = Path(__file__).parent.parent.parent / "data" / "pdfs"


def generate_monthly_pdf(archive_html: str, month: str, article_count: int) -> bool:
    """Convert archive_html string to PDF and log to Reports sheet.

    Args:
        archive_html:   Fully rendered HTML of the archive page for this month.
        month:          'YYYY-MM' string (e.g. '2026-05').
        article_count:  Number of articles in this month.

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

    # Save PDF locally to data/pdfs/
    try:
        _PDF_DIR.mkdir(parents=True, exist_ok=True)
        pdf_path = _PDF_DIR / filename
        pdf_path.write_bytes(pdf_bytes)
        print(f"  PDF saved: {pdf_path}")
    except Exception as e:
        print(f"  PDF: save error: {e}")
        # Non-fatal — continue to log to Sheets

    # Create Reports row in Google Sheets
    try:
        create_record("Reports", {
            "month": month,
            "article_count": article_count,
            "status": "pending_send",
        })
        print(f"  Reports row created for {month} ({article_count} articles).")
    except Exception as e:
        print(f"  PDF: Reports row creation failed: {e}")
        return False

    return True
