"""
scripts/create_ignored_urls_tab.py — One-shot setup script.

Creates the 'ignored_urls' worksheet in the KVN Google Spreadsheet and writes
the header row.  Run this once manually before using ignore_record() or the
ignored_url_exists() dedup check.

Usage (from the repo root):
    python scripts/create_ignored_urls_tab.py

Prerequisites:
    - .env file present in the repo root (or env vars already exported)
    - GOOGLE_SERVICE_ACCOUNT_JSON and KVN_SHEETS_ID set
    - Service account has editor access to the spreadsheet
"""
import sys

import gspread.exceptions
from google.oauth2.service_account import Credentials

import config  # triggers env-var validation; raises EnvironmentError if vars missing

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_TAB_NAME = "ignored_urls"
_HEADERS = ["url", "title_ko", "ignored_date", "reason"]


def main() -> None:
    """Create the ignored_urls tab with its header row, or report if it exists."""
    creds = Credentials.from_service_account_info(
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        scopes=_SCOPES,
    )
    client = gspread.authorize(creds)

    try:
        spreadsheet = client.open_by_key(config.KVN_SHEETS_ID)
    except gspread.exceptions.SpreadsheetNotFound:
        print(
            f"ERROR: spreadsheet '{config.KVN_SHEETS_ID}' not found. "
            "Check KVN_SHEETS_ID and service account access.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Check whether the tab already exists
    existing_titles = [ws.title for ws in spreadsheet.worksheets()]
    if _TAB_NAME in existing_titles:
        print("Tab already exists — skipped.")
        return

    # Create tab and write header
    worksheet = spreadsheet.add_worksheet(
        title=_TAB_NAME,
        rows=1000,
        cols=len(_HEADERS),
    )
    worksheet.append_row(_HEADERS, value_input_option="USER_ENTERED")
    print("ignored_urls tab created.")


if __name__ == "__main__":
    main()
