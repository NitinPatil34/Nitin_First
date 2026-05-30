const SHEET_NAME = 'Nickel Prices';
const HEADERS = [
  'Fetched At UTC',
  'Value',
  'Unit',
  'Price Date',
];

function doPost(e) {
  const payload = JSON.parse((e.postData && e.postData.contents) || '{}');
  const expectedSecret = PropertiesService.getScriptProperties().getProperty('NICKEL_SHEETS_SHARED_SECRET');

  if (expectedSecret && payload.secret !== expectedSecret) {
    return jsonResponse({ ok: false, error: 'Unauthorized' });
  }

  const rows = Array.isArray(payload.rows) ? payload.rows : [];
  if (rows.length === 0) {
    return jsonResponse({ ok: false, error: 'No rows supplied' });
  }

  const spreadsheet = getTargetSpreadsheet();
  const sheet = getTargetSheet(spreadsheet);
  ensureHeaderRow(sheet);

  const values = rows.map((row) => [
    row.fetched_at_utc || '',
    row.value || '',
    row.unit || '',
    row.price_date || '',
  ]);
  sheet.getRange(sheet.getLastRow() + 1, 1, values.length, HEADERS.length).setValues(values);

  return jsonResponse({
    ok: true,
    rowsAppended: values.length,
    spreadsheetId: spreadsheet.getId(),
    sheetName: sheet.getName(),
  });
}

function getTargetSpreadsheet() {
  const spreadsheetId = PropertiesService.getScriptProperties().getProperty('NICKEL_SPREADSHEET_ID');
  if (spreadsheetId) {
    return SpreadsheetApp.openById(spreadsheetId);
  }
  return SpreadsheetApp.getActiveSpreadsheet();
}

function getTargetSheet(spreadsheet) {
  const namedSheet = spreadsheet.getSheetByName(SHEET_NAME);
  if (namedSheet) {
    return namedSheet;
  }

  const firstSheet = spreadsheet.getSheets()[0];
  if (isSheetEmpty(firstSheet)) {
    firstSheet.setName(SHEET_NAME);
    return firstSheet;
  }

  return spreadsheet.insertSheet(SHEET_NAME);
}

function isSheetEmpty(sheet) {
  return sheet.getLastRow() === 0 && sheet.getLastColumn() === 0;
}

function ensureHeaderRow(sheet) {
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    return;
  }

  const currentHeaders = sheet.getRange(1, 1, 1, HEADERS.length).getValues()[0];
  const hasHeaders = HEADERS.every((header, index) => currentHeaders[index] === header);
  if (!hasHeaders) {
    // Switching from the old multi-product sheet layout to the focused tracker.
    sheet.clearContents();
    sheet.appendRow(HEADERS);
  }
}

function jsonResponse(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
