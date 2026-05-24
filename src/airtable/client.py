"""
src/airtable/client.py — Google Sheets–backed drop-in replacement.

Public API is identical to the original Airtable version so all calling
code (collect.py, build.py, form_processor, translator, generate.py)
requires zero changes.

Internals use gspread + Google Sheets API. Records are returned in
Airtable record format: {"id": "<uuid>", "fields": {...}}.

Tab name mapping (Airtable → Google Sheets):
    Articles → articles
    Keywords → keywords
    Glossary → glossary
    Reports  → reports
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Optional

import gspread
import gspread.exceptions
from google.oauth2.service_account import Credentials

import config  # triggers env-var validation on import

logger = logging.getLogger(__name__)

# ── OAuth2 scopes ──────────────────────────────────────────────
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

# ── Tab name mapping ──────────────────────────────────────────
_TAB_MAP: dict[str, str] = {
    "Articles": "articles",
    "Keywords": "keywords",
    "Glossary": "glossary",
    "Reports":  "reports",
}

# ── Fields that hold lists (comma-separated in Sheets) ────────
_LIST_FIELDS: frozenset[str] = frozenset({"tags_internal"})

# ── Fields that hold booleans (TRUE/FALSE in Sheets) ──────────
_BOOL_FIELDS: frozenset[str] = frozenset({
    "is_active", "is_cluster_rep", "is_product_news",
    "glossary_validated",
})

# ── Singletons ────────────────────────────────────────────────
_client: Optional[gspread.Client] = None
_spreadsheet: Optional[gspread.Spreadsheet] = None


# ---------------------------------------------------------------------------
# Internal: auth + tab access
# ---------------------------------------------------------------------------

def _get_client() -> gspread.Client:
    global _client
    if _client is None:
        creds = Credentials.from_service_account_info(
            config.GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=_SCOPES,
        )
        _client = gspread.authorize(creds)
        logger.info("gspread client authenticated.")
    return _client


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet
    if _spreadsheet is None:
        try:
            _spreadsheet = _get_client().open_by_key(config.KVN_SHEETS_ID)
            logger.info("Spreadsheet '%s' opened.", _spreadsheet.title)
        except gspread.exceptions.SpreadsheetNotFound as exc:
            raise gspread.exceptions.SpreadsheetNotFound(
                f"Spreadsheet '{config.KVN_SHEETS_ID}' not found. "
                "Check KVN_SHEETS_ID and service account access."
            ) from exc
    return _spreadsheet


def _get_tab(table_name: str) -> gspread.Worksheet:
    tab_name = _TAB_MAP.get(table_name, table_name.lower())
    return _get_spreadsheet().worksheet(tab_name)


# ---------------------------------------------------------------------------
# Internal: Airtable formula evaluator
#
# Handles the exact patterns used in KVN scripts:
#   {field}='value'
#   AND(..., ...)
#   OR(..., ...)
# ---------------------------------------------------------------------------

def _split_top_level(s: str) -> list[str]:
    """Split a comma-separated string ignoring commas inside parentheses."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return parts


def _eval_formula(row: dict, formula: str) -> bool:
    """Evaluate an Airtable-style formula against a raw (string) row dict."""
    f = formula.strip()
    upper = f.upper()

    if upper.startswith("AND(") and f.endswith(")"):
        parts = _split_top_level(f[4:-1])
        return all(_eval_formula(row, p) for p in parts)

    if upper.startswith("OR(") and f.endswith(")"):
        parts = _split_top_level(f[3:-1])
        return any(_eval_formula(row, p) for p in parts)

    # {field}='value'  or  {field} = 'value'
    m = re.match(r"\{(\w+)\}\s*=\s*'([^']*)'", f)
    if m:
        field, value = m.group(1), m.group(2)
        return str(row.get(field, "")) == value

    logger.debug("_eval_formula: unrecognised pattern %r — including row.", formula)
    return True  # unknown pattern → include row (safe default)


# ---------------------------------------------------------------------------
# Internal: serialisation / deserialisation
# ---------------------------------------------------------------------------

