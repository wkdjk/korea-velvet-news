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
  var form = FormApp.create('KVN article submission / KVN 기사 제출');
  form.setDescription('Submit a new article for Korea Velvet News. / 새 기사를 제출하세요.');
  form.setCollectEmail(false);
  form.setLimitOneResponsePerUser(false);
  form.setShowLinkToRespondAgain(true);

  // ── Q1: Input type / 입력 유형 (required dropdown) ────────────────────────
  form.addListItem()
    .setTitle('Input type / 입력 유형')
    .setRequired(true)
    .setChoiceValues([
      'Article URL / 기사 URL',
      'Direct text / 직접 입력 텍스트',
      'Photo Drive URL / 사진 Drive URL',
    ]);

  // ── Q2: Article URL / 기사 URL (optional short text) ─────────────────────
  form.addTextItem()
    .setTitle('Article URL / 기사 URL')
    .setRequired(false)
    .setHelpText('Paste the article URL. / 기사 URL을 붙여넣으세요. (예: https://...)');

  // ── Q3: Direct text / 직접 입력 텍스트 (optional long text) ──────────────
  form.addParagraphTextItem()
    .setTitle('Direct text / 직접 입력 텍스트')
    .setRequired(false)
    .setHelpText('Paste the full article body. / 기사 본문을 붙여넣으세요.');

  // ── Q4: Photo Drive URL / 사진 Drive URL (optional short text) ───────────
  form.addTextItem()
    .setTitle('Photo Drive URL / 사진 Drive URL')
    .setRequired(false)
    .setHelpText('Paste the Google Drive share link. / Google Drive 공유 링크를 붙여넣으세요.');

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
