"""
scripts/format_articles_sheet.py — One-time runner: reorder articles tab columns,
add 'approved' checkbox column, and apply formatting to the KVN Google Sheet.

Usage:
    python scripts/format_articles_sheet.py

Requires environment variables (loaded from .env):
    GOOGLE_SERVICE_ACCOUNT_JSON   Service account JSON string
    KVN_SHEETS_ID                 Target spreadsheet ID

Safety:
    - All existing data rows are preserved; only column order changes.
    - The 'approved' column is added with FALSE for every existing row.
    - The script is idempotent: if 'approved' already exists it is not duplicated.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Load .env from repo root (one level up from scripts/)
_repo_root = Path(__file__).resolve().parent.parent
_env_path = _repo_root / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_env_path)
except ImportError:
    pass  # python-dotenv optional; rely on shell-exported vars

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERROR] gspread or google-auth not installed.")
    print("        Run: pip install gspread google-auth")
    sys.exit(1)

# ── Target column order ───────────────────────────────────────────────────────
# 'approved' is always column A (index 0).
# 'id' is moved to the final column for cleanliness.

NEW_COLUMN_ORDER: list[str] = [
    "approved",
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
    "body_ko",
    "title_en",
    "body_en",
    "source_type",
    "tags_internal",
    "image_url",
    "photo_drive_url",
    "direct_text",
    "month_key",
    "glossary_validated",
    "classifier_feedback",
    "id",
]

# ── Column widths (pixels) ────────────────────────────────────────────────────
COLUMN_WIDTHS: dict[str, int] = {
    "approved":        80,
    "title_ko":       280,
    "status":         120,
    "published_date": 110,
    "source_name":    150,
    "relevance_score": 90,
    "is_product_news": 90,
    "url":            200,
}
DEFAULT_WIDTH = 100

# ── Header row formatting ─────────────────────────────────────────────────────
HEADER_BG_COLOUR = {"red": 0.290, "green": 0.565, "blue": 0.851}  # #4A90D9
HEADER_FG_COLOUR = {"red": 1.0,   "green": 1.0,   "blue": 1.0}    # white

ROW_HEIGHT_PX = 21

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth() -> gspread.Client:
    """Authenticate using GOOGLE_SERVICE_ACCOUNT_JSON env var."""
    sa_json_raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_json_raw:
        print("[ERROR] GOOGLE_SERVICE_ACCOUNT_JSON is not set.")
        sys.exit(1)
    creds = Credentials.from_service_account_info(json.loads(sa_json_raw), scopes=SCOPES)
    return gspread.authorize(creds)


def _col_letter(index: int) -> str:
    """Convert 0-based column index to A1-notation letter(s)."""
    result = ""
    n = index
    while True:
        result = chr(ord("A") + n % 26) + result
        n = n // 26 - 1
        if n < 0:
            break
    return result


def _build_column_requests(sheet_id: int, headers: list[str]) -> list[dict]:
    """Build batchUpdate requests for column widths."""
    requests = []
    for idx, col in enumerate(headers):
        px = COLUMN_WIDTHS.get(col, DEFAULT_WIDTH)
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId":    sheet_id,
                    "dimension":  "COLUMNS",
                    "startIndex": idx,
                    "endIndex":   idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })
    return requests


def _build_row_height_request(sheet_id: int, row_count: int) -> dict:
    """Build a single batchUpdate request to set all row heights."""
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId":    sheet_id,
                "dimension":  "ROWS",
                "startIndex": 0,
                "endIndex":   row_count,
            },
            "properties": {"pixelSize": ROW_HEIGHT_PX},
            "fields": "pixelSize",
        }
    }


def _build_freeze_request(sheet_id: int) -> dict:
    """Freeze row 1 (header)."""
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId":     sheet_id,
                "gridProperties": {"frozenRowCount": 1},
            },
            "fields": "gridProperties.frozenRowCount",
        }
    }


def _build_header_format_request(sheet_id: int, num_cols: int) -> dict:
    """Apply background colour, white bold text to header row."""
    return {
        "repeatCell": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    0,
                "endRowIndex":      1,
                "startColumnIndex": 0,
                "endColumnIndex":   num_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "backgroundColor": HEADER_BG_COLOUR,
                    "textFormat": {
                        "foregroundColor": HEADER_FG_COLOUR,
                        "bold": True,
                    },
                }
            },
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }
    }


def _build_checkbox_request(sheet_id: int, approved_col_idx: int, num_data_rows: int) -> dict:
    """Apply Boolean checkbox data validation to the 'approved' column (data rows only)."""
    return {
        "setDataValidation": {
            "range": {
                "sheetId":          sheet_id,
                "startRowIndex":    1,               # skip header
                "endRowIndex":      1 + num_data_rows,
                "startColumnIndex": approved_col_idx,
                "endColumnIndex":   approved_col_idx + 1,
            },
            "rule": {
                "condition": {"type": "BOOLEAN"},
                "showCustomUi": True,
            },
        }
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    sheets_id = os.environ.get("KVN_SHEETS_ID", "")
    if not sheets_id:
        print("[ERROR] KVN_SHEETS_ID is not set.")
        sys.exit(1)

    client = _auth()
    print("Authenticated with Google.")

    spreadsheet = client.open_by_key(sheets_id)
    ws = spreadsheet.worksheet("articles")
    sheet_id = ws.id
    print(f"Opened 'articles' tab (sheet_id={sheet_id}).")

    # ── Read all existing data ────────────────────────────────────────────────
    all_values: list[list[str]] = ws.get_all_values()
    if not all_values:
        print("[ERROR] 'articles' tab is completely empty — nothing to reformat.")
        sys.exit(1)

    old_headers: list[str] = all_values[0]
    data_rows:   list[list[str]] = all_values[1:]
    print(f"  Read {len(data_rows)} data row(s), {len(old_headers)} existing column(s).")

    # ── Guard: do not duplicate 'approved' ───────────────────────────────────
    if "approved" in old_headers:
        print("  'approved' column already present — adjusting source mapping.")

    # Build dict list from old data
    old_records: list[dict[str, str]] = []
    for row in data_rows:
        # Pad short rows to match header length
        padded = row + [""] * (len(old_headers) - len(row))
        old_records.append(dict(zip(old_headers, padded)))

    # ── Determine final column list ───────────────────────────────────────────
    # Any old column not in NEW_COLUMN_ORDER is appended at the end (safety net).
    known_set = set(NEW_COLUMN_ORDER)
    extra_cols = [c for c in old_headers if c not in known_set]
    final_headers = NEW_COLUMN_ORDER + extra_cols

    print(f"  Final column count: {len(final_headers)}")
    if extra_cols:
        print(f"  Extra columns appended: {extra_cols}")

    # ── Build new data grid ───────────────────────────────────────────────────
    new_grid: list[list[str]] = [final_headers]
    approved_col_idx = final_headers.index("approved")

    for record in old_records:
        new_row: list[str] = []
        for col in final_headers:
            if col == "approved":
                # Use existing value if present, otherwise FALSE
                new_row.append(record.get("approved", "FALSE"))
            else:
                new_row.append(record.get(col, ""))
        new_grid.append(new_row)

    # ── Clear and rewrite the entire sheet ───────────────────────────────────
    print("  Clearing sheet...")
    ws.clear()

    print("  Writing new column order + data...")
    ws.update(
        range_name="A1",
        values=new_grid,
        value_input_option="USER_ENTERED",
    )
    print(f"  Wrote {len(new_grid)} rows ({len(new_grid) - 1} data row(s)).")

    # ── batchUpdate: formatting ───────────────────────────────────────────────
    total_rows = len(new_grid)
    num_data_rows = total_rows - 1
    num_cols = len(final_headers)

    requests: list[dict] = []
    requests.append(_build_freeze_request(sheet_id))
    requests.append(_build_row_height_request(sheet_id, total_rows + 50))  # +50 buffer
    requests.extend(_build_column_requests(sheet_id, final_headers))
    requests.append(_build_header_format_request(sheet_id, num_cols))

    if num_data_rows > 0:
        requests.append(_build_checkbox_request(sheet_id, approved_col_idx, num_data_rows))

    print("  Applying formatting via batchUpdate...")
    spreadsheet.batch_update({"requests": requests})
    print("  Formatting applied.")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("FORMAT COMPLETE")
    print("=" * 60)
    print(f"  Columns: {len(final_headers)}")
    print(f"  Data rows preserved: {num_data_rows}")
    print(f"  'approved' column index: {approved_col_idx + 1} (column {_col_letter(approved_col_idx)})")
    print(f"  URL: https://docs.google.com/spreadsheets/d/{sheets_id}/edit")


if __name__ == "__main__":
    main()
