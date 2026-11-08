function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function getTelemetrySheet() {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getSheetByName("SocialTelemetry");
  if (!sheet) {
    sheet = spreadsheet.insertSheet("SocialTelemetry");
  }
  return sheet;
}

function doPost(e) {
  var expectedToken = PropertiesService.getScriptProperties().getProperty("SYNC_TOKEN");
  if (!expectedToken) {
    return jsonResponse({status: "error", message: "SYNC_TOKEN is not configured"});
  }

  var data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (error) {
    return jsonResponse({status: "error", message: "Invalid JSON payload"});
  }

  if (data.token !== expectedToken) {
    return jsonResponse({status: "error", message: "Unauthorized"});
  }
  if (!Array.isArray(data.rows) || data.rows.some(function(row) {
    return !Array.isArray(row) || row.length !== 5;
  })) {
    return jsonResponse({status: "error", message: "Invalid telemetry rows"});
  }

  var lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) {
    return jsonResponse({status: "error", message: "Another sync is in progress"});
  }

  try {
    var sheet = getTelemetrySheet();
    var values = [[
      "Timestamp",
      "Hashtag / Vector",
      "Mention_Count",
      "Narrative_Velocity",
      "Polarization_Index"
    ]].concat(data.rows);
    sheet.clearContents();
    sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
    return jsonResponse({status: "success"});
  } finally {
    lock.releaseLock();
  }
}

function doGet() {
  var sheet = getTelemetrySheet();
  var values = sheet.getDataRange().getValues();
  var rows = values.length > 1 ? values.slice(1) : [];
  return jsonResponse({
    available: rows.length > 0,
    rows: rows,
    updatedAt: rows.length ? rows[0][0] : null
  });
}
