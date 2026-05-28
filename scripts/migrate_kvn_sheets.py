"""
scripts/migrate_kvn_sheets.py — In-place data migration for "Korea Velvet News — Master Data".

Applies the following transformations to the live sheet:

1. articles tab:
   - Converts approved column values: TRUE → YES, FALSE → NO.
   - Only rows where status is 'published' or 'translated' are retained
     (all others are left as-is — single-tab architecture means we keep
     every row, but we ensure approved is correctly formatted).
   - Actually: converts ALL approved values for full consistency.

2. ignored_urls tab:
   - Strips empty rows (keeps only rows with a non-empty url column).
   - Resizes the tab to header + real rows + a small buffer (max 200 rows).

3. keywords, glossary, reports:
   - Row counts reported; no transformation needed (data already in place).

Usage:
    PYTHONPATH=. python scripts/migrate_kvn_sheets.py

No arguments required. Reads KVN_SHEETS_ID and GOOGLE_SERVICE_ACCOUNT_JSON from .env.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv

load_dotenv()

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERROR] gspread or google-auth not installed.")
    print("        Run: pip install gspread google-auth")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEETS_ID = os.environ.get("KVN_SHEETS_ID", "")


def _get_spreadsheet() -> gspread.Spreadsheet:
    sa_json_raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_raw:
        print("[ERROR] GOOGLE_SERVICE_ACCOUNT_JSON is not set.")
        sys.exit(1)
    if not SHEETS_ID:
        print("[ERROR] KVN_SHEETS_ID is not set.")
        sys.exit(1)
    creds = Credentials.from_service_account_info(json.loads(sa_json_raw), scopes=SCOPES)
    client = gspread.authorize(creds)
    ss = client.open_by_key(SHEETS_ID)
    print(f"Opened: {ss.title} ({SHEETS_ID})")
    return ss


# ── Task 1: migrate approved column TRUE/FALSE → YES/NO ──────────────────────

def migrate_approved(ss: gspread.Spreadsheet) -> None:
    """Convert all approved values in the articles tab to YES/NO strings."""
    ws = ss.worksheet("articles")
    all_values = ws.get_all_values()

    if not all_values:
        print("articles tab: empty — skipping.")
        return

    headers = all_values[0]
    if "approved" not in headers:
        print("articles tab: no 'approved' column found — skipping.")
        return

    approved_col_idx = headers.index("approved")  # 0-based
    approved_col_1based = approved_col_idx + 1

    cells_to_update: list[gspread.Cell] = []
    converted = 0
    already_ok = 0
    skipped_empty = 0

    for row_idx, row in enumerate(all_values[1:], start=2):
        if len(row) <= approved_col_idx:
            skipped_empty += 1
            continue

        raw = str(row[approved_col_idx]).strip()

        if raw.upper() in ("TRUE", "1", "YES"):
            new_val = "YES"
        elif raw.upper() in ("FALSE", "0", "NO"):
            new_val = "NO"
        elif raw == "":
            # Empty cells → default NO
            new_val = "NO"
        else:
            print(f"  [WARN] Row {row_idx}: unexpected approved value '{raw}' → NO")
            new_val = "NO"

        if raw == new_val:
            already_ok += 1
        else:
            cells_to_update.append(gspread.Cell(row_idx, approved_col_1based, new_val))
            converted += 1

    if cells_to_update:
        ws.update_cells(cells_to_update, value_input_option="USER_ENTERED")

    print(
        f"articles tab: {converted} approved values converted, "
        f"{already_ok} already correct, {skipped_empty} empty rows skipped."
    )
    print(f"  Total data rows: {len(all_values) - 1}")


# ── Task 2: clean ignored_urls tab (strip empty rows) ───────────────────────

def clean_ignored_urls(ss: gspread.Spreadsheet) -> None:
    """Remove empty rows from ignored_urls; resize tab to header + real rows + buffer."""
    ws = ss.worksheet("ignored_urls")
    all_values = ws.get_all_values()

    if not all_values:
        print("ignored_urls tab: empty — nothing to clean.")
        return

    headers = all_values[0]
    data_rows = all_values[1:]

    # Keep only rows with a non-empty url (first column)
    real_rows = [r for r in data_rows if r and r[0].strip()]
    empty_count = len(data_rows) - len(real_rows)

    print(f"ignored_urls tab: {len(data_rows)} total data rows, "
          f"{len(real_rows)} with URLs, {empty_count} empty.")

    if empty_count == 0:
        print("  No empty rows to remove.")
        return

    # Clear the entire worksheet, then rewrite with header + real rows only.
    # Bulk approach: clear all, set header, append real rows.
    ws.clear()
    ws.append_row(headers, value_input_option="USER_ENTERED")

    if real_rows:
        ws.append_rows(real_rows, value_input_option="USER_ENTERED")

    # Resize the sheet to header + real rows + 10-row buffer (min 50)
    new_row_count = max(50, len(real_rows) + 11)
    # Sheets API resize via batch_update
    ss.batch_update({
        "requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": ws.id,
                    "gridProperties": {
                        "rowCount": new_row_count,
                        "columnCount": len(headers),
                    },
                },
                "fields": "gridProperties.rowCount,gridProperties.columnCount",
            }
        }]
    })

    print(f"  ignored_urls tab cleaned: {len(real_rows)} URL rows retained, "
          f"tab resized to {new_row_count} rows.")


# ── Task 3: report row counts for remaining tabs ────────────────────────────

def report_tab_counts(ss: gspread.Spreadsheet) -> None:
    """Print row counts for keywords, glossary, and reports tabs."""
    for tab_name in ["keywords", "glossary", "reports"]:
        ws = ss.worksheet(tab_name)
        rows = ws.get_all_records(empty2zero=False, head=1)
        print(f"{tab_name} tab: {len(rows)} data rows (no transformation applied).")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Migration started: {date.today().isoformat()}")
    print("=" * 60)

    ss = _get_spreadsheet()

    print("\n[1] Migrating articles approved column...")
    migrate_approved(ss)

    print("\n[2] Cleaning ignored_urls tab...")
    clean_ignored_urls(ss)

    print("\n[3] Reporting other tab row counts...")
    report_tab_counts(ss)

    print("\n" + "=" * 60)
    print("MIGRATION COMPLETE")
    print("=" * 60)
    print(f"\nSheet: https://docs.google.com/spreadsheets/d/{SHEETS_ID}/edit")


if __name__ == "__main__":
    main()
