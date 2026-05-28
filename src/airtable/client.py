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
from datetime import date
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

# ── Fields that use YES/NO strings (not TRUE/FALSE checkboxes) ─
# approved: Commander sets YES; pipeline never reverts to NO.
_YES_NO_FIELDS: frozenset[str] = frozenset({"approved"})

# ── Singletons ────────────────────────────────────────────────
_client: Optional[gspread.Client] = None
_spreadsheet: Optional[gspread.Spreadsheet] = None
_url_cache: Optional[set] = None          # loaded once per session
_ignored_url_cache: Optional[set] = None  # loaded once per session from ignored_urls tab
_headers_cache: dict[str, list[str]] = {} # tab_name → header row, cached per session


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


def _get_headers(tab: gspread.Worksheet, table_name: str) -> list[str]:
    """Return header row for a tab, cached per session to minimise API calls."""
    tab_name = _TAB_MAP.get(table_name, table_name.lower())
    if tab_name not in _headers_cache:
        _headers_cache[tab_name] = tab.row_values(1)
        logger.debug("_get_headers: loaded headers for '%s'.", tab_name)
    return _headers_cache[tab_name]


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
    if key in _YES_NO_FIELDS:
        # Accept True, "YES", "yes", "TRUE", "true" → "YES"; anything else → "NO"
        if value is True or str(value).upper() in ("YES", "TRUE", "1"):
            return "YES"
        return "NO"
    return str(value)


def _deserialize_row(row: dict) -> dict:
    """Convert raw Sheets string values to appropriate Python types."""
    out: dict = {}
    for k, v in row.items():
        if k in _LIST_FIELDS:
            out[k] = [x.strip() for x in v.split(",") if x.strip()] if v else []
        elif k in _BOOL_FIELDS:
            out[k] = str(v).upper() == "TRUE"
        elif k in _YES_NO_FIELDS:
            # YES → True; anything else → False
            out[k] = str(v).upper() == "YES"
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
    headers = _get_headers(tab, table_name)

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

    # Keep URL cache consistent so url_exists() stays accurate within the session
    if table_name == "Articles" and _url_cache is not None and "url" in fields:
        _url_cache.add(str(fields["url"]))

    logger.info("create_record('%s'): id=%s", table_name, record_id)
    return {"id": record_id, "fields": fields}


def batch_create_records(table_name: str, fields_list: list[dict]) -> list[dict]:
    """Append multiple rows in a single API call.

    Args:
        table_name:  One of "Articles", "Keywords", "Glossary", "Reports".
        fields_list: List of field dicts, one per record to create.

    Returns:
        List of {"id": "<uuid>", "fields": <fields dict>} records.
    """
    if not fields_list:
        return []

    tab = _get_tab(table_name)
    headers = _get_headers(tab, table_name)

    results: list[dict] = []
    batch: list[list[str]] = []

    for fields in fields_list:
        record_id = str(uuid.uuid4())
        row_data: dict = {"id": record_id}
        row_data.update(fields)

        # Auto-compute month_key from published_date (YYYY-MM)
        if "published_date" in row_data and "month_key" not in row_data:
            pd_val = str(row_data.get("published_date", ""))
            if len(pd_val) >= 7:
                row_data["month_key"] = pd_val[:7]

        batch.append([_serialize_value(h, row_data.get(h, "")) for h in headers])
        results.append({"id": record_id, "fields": fields})

        # Keep URL cache consistent
        if _url_cache is not None and "url" in fields:
            _url_cache.add(str(fields["url"]))

    tab.append_rows(batch, value_input_option="USER_ENTERED")
    logger.info("batch_create_records('%s'): %d records created.", table_name, len(results))
    return results


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


def _load_url_cache() -> set:
    """Load all existing article URLs into memory (once per session)."""
    global _url_cache
    if _url_cache is None:
        tab = _get_tab("Articles")
        all_rows: list[dict] = tab.get_all_records(empty2zero=False, head=1)
        _url_cache = {row.get("url", "") for row in all_rows if row.get("url")}
        logger.info("_load_url_cache: %d existing URLs loaded.", len(_url_cache))
    return _url_cache


def url_exists(url: str) -> bool:
    """Return True if the normalised URL already exists in the Articles tab."""
    return url in _load_url_cache()


