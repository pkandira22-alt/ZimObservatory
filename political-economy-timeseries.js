const TIME_SERIES_STORAGE_KEY = 'kuvhura-political-time-series-v1';
const TIME_SERIES_MAX_ROWS = 5000;
const TIME_SERIES_MAX_FILE_BYTES = 2 * 1024 * 1024;
const TIME_SERIES_COLUMNS = ['series', 'period', 'metric', 'value', 'unit', 'source', 'source_url'];
const POLITICAL_TIME_SERIES = {
  'fx-inflation': {
    title: 'Parallel FX premium + monthly inflation',
    equation: 'Drivers: Rent Extraction (E) and Patronage Load (Pr).',
    guidance: 'Record the FX premium as (parallel rate − official rate) ÷ official rate × 100 and cite both quotes. Identify CPI as month-on-month or year-on-year; do not mix definitions.',
    color: '#FBBF24',
    metrics: {
      parallel_fx_premium_pct: 'Parallel-market FX premium',
      monthly_cpi_mom_pct: 'Monthly CPI inflation (MoM)',
      monthly_cpi_yoy_pct: 'Monthly CPI inflation (YoY)'
    },
    references: [
      {
        label: 'ZIMSTAT monthly CPI releases',
        url: 'https://zimstat.co.zw/consumer-price-index/',
        note: 'PDF/XLS releases; check currency, weights, and methodology before joining periods.'
      },
      {
        label: 'RBZ official exchange rates',
        url: 'https://www.rbz.co.zw/index.php/research/markets/exchange-rates',
        note: 'Official rates only; a matching historical parallel-market series was not identified.'
      },
      {
        label: 'World Bank annual CPI API',
        url: 'https://api.worldbank.org/v2/country/ZW/indicator/FP.CPI.TOTL.ZG?format=json&per_page=200',
        note: 'Annual fallback only; recent observations may be null or stale.'
      }
    ]
  },
  'remittance-purchasing-power': {
    title: 'Remittances + civil-service purchasing power',
    equation: 'Driver: Diaspora Buffer (DB).',
    guidance: 'Record remittance inflows and a civil-service real-pay measure. Put the purchasing-power index base period in its unit (for example, index points with base=100); do not infer salary values.',
    color: '#38BDF8',
    metrics: {
      remittances_received: 'Remittance inflows',
      civil_service_real_pay: 'Civil-service real purchasing power'
    },
    references: [
      {
        label: 'World Bank annual remittances API',
        url: 'https://api.worldbank.org/v2/country/ZW/indicator/BX.TRF.PWKR.CD.DT?format=json&per_page=200',
        note: 'Annual current US$; includes personal transfers and compensation of employees.'
      }
    ]
  },
  'oag-leakage': {
    title: 'Auditor-General unvouched leakage',
    equation: 'Driver: Rent Extraction (E) and institutional impunity.',
    guidance: 'Use only amounts explicitly reported by a source, in a consistent currency and definition. Do not double-count an expenditure and its procurement bypass or asset transfer. 2030 is a future horizon, not an observation.',
    color: '#F87171',
    metrics: {
      unvouched_expenditure: 'Unvouched expenditure',
      procurement_bypass: 'Procurement bypass amount',
      parastatal_asset_transfer: 'Parastatal asset transfer'
    },
    references: [
      {
        label: 'Auditor-General document library',
        url: 'https://auditorgeneral.gov.zw/document-library/',
        note: 'Year-labeled report PDFs are documents, not a standardized leakage dataset.'
      },
      {
        label: 'Auditor-General library API',
        url: 'https://auditorgeneral.gov.zw/wp-json/wp/v2/pages/262',
        note: 'Machine-readable index links to reports; 2030 is future and cannot be an observed value.'
      }
    ]
  },
  'narrative-throttling': {
    title: 'Narrative velocity + state throttling',
    equation: 'Drivers: Social Influence (I) and Social Control (C).',
    guidance: 'Use a consistent weekly sampling frame for mention counts. Record throttling only when a source documents a measurement or event, and state its original unit; do not synthesize a throttling index.',
    color: '#A78BFA',
    metrics: {
      weekly_narrative_mentions: 'Weekly narrative mentions',
      throttling_measure: 'Documented throttling measure'
    },
    references: [
      {
        label: 'GDELT DOC API',
        url: 'https://api.gdeltproject.org/api/v2/doc/doc?query=Zimbabwe&mode=timelinevol&format=json',
        note: 'News-coverage volume proxy, not public opinion or social-media post counts.'
      },
      {
        label: 'OONI Zimbabwe measurements',
        url: 'https://api.ooni.io/api/v1/measurements?probe_cc=ZW&limit=2',
        note: 'Individual network measurements; anomalies do not by themselves prove state throttling or attribution. The existing sheet bridge replaces its current snapshot rather than retaining history.'
      }
    ]
  }
};

