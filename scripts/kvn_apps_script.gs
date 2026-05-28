/**
 * kvn_apps_script.gs — KVN Google Sheets Apps Script: two live triggers.
 *
 * TRIGGER 1 — onKVNFormSubmit:
 *   Fires when the KVN submission form is submitted.
 *   Maps form answers to the 'articles' tab and inserts a new row.
 *
 * TRIGGER 2 — onArticleApproved:
 *   Fires on any cell edit in the spreadsheet.
 *   When the 'approved' column in the 'articles' tab is changed:
 *     'YES' → status = "approved"
 *     'NO'  → status = "pending_review"  (unless status is already protected)
 *
 * SETUP:
 *   1. Open the KVN Google Sheet → Extensions → Apps Script.
 *   2. Paste this entire file (replace any existing code).
 *   3. Run createKVNForm() once (creates the submission form).
 *   4. Run installTriggers() once.
 *   5. Authorise when prompted.
 *
 * NOTE: After running installTriggers(), do NOT manually add triggers in the
 *       Apps Script dashboard — duplicates will cause double-writes.
 */

// ── Column index constants (0-based) ─────────────────────────────────────────
// These must match the column order in ARTICLES_HEADERS in setup_sheets.py.

var COL = {
  APPROVED:           0,   // A — YES/NO dropdown
  TITLE_KO:           1,   // B
  STATUS:             2,   // C — submitted | pending_review | approved | translated | published | translation_failed | ignored
  PUBLISHED_DATE:     3,   // D
  SOURCE_NAME:        4,   // E
  RELEVANCE_SCORE:    5,   // F
  IS_PRODUCT_NEWS:    6,   // G
  URL:                7,   // H
  RECOMMENDATION:     8,   // I
  IS_CLUSTER_REP:     9,   // J
  CLUSTER_ID:         10,  // K
  INPUT_TYPE:         11,  // L
  BODY_KO:            12,  // M
  TITLE_EN:           13,  // N
  BODY_EN:            14,  // O
  WHY_IT_MATTERS:     15,  // P
  SOURCE_ATTRIBUTION: 16,  // Q
  CATEGORY:           17,  // R
  SOURCE_TYPE:        18,  // S
  TAGS_INTERNAL:      19,  // T
  IMAGE_URL:          20,  // U
  PHOTO_DRIVE_URL:    21,  // V
  DIRECT_TEXT:        22,  // W
  MONTH_KEY:          23,  // X
  GLOSSARY_VALIDATED: 24,  // Y
  CLASSIFIER_FEEDBACK:25,  // Z
  ID:                 26,  // AA
};

var TOTAL_COLS = 27;  // Must equal length of ARTICLES_HEADERS in setup_sheets.py.

// Statuses that must not be reverted by changing 'approved' back to NO.
// 'ignored' is protected so that manually ignored articles cannot be
// accidentally re-activated by an approved-column edit.
var PROTECTED_STATUSES = ['published', 'translated', 'ignored'];

// ── Helper: build a blank row array of TOTAL_COLS length ─────────────────────

function _blankRow() {
  var row = [];
  for (var i = 0; i < TOTAL_COLS; i++) {
    row.push('');
  }
  return row;
}


// ── Helper: derive YYYY-MM month key from a date string or Date object ────────

function _monthKey(dateVal) {
  if (!dateVal) return '';
  var d;
  if (dateVal instanceof Date) {
    d = dateVal;
  } else {
    d = new Date(dateVal);
  }
  if (isNaN(d.getTime())) return '';
  var month = ('0' + (d.getMonth() + 1)).slice(-2);
  return d.getFullYear() + '-' + month;
}


// ── Helper: look up header row to find column index by name ──────────────────
// Safety check: ensures the script does not silently write to the wrong column
// if the sheet is ever re-ordered.

function _getHeaderMap(sheet) {
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var map = {};
  for (var i = 0; i < headers.length; i++) {
    map[headers[i]] = i;  // 0-based
  }
  return map;
}


// ── TRIGGER 1: Form submission ────────────────────────────────────────────────

/**
 * onKVNFormSubmit — called by a FormSubmit trigger installed via installTriggers().
 *
 * Expected form fields (by title — bilingual, matching create_kvn_form.gs):
 *   "Input type / 입력 유형"              → dropdown (3 options)
 *   "Article URL / 기사 URL"              → short text
 *   "Direct text / 직접 입력 텍스트"      → paragraph text
 *   "Photo Drive URL / 사진 Drive URL"    → short text
 *
 * @param {GoogleAppsScript.Events.FormsOnFormSubmit} e
 */
