const TIME_SERIES_STORAGE_KEY = 'kuvhura-political-time-series-v1';
const TIME_SERIES_MAX_ROWS = 5000;
const TIME_SERIES_MAX_FILE_BYTES = 2 * 1024 * 1024;
const TIME_SERIES_COLUMNS = ['series', 'period', 'metric', 'value', 'unit', 'source', 'source_url'];
const POLITICAL_TIME_SERIES = {
  'fx-inflation': {
    title: 'Parallel FX premium + CPI inflation',
    equation: 'Drivers: Rent Extraction (E) and Patronage Load (Pr).',
    guidance: 'Tracks parallel-market FX spread (%) alongside official annual/monthly CPI inflation (%). Import custom CSV observations to overlay higher-frequency monthly readings.',
    color: '#FBBF24',
    metrics: {
      parallel_fx_premium_pct: 'Parallel-market FX premium',
      monthly_cpi_mom_pct: 'Monthly CPI inflation (MoM)',
      monthly_cpi_yoy_pct: 'CPI inflation (YoY)'
    },
    references: [
      {
        label: 'ZIMSTAT Consumer Price Index',
        url: 'https://zimstat.co.zw/consumer-price-index/',
        note: 'Official national CPI releases.'
      },
      {
        label: 'RBZ official exchange rates',
        url: 'https://www.rbz.co.zw/index.php/research/markets/exchange-rates',
        note: 'Official interbank & ZiG reference rates.'
      },
      {
        label: 'World Bank annual CPI API',
        url: 'https://api.worldbank.org/v2/country/ZW/indicator/FP.CPI.TOTL.ZG?format=json&per_page=200',
        note: 'Live World Bank v2 CPI indicator for Zimbabwe (ZW).'
      }
    ]
  },
  'remittance-purchasing-power': {
    title: 'Remittances + civil-service purchasing power',
    equation: 'Driver: Diaspora Buffer (DB).',
    guidance: 'Tracks diaspora remittance inflows (USD millions) alongside civil-service real purchasing power (Index, 2018=100).',
    color: '#38BDF8',
    metrics: {
      remittances_received: 'Remittance inflows',
      civil_service_real_pay: 'Civil-service real purchasing power'
    },
    references: [
      {
        label: 'World Bank annual remittances API',
        url: 'https://api.worldbank.org/v2/country/ZW/indicator/BX.TRF.PWKR.CD.DT?format=json&per_page=200',
        note: 'Live World Bank personal remittances series for Zimbabwe.'
      },
      {
        label: 'Ministry of Finance & Economic Development',
        url: 'https://www.zimtreasury.co.zw/',
        note: 'Fiscal wage reviews and mid-year budget statements.'
      }
    ]
  },
  'oag-leakage': {
    title: 'Auditor-General unvouched leakage',
    equation: 'Driver: Rent Extraction (E) and institutional impunity.',
    guidance: 'Observed annual Office of the Auditor-General (OAG) audit findings in USD millions (2018–2024 observed audits only; future horizons excluded).',
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
        note: 'Annual OAG Zimbabwe narrative and financial audit reports.'
      },
      {
        label: 'Auditor-General library API',
        url: 'https://auditorgeneral.gov.zw/wp-json/wp/v2/pages/262',
        note: 'Machine-readable index linking official published audit PDFs.'
      }
    ]
  },
  'narrative-throttling': {
    title: 'Narrative velocity + state throttling',
    equation: 'Drivers: Social Influence (I) and Social Control (C).',
    guidance: 'Tracks political-economy media/narrative volume (GDELT DOC timeline) alongside documented OONI Zimbabwe network anomaly/throttling events.',
    color: '#A78BFA',
    metrics: {
      weekly_narrative_mentions: 'Political-economy narrative volume',
      throttling_measure: 'Documented throttling / OONI anomalies'
    },
    references: [
      {
        label: 'GDELT DOC API (Zimbabwe political economy)',
        url: 'https://api.gdeltproject.org/api/v2/doc/doc?query=Zimbabwe&mode=timelinevol&format=json',
        note: 'Live weekly political-economy coverage velocity index.'
      },
      {
        label: 'OONI Zimbabwe measurements',
        url: 'https://api.ooni.io/api/v1/measurements?probe_cc=ZW&anomaly=true&limit=50',
        note: 'Open Observatory of Network Interference measurements for ZW.'
      }
    ]
  }
};

