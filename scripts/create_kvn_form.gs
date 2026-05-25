/**
 * create_kvn_form.gs — One-time Apps Script: creates the KVN article submission form.
 *
 * HOW TO RUN (once only):
 *   1. Open the KVN Google Sheet.
 *   2. Go to Extensions → Apps Script.
 *   3. Paste this entire file into the editor.
 *   4. Click Run → createKVNForm().
 *   5. Authorise when prompted.
 *   6. Copy the form URL from the execution log.
 *
 * After the form is created, set up the submission trigger in kvn_apps_script.gs.
 */

/**
 * Creates the KVN article submission form and links it to the active spreadsheet.
 * Logs the form URL and ID on completion.
 */
function createKVNForm() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  // ── Create the form ──────────────────────────────────────────────────────
  var form = FormApp.create('KVN 기사 제출 (Korea Velvet News)');
  form.setDescription('새 기사를 제출하려면 아래 양식을 작성하세요.');
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setShowLinkToRespondAgain(true);

  // ── Q1: 입력 유형 (required dropdown) ────────────────────────────────────
  form.addListItem()
    .setTitle('입력 유형')
    .setRequired(true)
    .setChoiceValues(['기사 URL', '직접 텍스트 입력', '사진 Drive URL']);

  // ── Q2: 기사 URL (optional short text) ───────────────────────────────────
  form.addTextItem()
    .setTitle('기사 URL')
    .setRequired(false)
    .setHelpText('기사 URL을 입력 유형으로 선택한 경우 URL을 붙여넣으세요. (예: https://...)');

  // ── Q3: 직접 입력 텍스트 (optional long text) ────────────────────────────
  form.addParagraphTextItem()
    .setTitle('직접 입력 텍스트')
    .setRequired(false)
    .setHelpText('직접 텍스트 입력을 선택한 경우 기사 본문을 여기에 붙여넣으세요.');

  // ── Q4: 사진 Drive URL (optional short text) ─────────────────────────────
  form.addTextItem()
    .setTitle('사진 Drive URL')
    .setRequired(false)
    .setHelpText('사진 Drive URL을 선택한 경우 Google Drive 공유 링크를 붙여넣으세요.');

  // ── Link form responses to a dedicated tab in this spreadsheet ───────────
  // Note: the onKVNFormSubmit trigger in kvn_apps_script.gs handles routing
  // responses to the 'articles' tab.  We do NOT link directly to articles
  // because column order and defaults must be managed by the trigger.
  var destSheet = ss.getSheetByName('form_responses');
  if (!destSheet) {
    destSheet = ss.insertSheet('form_responses');
  }
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  // ── Log results ──────────────────────────────────────────────────────────
  var formUrl  = form.getPublishedUrl();
  var editUrl  = form.getEditUrl();
  var formId   = form.getId();

  Logger.log('=== KVN Form Created ===');
  Logger.log('Form ID  : ' + formId);
  Logger.log('Submit URL: ' + formUrl);
  Logger.log('Edit URL : ' + editUrl);
  Logger.log('');
  Logger.log('Next step: open kvn_apps_script.gs and run installTriggers().');
  Logger.log('You will need the Form ID above when installing the FormSubmit trigger.');

  // Store form ID in a named range so installTriggers() can find it automatically.
  var namedRanges = ss.getNamedRanges();
  var existingRange = namedRanges.find(function(nr) { return nr.getName() === 'KVN_FORM_ID'; });
  if (existingRange) {
    existingRange.getRange().setValue(formId);
  } else {
    // Write to a helper cell in the first sheet and name it
    var helperSheet = ss.getSheets()[0];
    // Use a far-right cell unlikely to conflict with data (column Z, row 1)
    var cell = helperSheet.getRange('Z1');
    cell.setValue(formId);
    ss.setNamedRange('KVN_FORM_ID', cell);
  }

  Logger.log('=== DONE — copy the Submit URL above and run installTriggers() next. ===');
}
