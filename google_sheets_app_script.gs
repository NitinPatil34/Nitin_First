const SHEET_NAME = 'Nickel Prices';
const HEADERS = [
  'Fetched At UTC',
  'Value',
  'Unit',
  'Price Date',
  'Cell Price %',
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

  const startRow = sheet.getLastRow() + 1;
  const values = rows.map((row, index) => {
    const sheetRow = startRow + index;
    return [
      row.fetched_at_utc || '',
      parsePriceValue(row.value),
      row.unit || '',
      row.price_date || '',
      `=((B${sheetRow}*0.013*10^-3)/1.45)*100`,
    ];
  });
  sheet.getRange(startRow, 1, values.length, HEADERS.length).setValues(values);

  return jsonResponse({
    ok: true,
    rowsAppended: values.length,
    spreadsheetId: spreadsheet.getId(),
    sheetName: sheet.getName(),
  });
}

function parsePriceValue(value) {
  const normalized = String(value || '').replace(/,/g, '').trim();
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : value || '';
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
    // Switching from an older layout to the focused tracker with calculated percentage.
    sheet.clearContents();
    sheet.appendRow(HEADERS);
  }
}

function jsonResponse(body) {
  return ContentService
    .createTextOutput(JSON.stringify(body))
    .setMimeType(ContentService.MimeType.JSON);
}