let serverTimeSeriesObservations = [];
let customTimeSeriesObservations = [];
let timeSeriesChart = null;
let timeSeriesChartMode = 'line';
let timeSeriesCutoff = null;

function getMergedTimeSeriesObservations() {
  const byKey = new Map();
  for (const item of serverTimeSeriesObservations) {
    byKey.set(`${item.series}\u0000${item.period}\u0000${item.metric}`, item);
  }
  for (const item of customTimeSeriesObservations) {
    byKey.set(`${item.series}\u0000${item.period}\u0000${item.metric}`, item);
  }
  return [...byKey.values()];
}

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
  const value = String(period || '').trim();
  let match = value.match(/^(\d{4})$/);
  if (match) return Date.UTC(Number(match[1]), 0, 1);

  match = value.match(/^(\d{4})-(\d{2})$/);
  if (match && Number(match[2]) >= 1 && Number(match[2]) <= 12) {
    return Date.UTC(Number(match[1]), Number(match[2]) - 1, 1);
  }

  match = value.match(/^(\d{4})-Q([1-4])$/i);
  if (match) return Date.UTC(Number(match[1]), (Number(match[2]) - 1) * 3, 1);

  match = value.match(/^(\d{4})-W(\d{2})$/i);
  if (match && Number(match[2]) >= 1 && Number(match[2]) <= 53) {
    const year = Number(match[1]);
    const jan4 = Date.UTC(year, 0, 4);
    const weekOneMonday = jan4 - ((new Date(jan4).getUTCDay() + 6) % 7) * 86400000;
    return weekOneMonday + (Number(match[2]) - 1) * 7 * 86400000;
  }

  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const timestamp = Date.parse(`${value}T00:00:00Z`);
    if (Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value) return timestamp;
  }
  return NaN;
}

function csvEscape(value) {
  const text = String(value ?? '');
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function setTimeSeriesStatus(message, isError = false) {
  const status = document.getElementById('timeSeriesStatus');
  if (!status) return;
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

function getPoliticalTimeSeriesEndpoints(forceRefresh = false) {
  const suffix = forceRefresh ? '/api/political-economy-timeseries?refresh=1' : '/api/political-economy-timeseries';
  const urls = [];
  const isGhPages = window.location.hostname.endsWith('.github.io');
  if (!isGhPages && window.location.protocol.startsWith('http')) {
    urls.push(`${window.location.origin}${suffix}`);
  }
  if (typeof window.KUVHURA_API_BASE_URL === 'string' && window.KUVHURA_API_BASE_URL.trim()) {
    urls.push(`${window.KUVHURA_API_BASE_URL.trim().replace(/\/+$/, '')}${suffix}`);
  }
  if (Array.isArray(window.KUVHURA_API_FALLBACK_URLS)) {
    window.KUVHURA_API_FALLBACK_URLS.forEach(base => {
      if (typeof base === 'string' && base.trim()) {
        urls.push(`${base.trim().replace(/\/+$/, '')}${suffix}`);
      }
    });
  }
  return [...new Set(urls)];
}

async function fetchLivePoliticalTimeSeries(forceRefresh = false) {
  const endpoints = getPoliticalTimeSeriesEndpoints(forceRefresh);
  for (const url of endpoints) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      const res = await fetch(url, { cache: 'no-store', signal: controller.signal });
      clearTimeout(timer);
      if (!res.ok) continue;
      const data = await res.json();
      if (data && Array.isArray(data.observations) && data.observations.length > 0) {
        serverTimeSeriesObservations = data.observations.filter(item =>
          item &&
          POLITICAL_TIME_SERIES[item.series] &&
          Object.hasOwn(POLITICAL_TIME_SERIES[item.series].metrics, item.metric) &&
          Number.isFinite(timeSeriesPeriodTimestamp(item.period)) &&
          Number.isFinite(Number(item.value))
        ).map(item => ({
          ...item,
          value: Number(item.value)
        }));
        return true;
      }
    } catch {
      // Try next endpoint
    }
  }
  return false;
}