let timeSeriesObservations = [];
let timeSeriesChart = null;
let timeSeriesCutoff = null;

function parseTimeSeriesCsv(text) {
  const rows = [];
  let row = [];
  let field = '';
  let inQuotes = false;
  const input = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');

  for (let index = 0; index < input.length; index++) {
    const character = input[index];
    if (inQuotes) {
      if (character === '"' && input[index + 1] === '"') {
        field += '"';
        index++;
      } else if (character === '"') {
        inQuotes = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field.length === 0) {
      inQuotes = true;
    } else if (character === ',') {
      row.push(field.trim());
      field = '';
    } else if (character === '\n') {
      row.push(field.trim());
      if (row.some(value => value !== '')) rows.push(row);
      row = [];
      field = '';
    } else {
      field += character;
    }
  }
  if (inQuotes) throw new Error('The CSV contains an unclosed quoted field.');
  row.push(field.trim());
  if (row.some(value => value !== '')) rows.push(row);
  return rows;
}

function timeSeriesPeriodTimestamp(period) {
  let match = period.match(/^(\d{4})$/);
  if (match) return Date.UTC(Number(match[1]), 0, 1);

  match = period.match(/^(\d{4})-(\d{2})$/);
  if (match && Number(match[2]) >= 1 && Number(match[2]) <= 12) {
    return Date.UTC(Number(match[1]), Number(match[2]) - 1, 1);
  }

  match = period.match(/^(\d{4})-Q([1-4])$/i);
  if (match) return Date.UTC(Number(match[1]), (Number(match[2]) - 1) * 3, 1);

  match = period.match(/^(\d{4})-W(\d{2})$/i);
  if (match && Number(match[2]) >= 1 && Number(match[2]) <= 53) {
    const year = Number(match[1]);
    const jan4 = Date.UTC(year, 0, 4);
    const weekOneMonday = jan4 - ((new Date(jan4).getUTCDay() + 6) % 7) * 86400000;
    return weekOneMonday + (Number(match[2]) - 1) * 7 * 86400000;
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(period)) {
    const timestamp = Date.parse(`${period}T00:00:00Z`);
    if (Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === period) return timestamp;
  }
  return NaN;
}

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function setTimeSeriesStatus(message, isError = false) {
  const status = document.getElementById('timeSeriesStatus');
  status.textContent = message;
  status.style.color = isError ? '#F87171' : 'var(--text-muted)';
}

function downloadTimeSeriesCsv(filename, rows) {
  const content = [TIME_SERIES_COLUMNS, ...rows].map(row => row.map(csvEscape).join(',')).join('\r\n');
  const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function renderPoliticalTimeSeries(resetCutoff = false) {
  const seriesId = document.getElementById('timeSeriesSelect').value;
  const series = POLITICAL_TIME_SERIES[seriesId];
  const range = document.getElementById('timeSeriesRange');
  const through = document.getElementById('timeSeriesThrough');
  const start = document.getElementById('timeSeriesStart');
  const end = document.getElementById('timeSeriesEnd');
  const description = document.getElementById('timeSeriesDescription');
  const referenceContainer = document.getElementById('timeSeriesReferenceSources');
  const sources = document.getElementById('timeSeriesSources');

  description.textContent = `${series.equation} ${series.guidance}`;
  referenceContainer.replaceChildren();
  series.references.forEach(reference => {
    const item = document.createElement('div');
    item.className = 'time-series-source';
    const link = document.createElement('a');
    link.href = reference.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = reference.label;
    item.append(link, document.createTextNode(` · ${reference.note}`));
    referenceContainer.append(item);
  });
  const observations = timeSeriesObservations
    .filter(item => item.series === seriesId)
    .sort((a, b) => timeSeriesPeriodTimestamp(a.period) - timeSeriesPeriodTimestamp(b.period));
  const periods = [...new Map(observations.map(item => [
    item.period,
    timeSeriesPeriodTimestamp(item.period)
  ]))].map(([period, timestamp]) => ({ period, timestamp }))
    .sort((a, b) => a.timestamp - b.timestamp);

  if (!periods.length) {
    range.min = '0';
    range.max = '0';
    range.value = '0';
    range.disabled = true;
    through.textContent = 'No observations';
    start.textContent = 'Start —';
    end.textContent = 'Latest —';
    sources.replaceChildren();
    if (timeSeriesChart) {
      timeSeriesChart.destroy();
      timeSeriesChart = null;
    }
    setTimeSeriesStatus(`No source-attributed observations loaded for ${series.title}. Import a CSV; no estimates or future values are generated.`);
    return;
  }

  range.disabled = false;
  range.min = '0';
  range.max = String(periods.length - 1);
  let selectedIndex = periods.length - 1;
  if (!resetCutoff && timeSeriesCutoff !== null) {
    const priorIndex = periods.findIndex(item => item.timestamp > timeSeriesCutoff);
    selectedIndex = priorIndex === -1 ? periods.length - 1 : Math.max(0, priorIndex - 1);
  }
  range.value = String(selectedIndex);
  const selectedPeriod = periods[selectedIndex];
  timeSeriesCutoff = selectedPeriod.timestamp;
  through.textContent = `Through ${selectedPeriod.period}`;
  start.textContent = `Start ${periods[0].period}`;
  end.textContent = `Latest ${periods[periods.length - 1].period}`;

  const visiblePeriods = periods.slice(0, selectedIndex + 1);
  const visibleLabels = new Set(visiblePeriods.map(item => item.period));
  const visibleObservations = observations.filter(item => visibleLabels.has(item.period));
  const unitList = [...new Set(visibleObservations.map(item => item.unit))];
  const unitAxis = new Map(unitList.map((unit, index) => [unit, `timeSeriesY${index}`]));
  const grouped = new Map();
  for (const observation of visibleObservations) {
    const key = `${observation.metric}\u0000${observation.unit}`;
    if (!grouped.has(key)) grouped.set(key, new Map());
    grouped.get(key).set(observation.period, observation.value);
  }

  const datasets = [...grouped.entries()].map(([key, values]) => {
    const [metric, unit] = key.split('\u0000');
    const metricIndex = Object.keys(series.metrics).indexOf(metric);
    const color = metricIndex < 0 ? series.color : [
      series.color, '#34D399', '#FBBF24'
    ][metricIndex % 3];
    return {
      label: `${series.metrics[metric]} (${unit})`,
      data: visiblePeriods.map(item => values.has(item.period) ? values.get(item.period) : null),
      borderColor: color,
      backgroundColor: color,
      pointRadius: 2,
      pointHoverRadius: 5,
      borderWidth: 2,
      tension: 0.15,
      spanGaps: false,
      yAxisID: unitAxis.get(unit)
    };
  });

  const scales = {
    x: {
      ticks: { color: '#94A3B8', maxRotation: 0, autoSkip: true },
      grid: { color: '#1E293B' }
    }
  };
  unitList.forEach((unit, index) => {
    scales[unitAxis.get(unit)] = {
      type: 'linear',
      position: index === 0 ? 'left' : 'right',
      title: { display: true, text: unit, color: '#94A3B8' },
      ticks: { color: '#94A3B8' },
      grid: { drawOnChartArea: index === 0, color: '#1E293B' }
    };
  });

  const chartConfiguration = {
    type: 'line',
    data: { labels: visiblePeriods.map(item => item.period), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { position: 'top', labels: { color: '#CBD5E1', boxWidth: 10, font: { size: 10 } } }
      },
      scales
    }
  };
  if (timeSeriesChart) {
    timeSeriesChart.data = chartConfiguration.data;
    timeSeriesChart.options = chartConfiguration.options;
    timeSeriesChart.update();
  } else {
    timeSeriesChart = new Chart(document.getElementById('politicalTimeSeriesChart'), chartConfiguration);
  }

  sources.replaceChildren();
  visibleObservations.slice(-12).reverse().forEach(observation => {
    const item = document.createElement('div');
    item.className = 'time-series-source';
    const label = document.createElement('strong');
    label.textContent = `${observation.period} · ${series.metrics[observation.metric]}: ${observation.value.toLocaleString()} ${observation.unit}`;
    const source = document.createElement('a');
    source.href = observation.source_url;
    source.target = '_blank';
    source.rel = 'noopener noreferrer';
    source.textContent = observation.source;
    item.append(label, document.createTextNode(' · '), source);
    sources.append(item);
  });

  setTimeSeriesStatus(
    `${visibleObservations.length} source-attributed observations through ${selectedPeriod.period}. Drivers shown here are not historical Φ or Praxis values.`
  );
}

async function importPoliticalTimeSeriesCsv(file) {
  if (file.size > TIME_SERIES_MAX_FILE_BYTES) {
    throw new Error('CSV files must be no larger than 2 MB.');
  }
  const rows = parseTimeSeriesCsv(await file.text());
  const header = rows.shift()?.map(value => value.toLowerCase());
  if (!header || header.length !== TIME_SERIES_COLUMNS.length ||
    TIME_SERIES_COLUMNS.some((column, index) => header[index] !== column)) {
    throw new Error(`CSV header must be: ${TIME_SERIES_COLUMNS.join(', ')}`);
  }
  if (rows.length > TIME_SERIES_MAX_ROWS) {
    throw new Error(`CSV files may contain at most ${TIME_SERIES_MAX_ROWS} observations.`);
  }

  const batch = [];
  const uniqueRows = new Set();
  for (const row of rows) {
    const cells = TIME_SERIES_COLUMNS.map((_, index) => row[index] || '');
    if (!cells[1] && !cells[3] && !cells[4] && !cells[5] && !cells[6]) continue;
    if (row.length !== TIME_SERIES_COLUMNS.length) {
      throw new Error('Each non-empty CSV row must have exactly seven columns.');
    }
    const [series, period, metric, rawValue, unit, source, sourceUrl] = cells;
    if (!POLITICAL_TIME_SERIES[series]) throw new Error(`Unknown series "${series}".`);
    if (!Object.hasOwn(POLITICAL_TIME_SERIES[series].metrics, metric)) {
      throw new Error(`Unknown metric "${metric}" for ${series}.`);
    }
    const timestamp = timeSeriesPeriodTimestamp(period);
    const value = Number(rawValue);
    if (!Number.isFinite(timestamp)) throw new Error(`Invalid period "${period}". Use YYYY, YYYY-Q1, YYYY-MM, YYYY-W01, or YYYY-MM-DD.`);
    if (timestamp > Date.now()) throw new Error(`Future period "${period}" is not accepted as an observation.`);
    if (!rawValue || !Number.isFinite(value)) throw new Error(`The value for ${metric} at ${period} must be a finite number.`);
    if (!unit || unit.length > 40) throw new Error('Each value needs a unit of at most 40 characters.');
    if (!source || source.length > 160) throw new Error('Each value needs a source name of at most 160 characters.');
    let parsedSourceUrl;
    try {
      parsedSourceUrl = new URL(sourceUrl);
    } catch {
      throw new Error(`The source URL for ${period} must be HTTP(S).`);
    }
    if (!['http:', 'https:'].includes(parsedSourceUrl.protocol)) {
      throw new Error(`The source URL for ${period} must be HTTP(S).`);
    }
    const key = `${series}\u0000${period}\u0000${metric}`;
    if (uniqueRows.has(key)) throw new Error(`Duplicate observation for ${series}, ${period}, ${metric}.`);
    uniqueRows.add(key);
    batch.push({
      series,
      period,
      metric,
      value,
      unit,
      source,
      source_url: parsedSourceUrl.href
    });
  }
  if (!batch.length) throw new Error('No observations found. Fill in at least one sourced data row in the CSV.');

  const storage = window.localStorage;
  const stored = JSON.parse(storage.getItem(TIME_SERIES_STORAGE_KEY) || '[]');
  if (!Array.isArray(stored)) throw new Error('Stored time-series data is invalid; clear this browser’s site data and retry.');
  const replacements = new Set(batch.map(item => `${item.series}\u0000${item.period}\u0000${item.metric}`));
  const merged = [
    ...stored.filter(item => !replacements.has(`${item.series}\u0000${item.period}\u0000${item.metric}`)),
    ...batch
  ];
  if (merged.length > TIME_SERIES_MAX_ROWS) {
    throw new Error(`The browser can store at most ${TIME_SERIES_MAX_ROWS} observations.`);
  }
  storage.setItem(TIME_SERIES_STORAGE_KEY, JSON.stringify(merged));
  timeSeriesObservations = merged;
  timeSeriesCutoff = null;
  return batch.length;
}

function downloadPoliticalTimeSeriesTemplate() {
  const rows = Object.entries(POLITICAL_TIME_SERIES).flatMap(([series, definition]) =>
    Object.keys(definition.metrics).map(metric => [series, '', metric, '', '', '', ''])
  );
  downloadTimeSeriesCsv('kuvhura-time-series-template.csv', rows);
}

function exportPoliticalTimeSeries() {
  const seriesId = document.getElementById('timeSeriesSelect').value;
  const rows = timeSeriesObservations
    .filter(item => item.series === seriesId)
    .map(item => TIME_SERIES_COLUMNS.map(column => item[column]));
  if (!rows.length) {
    setTimeSeriesStatus('There are no observations for this series to export.');
    return;
  }
  downloadTimeSeriesCsv(`kuvhura-${seriesId}-observations.csv`, rows);
}

function clearPoliticalTimeSeries() {
  const seriesId = document.getElementById('timeSeriesSelect').value;
  if (!window.confirm(`Clear locally stored observations for ${POLITICAL_TIME_SERIES[seriesId].title}?`)) return;
  const retained = timeSeriesObservations.filter(item => item.series !== seriesId);
  try {
    window.localStorage.setItem(TIME_SERIES_STORAGE_KEY, JSON.stringify(retained));
    timeSeriesObservations = retained;
    timeSeriesCutoff = null;
    renderPoliticalTimeSeries(true);
    setTimeSeriesStatus(`Cleared locally stored observations for ${POLITICAL_TIME_SERIES[seriesId].title}.`);
  } catch (error) {
    setTimeSeriesStatus(`Could not clear local observations: ${error.message}`, true);
  }
}

function initPoliticalEconomyTimeSeries() {
  const select = document.getElementById('timeSeriesSelect');
  const range = document.getElementById('timeSeriesRange');
  const fileInput = document.getElementById('timeSeriesFile');
  select.addEventListener('change', () => {
    timeSeriesCutoff = null;
    renderPoliticalTimeSeries(true);
  });
  range.addEventListener('input', () => {
    const selected = [...new Map(timeSeriesObservations
      .filter(item => item.series === select.value)
      .map(item => [item.period, timeSeriesPeriodTimestamp(item.period)]))]
      .sort((a, b) => a[1] - b[1]);
    timeSeriesCutoff = selected[Number(range.value)]?.[1] ?? null;
    renderPoliticalTimeSeries();
  });
  document.getElementById('timeSeriesTemplate').addEventListener('click', downloadPoliticalTimeSeriesTemplate);
  document.getElementById('timeSeriesExport').addEventListener('click', exportPoliticalTimeSeries);
  document.getElementById('timeSeriesClear').addEventListener('click', clearPoliticalTimeSeries);
  document.getElementById('timeSeriesImport').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const count = await importPoliticalTimeSeriesCsv(file);
      renderPoliticalTimeSeries(true);
      setTimeSeriesStatus(`Imported ${count} source-attributed observations. Data is stored only in this browser.`);
    } catch (error) {
      setTimeSeriesStatus(error.message, true);
    } finally {
      fileInput.value = '';
    }
  });

  try {
    const stored = JSON.parse(window.localStorage.getItem(TIME_SERIES_STORAGE_KEY) || '[]');
    if (!Array.isArray(stored)) throw new Error('Stored time-series data is invalid.');
    timeSeriesObservations = stored;
    renderPoliticalTimeSeries(true);
  } catch (error) {
    setTimeSeriesStatus(`Could not load local time-series data: ${error.message}`, true);
  }
}

document.addEventListener('DOMContentLoaded', initPoliticalEconomyTimeSeries);