function onKVNFormSubmit(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var articlesSheet = ss.getSheetByName('articles');

    if (!articlesSheet) {
      Logger.log('[ERROR] onKVNFormSubmit: "articles" tab not found.');
      return;
    }

    // ── Parse form response ──────────────────────────────────────────────────
    var responses = e.response.getItemResponses();
    var answers = {};
    for (var i = 0; i < responses.length; i++) {
      var item  = responses[i];
      var title = item.getItem().getTitle();
      var ans   = item.getResponse();
      answers[title] = ans || '';
    }

    // BUG FIX (2026-05-28): was `inputTypeKo` (undefined variable) — corrected to `inputTypeRaw`.
    var inputTypeRaw = answers['Input type / 입력 유형']             || '';
    var articleUrl   = answers['Article URL / 기사 URL']             || '';
    var directText   = answers['Direct text / 직접 입력 텍스트']     || '';
    var photoDrive   = answers['Photo Drive URL / 사진 Drive URL']   || '';

    // ── Map bilingual input type label → internal code ────────────────────────
    // Keys must exactly match the choice values in createKVNForm() in create_kvn_form.gs.
    var inputTypeMap = {
      'Article URL / 기사 URL':                'url',
      'Direct text / 직접 입력 텍스트':        'direct_text',
      'Photo Drive URL / 사진 Drive URL':      'photo',
    };
    var inputType = inputTypeMap[inputTypeRaw] || 'url';  // BUG FIX: was inputTypeMap[inputTypeKo]

    // ── Generate UUID (Apps Script built-in) ─────────────────────────────────
    var newId = Utilities.getUuid();

    // ── Submission timestamp for published_date ───────────────────────────────
    var submittedAt = e.response.getTimestamp();
    var publishedDate = Utilities.formatDate(
      submittedAt,
      Session.getScriptTimeZone(),
      'yyyy-MM-dd'
    );
    var monthKey = _monthKey(submittedAt);

    // ── Build row array ───────────────────────────────────────────────────────
    var row = _blankRow();
    row[COL.APPROVED]        = 'NO';   // YES/NO dropdown — new submissions default to NO
    row[COL.STATUS]          = 'submitted';
    row[COL.PUBLISHED_DATE]  = publishedDate;
    row[COL.INPUT_TYPE]      = inputType;
    row[COL.URL]             = articleUrl;
    row[COL.DIRECT_TEXT]     = directText;
    row[COL.PHOTO_DRIVE_URL] = photoDrive;
    row[COL.MONTH_KEY]       = monthKey;
    row[COL.ID]              = newId;

    // ── Safety check: verify column alignment via header map ──────────────────
    var headerMap = _getHeaderMap(articlesSheet);
    if (headerMap['approved'] !== COL.APPROVED || headerMap['id'] !== COL.ID) {
      Logger.log('[WARN] onKVNFormSubmit: header map mismatch — falling back to header-based write.');
      _writeRowByHeaders(articlesSheet, headerMap, {
        approved:        'NO',
        status:          'submitted',
        published_date:  publishedDate,
        input_type:      inputType,
        url:             articleUrl,
        direct_text:     directText,
        photo_drive_url: photoDrive,
        month_key:       monthKey,
        id:              newId,
      });
      return;
    }

    // ── Append row ────────────────────────────────────────────────────────────
    articlesSheet.appendRow(row);
    Logger.log('onKVNFormSubmit: inserted row id=' + newId + ' input_type=' + inputType);

  } catch (err) {
    Logger.log('[ERROR] onKVNFormSubmit: ' + err.toString());
  }
}


/**
 * _writeRowByHeaders — fallback writer that uses the live header map.
 * Avoids silent column-mismatch errors if the sheet is restructured.
 *
 * @param {GoogleAppsScript.Spreadsheet.Sheet} sheet
 * @param {Object} headerMap  — {columnName: 0basedIndex, ...}
 * @param {Object} fields     — {columnName: value, ...}
 */
function _writeRowByHeaders(sheet, headerMap, fields) {
  var totalCols = sheet.getLastColumn();
  var row = [];
  for (var i = 0; i < totalCols; i++) row.push('');

  for (var col in fields) {
    if (Object.prototype.hasOwnProperty.call(fields, col)) {
      var idx = headerMap[col];
      if (idx !== undefined) {
        row[idx] = fields[col];
      }
    }
  }
  sheet.appendRow(row);
}


// ── TRIGGER 2: approved dropdown edit ────────────────────────────────────────

/**
 * onArticleApproved — called by an onEdit trigger installed via installTriggers().
 *
 * Reacts only when:
 *   - The edited sheet is "articles".
 *   - The edited column is the "approved" column (column A, 1-based = 1).
 *   - The edited row is not row 1 (header).
 *
 * Behaviour (YES/NO dropdown — not a checkbox):
 *   approved = 'YES' → status = "approved"
 *   approved = 'NO'  → status = "pending_review"
 *                       (skipped if current status is in PROTECTED_STATUSES)
 *
 * @param {GoogleAppsScript.Events.SheetsOnEdit} e
 */