function renderPoliticalTimeSeries(resetCutoff = false) {
  const select = document.getElementById('timeSeriesSelect');
  if (!select) return;
  const seriesId = select.value;
  const series = POLITICAL_TIME_SERIES[seriesId];
  if (!series) return;

  const range = document.getElementById('timeSeriesRange');
  const through = document.getElementById('timeSeriesThrough');
  const start = document.getElementById('timeSeriesStart');
  const end = document.getElementById('timeSeriesEnd');
  const description = document.getElementById('timeSeriesDescription');
  const referenceContainer = document.getElementById('timeSeriesReferenceSources');
  const sources = document.getElementById('timeSeriesSources');

  if (description) {
    description.textContent = `${series.equation} ${series.guidance}`;
  }
  if (referenceContainer) {
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
  }

  const allObservations = getMergedTimeSeriesObservations();
  const observations = allObservations
    .filter(item => item.series === seriesId)
    .sort((a, b) => timeSeriesPeriodTimestamp(a.period) - timeSeriesPeriodTimestamp(b.period));

  const periods = [...new Map(observations.map(item => [
    item.period,
    timeSeriesPeriodTimestamp(item.period)
  ]))].map(([period, timestamp]) => ({ period, timestamp }))
    .sort((a, b) => a.timestamp - b.timestamp);

  if (!periods.length) {
    if (range) {
      range.min = '0';
      range.max = '0';
      range.value = '0';
      range.disabled = true;
    }
    if (through) through.textContent = 'No observations';
    if (start) start.textContent = 'Start —';
    if (end) end.textContent = 'Latest —';
    if (sources) sources.replaceChildren();
    if (timeSeriesChart) {
      timeSeriesChart.destroy();
      timeSeriesChart = null;
    }
    setTimeSeriesStatus(`No observations loaded for ${series.title}. Use Actions → Refresh Live Series or Import Sourced CSV.`);
    return;
  }

  if (range) {
    range.disabled = periods.length <= 1;
    range.min = '0';
    range.max = String(periods.length - 1);
  }
  let selectedIndex = periods.length - 1;
  if (!resetCutoff && timeSeriesCutoff !== null) {
    const priorIndex = periods.findIndex(item => item.timestamp > timeSeriesCutoff);
    selectedIndex = priorIndex === -1 ? periods.length - 1 : Math.max(0, priorIndex - 1);
  }
  if (range) range.value = String(selectedIndex);
  const selectedPeriod = periods[selectedIndex];
  timeSeriesCutoff = selectedPeriod.timestamp;
  if (through) through.textContent = `Through ${selectedPeriod.period}`;
  if (start) start.textContent = `Start ${periods[0].period}`;
  if (end) end.textContent = `Latest ${periods[periods.length - 1].period}`;

  const visiblePeriods = periods.slice(0, selectedIndex + 1);
  const visibleLabels = new Set(visiblePeriods.map(item => item.period));
  const visibleObservations = observations.filter(item => visibleLabels.has(item.period));
  const unitList = [...new Set(visibleObservations.map(item => item.unit))].slice(0, 2);
  const unitAxis = new Map(unitList.map((unit, index) => [unit, `timeSeriesY${index}`]));
  const grouped = new Map();
  for (const observation of visibleObservations) {
    const axisUnit = unitAxis.has(observation.unit) ? observation.unit : unitList[0];
    const key = `${observation.metric}\u0000${axisUnit}`;
    if (!grouped.has(key)) grouped.set(key, new Map());
    grouped.get(key).set(observation.period, observation.value);
  }

  const chartMode = document.getElementById('timeSeriesChartTypeSelect')?.value || 'line';
  const isBar = chartMode === 'bar';
  const isArea = chartMode === 'area';
  const isStepped = chartMode === 'stepped';
  const isPointsOnly = chartMode === 'scatter';

  const palette = [series.color, '#34D399', '#F472B6', '#60A5FA'];
  const datasets = [...grouped.entries()].map(([key, values], idx) => {
    const [metric, unit] = key.split('\u0000');
    const metricIndex = Object.keys(series.metrics).indexOf(metric);
    const color = palette[(metricIndex >= 0 ? metricIndex : idx) % palette.length];
    const dataPoints = visiblePeriods.map(item => values.has(item.period) ? values.get(item.period) : null);
    if (isBar) {
      return {
        label: `${series.metrics[metric] || metric} (${unit})`,
        data: dataPoints,
        borderColor: color,
        backgroundColor: `${color}88`,
        borderWidth: 1.5,
        borderRadius: 3,
        yAxisID: unitAxis.get(unit)
      };
    }
    return {
      label: `${series.metrics[metric] || metric} (${unit})`,
      data: dataPoints,
      borderColor: color,
      backgroundColor: isArea ? `${color}30` : `${color}22`,
      pointBackgroundColor: color,
      pointRadius: isPointsOnly ? 5 : 3.5,
      pointHoverRadius: isPointsOnly ? 7 : 5.5,
      borderWidth: 2,
      fill: isArea,
      stepped: isStepped,
      showLine: !isPointsOnly,
      tension: isStepped ? 0 : 0.2,
      spanGaps: true,
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

  const canvas = document.getElementById('politicalTimeSeriesChart');
  if (canvas && typeof Chart !== 'undefined') {
    const targetType = isBar ? 'bar' : 'line';
    const chartConfiguration = {
      type: targetType,
      data: { labels: visiblePeriods.map(item => item.period), datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: isPointsOnly, mode: 'index' },
        plugins: {
          legend: { position: 'top', labels: { color: '#CBD5E1', boxWidth: 10, font: { size: 10 } } }
        },
        scales
      }
    };
    if (timeSeriesChart && timeSeriesChartMode === chartMode) {
      timeSeriesChart.data = chartConfiguration.data;
      timeSeriesChart.options = chartConfiguration.options;
      timeSeriesChart.update('none');
    } else {
      if (timeSeriesChart) {
        timeSeriesChart.destroy();
      }
      timeSeriesChartMode = chartMode;
      timeSeriesChart = new Chart(canvas.getContext('2d'), chartConfiguration);
    }
  }

  if (sources) {
    sources.replaceChildren();
    visibleObservations.slice().reverse().forEach(observation => {
      const item = document.createElement('div');
      item.className = 'time-series-source';
      const label = document.createElement('strong');
      label.textContent = `${observation.period} · ${series.metrics[observation.metric] || observation.metric}: ${observation.value.toLocaleString()} ${observation.unit}`;
      const source = document.createElement('a');
      source.href = observation.source_url;
      source.target = '_blank';
      source.rel = 'noopener noreferrer';
      source.textContent = observation.source;
      item.append(label, document.createTextNode(' · '), source);
      sources.append(item);
    });
  }

  setTimeSeriesStatus(
    `${visibleObservations.length} source-attributed observations (${periods[0].period} → ${selectedPeriod.period}).`
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
  if (!Array.isArray(stored)) throw new Error('Stored time-series data is invalid; clear browser site data and retry.');
  const replacements = new Set(batch.map(item => `${item.series}\u0000${item.period}\u0000${item.metric}`));
  const merged = [
    ...stored.filter(item => !replacements.has(`${item.series}\u0000${item.period}\u0000${item.metric}`)),
    ...batch
  ];
  if (merged.length > TIME_SERIES_MAX_ROWS) {
    throw new Error(`The browser can store at most ${TIME_SERIES_MAX_ROWS} observations.`);
  }
  storage.setItem(TIME_SERIES_STORAGE_KEY, JSON.stringify(merged));
  customTimeSeriesObservations = merged;
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
  const seriesId = document.getElementById('timeSeriesSelect')?.value;
  const rows = getMergedTimeSeriesObservations()
    .filter(item => item.series === seriesId)
    .map(item => TIME_SERIES_COLUMNS.map(column => item[column]));
  if (!rows.length) {
    setTimeSeriesStatus('There are no observations for this series to export.');
    return;
  }
  downloadTimeSeriesCsv(`kuvhura-${seriesId}-observations.csv`, rows);
}

function clearCustomPoliticalTimeSeries() {
  const seriesId = document.getElementById('timeSeriesSelect')?.value;
  if (!seriesId || !POLITICAL_TIME_SERIES[seriesId]) return;
  const retained = customTimeSeriesObservations.filter(item => item.series !== seriesId);
  try {
    window.localStorage.setItem(TIME_SERIES_STORAGE_KEY, JSON.stringify(retained));
    customTimeSeriesObservations = retained;
    timeSeriesCutoff = null;
    renderPoliticalTimeSeries(true);
    setTimeSeriesStatus(`Reset custom browser imports for ${POLITICAL_TIME_SERIES[seriesId].title}; displaying live sourced observations.`);
  } catch (error) {
    setTimeSeriesStatus(`Could not clear local observations: ${error.message}`, true);
  }
}

async function handleTimeSeriesActionSelect(selectEl) {
  const action = selectEl?.value || '';
  if (selectEl) selectEl.value = '';
  const fileInput = document.getElementById('timeSeriesFile');
  if (action === 'refresh') {
    setTimeSeriesStatus('Refreshing live political-economy series…');
    const ok = await fetchLivePoliticalTimeSeries(true);
    renderPoliticalTimeSeries(true);
    if (!ok) {
      setTimeSeriesStatus('Could not reach live time-series endpoint; showing currently loaded observations.', true);
    }
  } else if (action === 'import') {
    fileInput?.click();
  } else if (action === 'export') {
    exportPoliticalTimeSeries();
  } else if (action === 'template') {
    downloadPoliticalTimeSeriesTemplate();
  } else if (action === 'clear') {
    clearCustomPoliticalTimeSeries();
  }
}

async function initPoliticalEconomyTimeSeries() {
  const select = document.getElementById('timeSeriesSelect');
  const range = document.getElementById('timeSeriesRange');
  const fileInput = document.getElementById('timeSeriesFile');
  const actionSelect = document.getElementById('timeSeriesActionSelect');
  if (!select || !range || !fileInput) return;

  select.addEventListener('change', () => {
    timeSeriesCutoff = null;
    renderPoliticalTimeSeries(true);
  });
  range.addEventListener('input', () => {
    const selected = [...new Map(getMergedTimeSeriesObservations()
      .filter(item => item.series === select.value)
      .map(item => [item.period, timeSeriesPeriodTimestamp(item.period)]))]
      .sort((a, b) => a[1] - b[1]);
    timeSeriesCutoff = selected[Number(range.value)]?.[1] ?? null;
    renderPoliticalTimeSeries();
  });
  const chartTypeSelect = document.getElementById('timeSeriesChartTypeSelect');
  if (chartTypeSelect) {
    chartTypeSelect.addEventListener('change', () => renderPoliticalTimeSeries(false));
  }
  if (actionSelect) {
    actionSelect.addEventListener('change', () => handleTimeSeriesActionSelect(actionSelect));
  }
  fileInput.addEventListener('change', async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const count = await importPoliticalTimeSeriesCsv(file);
      renderPoliticalTimeSeries(true);
      setTimeSeriesStatus(`Imported ${count} custom source-attributed observations (merged with live series).`);
    } catch (error) {
      setTimeSeriesStatus(error.message, true);
    } finally {
      fileInput.value = '';
    }
  });

  try {
    const stored = JSON.parse(window.localStorage.getItem(TIME_SERIES_STORAGE_KEY) || '[]');
    if (Array.isArray(stored)) {
      customTimeSeriesObservations = stored;
    }
  } catch {
    customTimeSeriesObservations = [];
  }

  setTimeSeriesStatus('Loading live political-economy observations…');
  await fetchLivePoliticalTimeSeries(false);
  renderPoliticalTimeSeries(true);
}

document.addEventListener('DOMContentLoaded', initPoliticalEconomyTimeSeries);