def _serialize_value(key: str, value) -> str:
    """Convert a Python value to the string stored in Sheets."""
    if value is None:
        return ""
    if key in _LIST_FIELDS:
        if isinstance(value, (list, tuple)):
            return ",".join(str(v) for v in value)
        return str(value)
    if key in _BOOL_FIELDS:
        return "TRUE" if bool(value) else "FALSE"
    return str(value)


def _deserialize_row(row: dict) -> dict:
    """Convert raw Sheets string values to appropriate Python types."""
    out: dict = {}
    for k, v in row.items():
        if k in _LIST_FIELDS:
            out[k] = [x.strip() for x in v.split(",") if x.strip()] if v else []
        elif k in _BOOL_FIELDS:
            out[k] = str(v).upper() == "TRUE"
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Internal: ensure every row has a UUID in the 'id' column
# ---------------------------------------------------------------------------

def _ensure_ids(tab: gspread.Worksheet, all_rows: list[dict]) -> list[dict]:
    """Assign UUIDs to any rows missing an 'id'. Writes them back in one batch."""
    headers = tab.row_values(1)
    if "id" not in headers:
        return all_rows  # no id column — skip

    id_col_idx = headers.index("id") + 1  # 1-based for gspread
    cells_to_update: list[gspread.Cell] = []

    for sheet_row_idx, row in enumerate(all_rows, start=2):  # row 1 = header
        if not row.get("id"):
            new_id = str(uuid.uuid4())
            row["id"] = new_id
            cells_to_update.append(gspread.Cell(sheet_row_idx, id_col_idx, new_id))

    if cells_to_update:
        tab.update_cells(cells_to_update, value_input_option="USER_ENTERED")
        logger.info("_ensure_ids: wrote %d new UUIDs.", len(cells_to_update))

    return all_rows


# ---------------------------------------------------------------------------
# Public API — identical interface to the original Airtable client
# ---------------------------------------------------------------------------

def get_records(
    table_name: str,
    filter_formula: str = None,
    fields: list = None,
) -> list[dict]:
    """Return records in Airtable format: [{"id": "<uuid>", "fields": {...}}, ...].

    Args:
        table_name:     One of "Articles", "Keywords", "Glossary", "Reports".
        filter_formula: Optional Airtable-style formula string for filtering.
        fields:         Optional list of field names to include in the result.

    Returns:
        List of record dicts, each with keys "id" (str) and "fields" (dict).
    """
    tab = _get_tab(table_name)
    all_rows: list[dict] = tab.get_all_records(empty2zero=False, head=1)

    # Assign UUIDs to rows that don't have one (e.g. Google Form submissions)
    all_rows = _ensure_ids(tab, all_rows)

    results: list[dict] = []
    for row in all_rows:
        # Filter on raw string values (before deserialization) so formulas
        # like {is_active}='TRUE' match the literal cell content.
        if filter_formula and not _eval_formula(row, filter_formula):
            continue

        deserialized = _deserialize_row(row)
        record_id = deserialized.pop("id", "")

        if fields:
            deserialized = {k: v for k, v in deserialized.items() if k in fields}

        results.append({"id": record_id, "fields": deserialized})

    logger.debug("get_records('%s'): %d rows returned.", table_name, len(results))
    return results


def create_record(table_name: str, fields: dict) -> dict:
    """Append a new row and return it in Airtable record format.

    Automatically computes month_key from published_date if not provided.

    Returns:
        {"id": "<uuid>", "fields": <fields dict as supplied>}
    """
    tab = _get_tab(table_name)
    headers = tab.row_values(1)

    record_id = str(uuid.uuid4())
    row_data: dict = {"id": record_id}
    row_data.update(fields)

    # Auto-compute month_key from published_date (YYYY-MM)
    if "published_date" in row_data and "month_key" not in row_data:
        pd_val = str(row_data.get("published_date", ""))
        if len(pd_val) >= 7:
            row_data["month_key"] = pd_val[:7]

    values = [_serialize_value(h, row_data.get(h, "")) for h in headers]
    tab.append_row(values, value_input_option="USER_ENTERED")

    logger.info("create_record('%s'): id=%s", table_name, record_id)
    return {"id": record_id, "fields": fields}


