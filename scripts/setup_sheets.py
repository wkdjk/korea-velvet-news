"""
scripts/setup_sheets.py — One-time KVN Google Sheets setup.

Creates "KVN Master Data" spreadsheet, sets up 4 tabs with correct headers,
imports Keywords and Glossary from Airtable CSV exports, and prints the
Sheets ID to register as GitHub Secret KVN_SHEETS_ID.

Usage:
    GOOGLE_SERVICE_ACCOUNT_JSON='...' \\
    python scripts/setup_sheets.py \\
        --keywords-csv ~/Downloads/Keywords-Grid\\ view.csv \\
        --glossary-csv ~/Downloads/Glossary-Grid\\ view.csv

Optional flags:
    --sheets-id XXXX   Open existing sheet instead of creating a new one.
    --articles-csv     Also import published articles from Airtable export.
    --share-email      Extra email to grant editor access (default: seouldesk.help@gmail.com).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERROR] gspread or google-auth not installed.")
    print("        Run: pip install gspread google-auth")
    sys.exit(1)

# ── Schema definitions ────────────────────────────────────────

ARTICLES_HEADERS = [
    # ── Visible-priority columns (left side) ──────────────────────────────────
    "approved",          # NEW: checkbox; TRUE triggers build.py pipeline
    "title_ko",
    "status",
    "published_date",
    "source_name",
    "relevance_score",
    "is_product_news",
    "url",
    "recommendation",
    "is_cluster_rep",
    "cluster_id",
    "input_type",
    # ── Body / translation columns ────────────────────────────────────────────
    "body_ko",
    "title_en",
    "body_en",
    # ── Secondary metadata ────────────────────────────────────────────────────
    "source_type",
    "tags_internal",
    "image_url",
    "photo_drive_url",
    "direct_text",
    "month_key",
    "glossary_validated",
    "classifier_feedback",
    "id",              # UUID; kept last so key columns stay visible without scrolling
]

KEYWORDS_HEADERS = ["keyword", "is_active", "source", "note"]

GLOSSARY_HEADERS = ["term_ko", "term_en", "term_zh", "category", "note", "is_active"]

REPORTS_HEADERS = ["month", "article_count", "pdf_public_url", "status", "sent_at"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COMMANDER_EMAIL = "seouldesk.help@gmail.com"


# ── Helpers ───────────────────────────────────────────────────

def _active_flag(raw: str) -> str:
    """Convert Airtable 'checked' or 'TRUE' → 'TRUE'; anything else → 'FALSE'."""
    return "TRUE" if raw.strip().lower() in ("checked", "true", "1", "yes") else "FALSE"


def _read_csv(path: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) from a CSV file. Strips BOM."""
    rows: list[list[str]] = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        for row in reader:
            rows.append(row)
    return headers, rows


def _ensure_tab(spreadsheet: gspread.Spreadsheet, tab_name: str, headers: list[str]) -> gspread.Worksheet:
    """Return existing tab or create it with the given headers."""
    try:
        ws = spreadsheet.worksheet(tab_name)
        print(f"  Tab '{tab_name}' already exists — skipping creation.")
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=len(headers))
        ws.append_row(headers, value_input_option="USER_ENTERED")
        print(f"  Tab '{tab_name}' created with {len(headers)} columns.")
        return ws


def _clear_data_rows(ws: gspread.Worksheet) -> None:
    """Delete all rows except the header row (row 1)."""
    all_values = ws.get_all_values()
    if len(all_values) <= 1:
        return  # nothing to clear
    ws.delete_rows(2, len(all_values))


def _import_keywords(ws: gspread.Worksheet, csv_path: str) -> int:
    """Import Keywords CSV into the keywords tab. Returns row count."""
    headers, rows = _read_csv(csv_path)
    tab_headers = ws.row_values(1)

    batch: list[list[str]] = []
    for row in rows:
        row_dict = dict(zip(headers, row))
        mapped = {
            "id":        str(uuid.uuid4()),
            "keyword":   row_dict.get("keyword", ""),
            "is_active": _active_flag(row_dict.get("is_active", "")),
            "source":    row_dict.get("source", ""),
            "note":      row_dict.get("note", ""),
        }
        batch.append([mapped.get(h, "") for h in tab_headers])

    if batch:
        ws.append_rows(batch, value_input_option="USER_ENTERED")
    return len(batch)


def _import_glossary(ws: gspread.Worksheet, csv_path: str) -> int:
    """Import Glossary CSV into the glossary tab. Returns row count."""
    headers, rows = _read_csv(csv_path)
    tab_headers = ws.row_values(1)

    batch: list[list[str]] = []
    for row in rows:
        row_dict = dict(zip(headers, row))
        mapped = {
            "id":        str(uuid.uuid4()),
            "term_ko":   row_dict.get("term_ko", ""),
            "term_en":   row_dict.get("term_en", ""),
            "term_zh":   row_dict.get("term_zh", ""),
            "category":  row_dict.get("category", ""),
            "note":      row_dict.get("note", ""),
            "is_active": _active_flag(row_dict.get("is_active", "")),
        }
        batch.append([mapped.get(h, "") for h in tab_headers])

    if batch:
        ws.append_rows(batch, value_input_option="USER_ENTERED")
    return len(batch)


