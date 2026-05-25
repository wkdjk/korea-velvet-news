"""
scripts/add_article_columns.py — One-time migration: add 3 new columns to articles tab.

Adds after 'body_en' (column O):
  - why_it_matters      (column P)
  - source_attribution  (column Q)
  - category            (column R)

All subsequent columns shift right by 3.

Usage (run once from project root):
    python scripts/add_article_columns.py
"""
from __future__ import annotations

import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERROR] gspread not installed. Run: pip install gspread google-auth")
    sys.exit(1)

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_NEW_COLUMNS = ["why_it_matters", "source_attribution", "category"]

# Insert AFTER this column header
_INSERT_AFTER = "body_en"


def main():
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    sheets_id = os.environ.get("KVN_SHEETS_ID", "")

    if not sa_json or not sheets_id:
        print("[ERROR] GOOGLE_SERVICE_ACCOUNT_JSON and KVN_SHEETS_ID must be set.")
        sys.exit(1)

    creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=_SCOPES)
    client = gspread.authorize(creds)
    ss = client.open_by_key(sheets_id)
    tab = ss.worksheet("articles")

    headers = tab.row_values(1)
    print(f"Current columns ({len(headers)}): {headers}")

    # Check if already migrated
    if "why_it_matters" in headers:
        print("✅  'why_it_matters' already exists — migration not needed.")
        return

    if _INSERT_AFTER not in headers:
        print(f"[ERROR] Column '{_INSERT_AFTER}' not found in headers.")
        sys.exit(1)

    insert_after_idx = headers.index(_INSERT_AFTER)  # 0-based
    # Insert columns AFTER body_en → column index is insert_after_idx + 2 (1-based, +1 for after)
    insert_col_1based = insert_after_idx + 2  # 1-based position to insert at

    # Google Sheets API: insertDimension inserts BEFORE the given index.
    # We want to insert 3 columns after body_en, so insert before (insert_after_idx + 2).
    tab.spreadsheet.batch_update({
        "requests": [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": tab.id,
                        "dimension": "COLUMNS",
                        "startIndex": insert_after_idx + 1,  # 0-based, insert after body_en
                        "endIndex":   insert_after_idx + 1 + len(_NEW_COLUMNS),
                    },
                    "inheritFromBefore": False,
                }
            }
        ]
    })
    print(f"  Inserted {len(_NEW_COLUMNS)} columns after '{_INSERT_AFTER}'.")

    # Write header names into the new columns
    header_cells = []
    for i, col_name in enumerate(_NEW_COLUMNS):
        col_1based = insert_after_idx + 2 + i  # 1-based
        header_cells.append(gspread.Cell(1, col_1based, col_name))

    tab.update_cells(header_cells, value_input_option="USER_ENTERED")

    new_headers = tab.row_values(1)
    print(f"✅  Migration complete. New columns ({len(new_headers)}): {new_headers}")


if __name__ == "__main__":
    main()