def update_record(table_name: str, record_id: str, fields: dict) -> dict:
    """Find the row with matching id and update the specified fields.

    Returns:
        {"id": record_id, "fields": <updated fields>}

    Raises:
        ValueError: If the record is not found.
    """
    tab = _get_tab(table_name)
    all_values = tab.get_all_values()

    if not all_values:
        raise ValueError(f"Tab '{table_name}' is empty.")

    headers = all_values[0]
    if "id" not in headers:
        raise ValueError(f"Tab '{table_name}' has no 'id' column.")

    id_col_idx = headers.index("id")

    # Find matching row (1-based; row 1 = header, data starts at 2)
    target_row: Optional[int] = None
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > id_col_idx and row[id_col_idx] == record_id:
            target_row = i
            break

    if target_row is None:
        raise ValueError(
            f"Record '{record_id}' not found in tab '{table_name}'."
        )

    # Build batch update — only touch cells for the changed fields
    cells: list[gspread.Cell] = []
    for field, value in fields.items():
        if field in headers:
            col_idx = headers.index(field) + 1  # 1-based
            cells.append(gspread.Cell(target_row, col_idx, _serialize_value(field, value)))

    if cells:
        tab.update_cells(cells, value_input_option="USER_ENTERED")

    logger.info("update_record('%s'): id=%s, fields=%s", table_name, record_id, list(fields))
    return {"id": record_id, "fields": fields}


def batch_update_records(table_name: str, updates: list[dict]) -> list[dict]:
    """Update multiple records efficiently.

    Args:
        updates: List of {"id": record_id, "fields": {...}} dicts.

    Returns:
        List of {"id": ..., "fields": ...} results (one per update).
    """
    if not updates:
        return []

    tab = _get_tab(table_name)
    all_values = tab.get_all_values()

    if not all_values:
        raise ValueError(f"Tab '{table_name}' is empty.")

    headers = all_values[0]
    if "id" not in headers:
        raise ValueError(f"Tab '{table_name}' has no 'id' column.")

    id_col_idx = headers.index("id")

    # Build an id → row_number map for O(1) lookup
    id_to_row: dict[str, int] = {}
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > id_col_idx and row[id_col_idx]:
            id_to_row[row[id_col_idx]] = i

    # Collect all cell updates in one batch
    all_cells: list[gspread.Cell] = []
    results: list[dict] = []

    for item in updates:
        record_id = item["id"]
        fields = item["fields"]
        row_num = id_to_row.get(record_id)

        if row_num is None:
            logger.warning("batch_update_records: id '%s' not found — skipped.", record_id)
            continue

        for field, value in fields.items():
            if field in headers:
                col_idx = headers.index(field) + 1
                all_cells.append(gspread.Cell(row_num, col_idx, _serialize_value(field, value)))

        results.append({"id": record_id, "fields": fields})

    if all_cells:
        tab.update_cells(all_cells, value_input_option="USER_ENTERED")

    logger.info(
        "batch_update_records('%s'): %d/%d records updated.",
        table_name, len(results), len(updates),
    )
    return results


def url_exists(url: str) -> bool:
    """Return True if the normalised URL already exists in the Articles tab."""
    # Search raw values directly — no need to deserialise
    tab = _get_tab("Articles")
    all_rows: list[dict] = tab.get_all_records(empty2zero=False, head=1)
    return any(row.get("url", "") == url for row in all_rows)


def get_active_keywords() -> list[str]:
    """Return keyword strings where is_active is TRUE."""
    records = get_records(
        "Keywords",
        filter_formula="{is_active}='TRUE'",
        fields=["keyword"],
    )
    return [r["fields"]["keyword"] for r in records if r["fields"].get("keyword")]


def get_active_glossary() -> list[dict]:
    """Return [{term_ko, term_en}] for active Glossary records."""
    records = get_records(
        "Glossary",
        filter_formula="{is_active}='TRUE'",
        fields=["term_ko", "term_en"],
    )
    return [
        {
            "term_ko": r["fields"].get("term_ko", ""),
            "term_en": r["fields"].get("term_en", ""),
        }
        for r in records
        if r["fields"].get("term_ko") and r["fields"].get("term_en")
    ]