def _import_articles(ws: gspread.Worksheet, csv_path: str) -> int:
    """Import Articles CSV (published only) into the articles tab."""
    headers, rows = _read_csv(csv_path)
    tab_headers = ws.row_values(1)

    batch: list[list[str]] = []
    for row in rows:
        row_dict = dict(zip(headers, row))
        status = row_dict.get("status", "")
        if status not in ("published", "translated"):
            continue  # only import published articles

        pd_val = row_dict.get("published_date", "")
        month_key = pd_val[:7] if len(pd_val) >= 7 else ""

        mapped = {
            "id":             str(uuid.uuid4()),
            "url":            row_dict.get("url", ""),
            "title_ko":       row_dict.get("title_ko", ""),
            "title_en":       row_dict.get("title_en", ""),
            "body_ko":        row_dict.get("body_ko", ""),
            "body_en":        row_dict.get("body_en", ""),
            "source_name":    row_dict.get("source_name", ""),
            "source_type":    row_dict.get("source_type", "auto"),
            "published_date": pd_val,
            "status":         status,
            "month_key":      month_key,
        }
        batch.append([mapped.get(h, "") for h in tab_headers])

    if batch:
        ws.append_rows(batch, value_input_option="USER_ENTERED")
    return len(batch)


# ── Main ──────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="KVN Google Sheets one-time setup.")
    parser.add_argument("--keywords-csv",  required=True, help="Path to Keywords CSV export")
    parser.add_argument("--glossary-csv",  required=True, help="Path to Glossary CSV export")
    parser.add_argument("--articles-csv",  default=None,  help="(Optional) Path to Articles CSV export")
    parser.add_argument("--sheets-id",     default=None,  help="Existing Sheets ID (skip creation)")
    parser.add_argument("--share-email",   default=COMMANDER_EMAIL, help="Email to grant editor access")
    args = parser.parse_args()

    # ── Auth ──
    sa_json_raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_raw:
        print("[ERROR] GOOGLE_SERVICE_ACCOUNT_JSON environment variable is not set.")
        sys.exit(1)

    creds = Credentials.from_service_account_info(json.loads(sa_json_raw), scopes=SCOPES)
    client = gspread.authorize(creds)
    print("✓ Authenticated with Google.")

    # ── Open or create spreadsheet ──
    if args.sheets_id:
        spreadsheet = client.open_by_key(args.sheets_id)
        print(f"✓ Opened existing spreadsheet: {spreadsheet.title}")
    else:
        spreadsheet = client.create("KVN Master Data")
        # Share with Commander
        spreadsheet.share(args.share_email, perm_type="user", role="writer")
        print(f"✓ Created 'KVN Master Data' spreadsheet.")
        print(f"  Shared with {args.share_email}.")

    print(f"\n📋 Sheets ID: {spreadsheet.id}")
    print(f"   URL: https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit\n")

    # ── Create tabs ──
    print("Setting up tabs...")

    # Delete the default 'Sheet1' if it exists and is empty
    try:
        sheet1 = spreadsheet.worksheet("Sheet1")
        if len(spreadsheet.worksheets()) > 1:
            spreadsheet.del_worksheet(sheet1)
            print("  Removed default 'Sheet1'.")
    except gspread.exceptions.WorksheetNotFound:
        pass

    # articles tab — id column added at front
    # ARTICLES_HEADERS already includes 'id' as the last entry (moved there in Phase 4).
    # No splice needed; pass the list as-is.
    articles_ws = _ensure_tab(spreadsheet, "articles", ARTICLES_HEADERS)
    keywords_ws = _ensure_tab(spreadsheet, "keywords",  ["id"] + KEYWORDS_HEADERS)
    glossary_ws = _ensure_tab(spreadsheet, "glossary",  ["id"] + GLOSSARY_HEADERS)
    _ensure_tab(spreadsheet, "reports",   ["id"] + REPORTS_HEADERS)

    # ── Import Keywords ──
    print(f"\nImporting Keywords from: {args.keywords_csv}")
    kw_count = _import_keywords(keywords_ws, args.keywords_csv)
    print(f"  ✓ {kw_count} keywords imported.")

    # ── Import Glossary ──
    print(f"\nImporting Glossary from: {args.glossary_csv}")
    gl_count = _import_glossary(glossary_ws, args.glossary_csv)
    print(f"  ✓ {gl_count} glossary terms imported.")

    # ── Import Articles (optional) ──
    if args.articles_csv:
        print(f"\nImporting Articles from: {args.articles_csv}")
        ar_count = _import_articles(articles_ws, args.articles_csv)
        print(f"  ✓ {ar_count} published articles imported.")

    # ── Final instructions ──
    print("\n" + "=" * 60)
    print("SETUP COMPLETE")
    print("=" * 60)
    print(f"\nSheets ID (register as GitHub Secret KVN_SHEETS_ID):")
    print(f"  {spreadsheet.id}")
    print(f"\nURL:")
    print(f"  https://docs.google.com/spreadsheets/d/{spreadsheet.id}/edit")
    print(f"\nNext steps:")
    print("  1. Register KVN_SHEETS_ID in GitHub Secrets (wkdjk/korea-velvet-news)")
    print("  2. Register GOOGLE_SERVICE_ACCOUNT_JSON (same as VTW)")
    print("  3. Register GMAIL_APP_PASSWORD for monthly email")
    print("  4. Update local .env file")
    print("  5. Run: python scripts/collect.py  (test collection)")


if __name__ == "__main__":
    main()