def _load_ignored_url_cache() -> set:
    """Load all URLs from the ignored_urls tab into memory (once per session).

    Graceful: if the ignored_urls worksheet does not yet exist (C-7.1 not run),
    logs a warning and returns an empty set. Pipeline must not crash.
    """
    global _ignored_url_cache
    if _ignored_url_cache is None:
        try:
            tab = _get_spreadsheet().worksheet("ignored_urls")
            all_rows: list[dict] = tab.get_all_records(empty2zero=False, head=1)
            _ignored_url_cache = {row.get("url", "") for row in all_rows if row.get("url")}
            logger.info(
                "_load_ignored_url_cache: %d ignored URLs loaded.",
                len(_ignored_url_cache),
            )
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(
                "_load_ignored_url_cache: 'ignored_urls' tab not found — "
                "run scripts/create_ignored_urls_tab.py to create it. "
                "Returning empty set; pipeline continues."
            )
            _ignored_url_cache = set()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "_load_ignored_url_cache: unexpected error reading tab: %s — "
                "returning empty set.",
                exc,
            )
            _ignored_url_cache = set()
    return _ignored_url_cache


def ignored_url_exists(url: str) -> bool:
    """Return True if the URL is present in the ignored_urls tab.

    Returns False (never raises) when the tab is missing or unreadable.
    """
    return url in _load_ignored_url_cache()


def ignore_record(record_id: str, reason: str = "rejected") -> bool:
    """Mark a record as ignored in the articles tab and add its URL to ignored_urls.

    Single-tab architecture: the row stays in the articles tab with
    status='ignored'. The URL is appended to ignored_urls as a crawl blocklist
    entry. The row is never deleted.

    Sequence (strict order):
      1. Read all articles tab values.
      2. Locate the row for record_id in the 'id' column.
      3. Extract url and title_ko from that row.
      4. Set status='ignored' on the articles row via update_record().
      5. Append url + metadata to ignored_urls tab (blocklist entry).
         If this fails → log warning but return True (status was already set).
      6. Update _ignored_url_cache (add url).
      7. Return True on success, False if the articles row was not found or
         the status update failed.

    Args:
        record_id: The UUID in the 'id' column of the articles tab.
        reason:    Short string explaining why the article is being ignored.

    Returns:
        True if the record was successfully marked as ignored; False otherwise.
    """
    try:
        articles_tab = _get_tab("Articles")
        all_values = articles_tab.get_all_values()
    except Exception as exc:  # noqa: BLE001
        logger.error("ignore_record: failed to read articles tab: %s", exc)
        return False

    if not all_values:
        logger.error("ignore_record: articles tab is empty — id=%s", record_id)
        return False

    headers = all_values[0]
    if "id" not in headers:
        logger.error("ignore_record: articles tab has no 'id' column — id=%s", record_id)
        return False

    id_col_idx = headers.index("id")

    # Locate the target row (1-based; row 1 = header, data rows start at 2)
    target_data: Optional[list[str]] = None
    for row in all_values[1:]:
        if len(row) > id_col_idx and row[id_col_idx] == record_id:
            target_data = row
            break

    if target_data is None:
        logger.error("ignore_record: id=%s not found in articles tab.", record_id)
        return False

    # Extract url and title_ko
    url = ""
    title_ko = ""
    if "url" in headers:
        url_idx = headers.index("url")
        url = target_data[url_idx] if len(target_data) > url_idx else ""
    if "title_ko" in headers:
        title_idx = headers.index("title_ko")
        title_ko = target_data[title_idx] if len(target_data) > title_idx else ""

    logger.info("ignore_record: id=%s url=%s reason=%s", record_id, url, reason)

    # Step 4: set status='ignored' in the articles tab row (row stays — single-tab arch)
    try:
        update_record("Articles", record_id, {"status": "ignored"})
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ignore_record: update_record failed for id=%s: %s", record_id, exc
        )
        return False

    # Step 5: append URL to ignored_urls tab (crawl blocklist) — non-fatal if it fails
    try:
        ignored_tab = _get_spreadsheet().worksheet("ignored_urls")
        ignored_tab.append_row(
            [url, title_ko, date.today().isoformat(), reason],
            value_input_option="USER_ENTERED",
        )
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(
            "ignore_record: 'ignored_urls' tab not found — "
            "blocklist not updated but article status set to ignored. id=%s",
            record_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ignore_record: append to ignored_urls failed: %s — "
            "blocklist not updated but article status set to ignored. id=%s",
            exc,
            record_id,
        )

    # Step 6: update in-session cache so ignored_url_exists() stays accurate
    if _ignored_url_cache is not None and url:
        _ignored_url_cache.add(url)

    return True


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