function onArticleApproved(e) {
  try {
    var sheet = e.range.getSheet();
    if (sheet.getName() !== 'articles') return;

    var row = e.range.getRow();
    var col = e.range.getColumn();  // 1-based

    // Only react to the 'approved' column (column A = 1-based 1).
    // +1 converts 0-based COL.APPROVED to 1-based.
    if (col !== COL.APPROVED + 1) return;
    if (row === 1) return;  // header row

    var approvedValue = String(e.range.getValue()).trim().toUpperCase();
    var isApproved = (approvedValue === 'YES');

    // Status column: COL.STATUS is 0-based; getRange uses 1-based.
    var statusCell = sheet.getRange(row, COL.STATUS + 1);
    var currentStatus = String(statusCell.getValue()).toLowerCase().trim();

    if (isApproved) {
      // Always allow approval regardless of current status.
      statusCell.setValue('approved');
      Logger.log('onArticleApproved: row ' + row + ' approved=YES → status=approved');
    } else {
      // Do not revert if article is already in a protected status.
      if (PROTECTED_STATUSES.indexOf(currentStatus) !== -1) {
        Logger.log(
          'onArticleApproved: row ' + row +
          ' approved=NO but status="' + currentStatus + '" — protected, no change.'
        );
        return;
      }
      statusCell.setValue('pending_review');
      Logger.log('onArticleApproved: row ' + row + ' approved=NO → status=pending_review');
    }

  } catch (err) {
    Logger.log('[ERROR] onArticleApproved: ' + err.toString());
  }
}


// ── Trigger installer ─────────────────────────────────────────────────────────

/**
 * installTriggers — run once from the Apps Script editor after pasting this file.
 *
 * Installs:
 *   1. FormSubmit trigger → onKVNFormSubmit (linked to the form created by createKVNForm)
 *   2. onEdit trigger     → onArticleApproved (on this spreadsheet)
 *
 * Safe to re-run: existing triggers with the same function name are removed first.
 */
function installTriggers() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // ── Remove any existing triggers for these functions ──────────────────────
  var allTriggers = ScriptApp.getProjectTriggers();
  for (var i = 0; i < allTriggers.length; i++) {
    var fn = allTriggers[i].getHandlerFunction();
    if (fn === 'onKVNFormSubmit' || fn === 'onArticleApproved') {
      ScriptApp.deleteTrigger(allTriggers[i]);
      Logger.log('Removed existing trigger: ' + fn);
    }
  }

  // ── Install onEdit trigger ────────────────────────────────────────────────
  ScriptApp.newTrigger('onArticleApproved')
    .forSpreadsheet(ss)
    .onEdit()
    .create();
  Logger.log('Installed onEdit trigger → onArticleApproved');

  // ── Install FormSubmit trigger ────────────────────────────────────────────
  // Retrieve the Form ID stored by createKVNForm() in the named range KVN_FORM_ID.
  var formId = _getFormId(ss);

  if (!formId) {
    Logger.log('[WARN] KVN_FORM_ID named range not found or empty.');
    Logger.log('       Run createKVNForm() first, then re-run installTriggers().');
    Logger.log('[ERROR] Run createKVNForm() first, then re-run installTriggers().');
    return;
  }

  var form = FormApp.openById(formId);
  ScriptApp.newTrigger('onKVNFormSubmit')
    .forForm(form)
    .onFormSubmit()
    .create();
  Logger.log('Installed FormSubmit trigger → onKVNFormSubmit (form: ' + formId + ')');

  Logger.log('=== installTriggers() COMPLETE ===');
  Logger.log('1. onArticleApproved — onEdit (spreadsheet)');
  Logger.log('2. onKVNFormSubmit   — FormSubmit (KVN form)');
  Logger.log('Check Extensions → Apps Script → Triggers to confirm.');
}


/**
 * _getFormId — reads the KVN_FORM_ID from the spreadsheet named range.
 *
 * @param {GoogleAppsScript.Spreadsheet.Spreadsheet} ss
 * @returns {string|null}
 */
function _getFormId(ss) {
  try {
    var namedRanges = ss.getNamedRanges();
    for (var i = 0; i < namedRanges.length; i++) {
      if (namedRanges[i].getName() === 'KVN_FORM_ID') {
        var val = namedRanges[i].getRange().getValue();
        return val ? String(val).trim() : null;
      }
    }
  } catch (err) {
    Logger.log('[ERROR] _getFormId: ' + err.toString());
  }
  return null;
}
