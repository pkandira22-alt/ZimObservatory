import { existsSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';
import assert from 'node:assert/strict';

function extract(source, start, end) {
  const first = source.indexOf(start);
  const last = source.indexOf(end, first);
  assert.ok(first >= 0 && last > first);
  return source.slice(first, last);
}

test('trajectory covers calendar days without inventing missing readings', () => {
  const html = readFileSync(new URL('../systemic-risk.html', import.meta.url), 'utf8');
  const code = extract(html, 'function normalizeRollingTimeline(', '        function renderChart(');
  const normalize = runInNewContext(`${code}; normalizeRollingTimeline`, { Date });
  const timeline = normalize([
    { date: '2026-11-20', phi: 30, social_volume: 4 },
    { date: '2026-11-22', phi: 31, social_volume: 5 },
  ], 5, new Date('2026-11-23T12:00:00Z'));

  assert.deepEqual(Array.from(timeline, entry => entry.date), [
    '2026-11-19', '2026-11-20', '2026-11-21', '2026-11-22', '2026-11-23',
  ]);
  assert.equal(timeline[1].phi, 30);
  assert.equal(timeline[3].phi, 31);
  assert.equal(timeline[2].phi, undefined);
  assert.equal(timeline[4].phi, undefined);
});

test('stale and irrelevant posts do not contribute to fresh social metrics', async () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(source, 'async function getSocialHashtagTrendsInternal(', '\nconst LAYER2_MACRO_TTL_MS');
  const feeds = [
    { name: 'fresh', platform: 'Bluesky', posts: [
      { platform: 'Bluesky', text: 'relevant #Budget', createdAt: '2026-11-23T00:00:00Z' },
      { platform: 'Bluesky', text: 'unrelated #Sport', createdAt: '2026-11-23T00:00:00Z' },
    ] },
    { name: 'stale', platform: 'Mastodon', stale: true, error: 'feed unavailable', posts: [
      { platform: 'Mastodon', text: 'relevant #Budget', createdAt: '2026-11-22T00:00:00Z' },
    ] },
  ];
  const context = {
    SOCIAL_FEEDS: feeds, SOCIAL_CACHE_MS: 60000,
    SOCIAL_SOURCE_CACHE_MS: { x: 60000, youtube: 60000 },
    HASHTAG_REGEX: /#[A-Za-z]+/g, socialCache: {}, latestSocialTelemetry: null,
    getYouTubeApiKey: () => '', getXBearerToken: () => '',
    fetchSocialSource: async feed => feeds.find(result => result.name === feed.name)
      || { name: feed.name, platform: feed.platform, posts: [], failed: true },
    isModelRelevantSocialItem: text => text.startsWith('relevant'),
    isModelRelevantHashtag: () => true,
  };
  const collect = runInNewContext(`${code}; getSocialHashtagTrendsInternal`, context);
  const result = await collect();
  assert.equal(result.scannedPosts, 1);
  assert.equal(result.hashtags[0].mentions, 1);
  assert.equal(result.sources.find(feed => feed.name === 'stale').status, 'stale');
  assert.deepEqual(Array.from(result.sampledPlatforms), ['Bluesky']);
});

test('snapshot file preserves older days and refuses to overwrite corrupted history', () => {
  const dir = mkdtempSync(join(tmpdir(), 'zimobservatory-snapshot-test-'));
  const filename = join(dir, 'daily_telemetry_snapshots.json');
  try {
    const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
    const code = extract(source, 'function readLocalDailySnapshotsFallback()', 'function mergePersistedSnapshotsIntoTimeline(');
    const context = {
      LOCAL_SNAPSHOTS_FALLBACK_PATH: filename,
      existsSync, readFileSync, writeFileSync, renameSync,
      console: { warn() {} },
    };
    const store = runInNewContext(`${code}; ({ read: readLocalDailySnapshotsFallback, write: writeLocalDailySnapshotFallback })`, context);
    for (let day = 1; day <= 31; day++) {
      assert.equal(store.write({ date: `2026-10-${String(day).padStart(2, '0')}`, social_volume: day }), true);
    }
    assert.equal(store.write({ date: '2026-10-31', social_volume: 99 }), true);
    const restartedStore = runInNewContext(`${code}; ({ read: readLocalDailySnapshotsFallback })`, context);
    const saved = restartedStore.read();
    assert.equal(saved.length, 31);
    assert.equal(saved[0].date, '2026-10-01');
    assert.equal(saved[30].social_volume, 99);

    writeFileSync(filename, '{invalid', 'utf8');
    assert.equal(store.write({ date: '2026-11-01', social_volume: 1 }), false);
    assert.equal(readFileSync(filename, 'utf8'), '{invalid');
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test('rolling illustrative baseline anchors to today with zero gap before live reading', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(source, 'const TIMELINE_WINDOW_DAYS = 30;', '\nconst TELEMETRY_TIMELINE = buildRollingSeedTimeline();');
  const buildRolling = runInNewContext(`${code}; buildRollingSeedTimeline`, { Date });
  const baseline = buildRolling(new Date('2026-11-23T12:00:00Z'));

  assert.equal(baseline.length, 30);
  assert.equal(baseline[0].date, '2026-10-25');
  assert.equal(baseline[baseline.length - 2].date, '2026-11-22');
  assert.equal(baseline[baseline.length - 1].date, '2026-11-23');
  assert.equal(baseline.every(entry => Number.isFinite(entry.phi) && Number.isFinite(entry.fsi)), true);
  assert.equal(baseline.every(entry => entry.social_volume === undefined), true);
});

test('CARTO map tile proxy enforces allowlisted styles, valid tile bounds, and secret redaction', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(source, 'const CARTO_TILE_STYLE_TEMPLATES =', '\nfunction cacheMapTile(');
  const helpers = runInNewContext(
    `${code}; ({ resolveCartoTileUpstreamUrl, redactSecretQueryParams })`,
    { Map, Object, Number, String, encodeURIComponent }
  );

  const valid = helpers.resolveCartoTileUpstreamUrl('voyager', '6', '37', '35', 'test_demo_key');
  assert.equal(valid.baseUrl, 'https://basemaps.cartocdn.com/rastertiles/voyager/6/37/35.png');
  assert.equal(valid.url, 'https://basemaps.cartocdn.com/rastertiles/voyager/6/37/35.png?key=test_demo_key');

  const keyless = helpers.resolveCartoTileUpstreamUrl('dark_all', '6', '37', '35', null);
  assert.equal(keyless.url, 'https://basemaps.cartocdn.com/dark_all/6/37/35.png');

  assert.equal(helpers.resolveCartoTileUpstreamUrl('../evil', '6', '37', '35', 'k'), null);
  assert.equal(helpers.resolveCartoTileUpstreamUrl('voyager', '20', '0', '0', 'k'), null);
  assert.equal(helpers.resolveCartoTileUpstreamUrl('voyager', '6', '64', '35', 'k'), null);
  assert.equal(helpers.resolveCartoTileUpstreamUrl('voyager', '6', '-1', '35', 'k'), null);
  assert.equal(helpers.resolveCartoTileUpstreamUrl('voyager', '6', '37?host=x', '35', 'k'), null);

  assert.equal(
    helpers.redactSecretQueryParams('fetch failed https://basemaps.cartocdn.com/rastertiles/voyager/6/37/35.png?key=secret123&x=1'),
    'fetch failed https://basemaps.cartocdn.com/rastertiles/voyager/6/37/35.png?key=[REDACTED]&x=1'
  );
});

test('same-day snapshot merging preserves previously recorded metrics during transient upstream timeouts', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(source, 'function mergeSnapshotEntryFields(', '\nfunction readRepoDailySnapshots(');
  const mergeFields = runInNewContext(`${code}; mergeSnapshotEntryFields`, { Array, Number });

  const earlierToday = {
    date: '2026-11-23',
    phi: 22.5,
    markov_crisis_prob: 47.1,
    macro_volatility_proxy: 24.4,
    fsi: 56.2,
    warning_level: 'Accelerated Degradation',
    hansard_friction: 59.3,
    treasury_friction: 51.8,
    social_volume: 120,
    tracked_topics: [{ topic: 'Finance Bill', category: 'Bill Digests', friction: 62 }]
  };
  const transientPartial = {
    date: '2026-11-23',
    phi: 23.1,
    markov_crisis_prob: 46.8,
    social_volume: 135
  };

  const merged = mergeFields(earlierToday, transientPartial);
  assert.equal(merged.phi, 23.1);
  assert.equal(merged.social_volume, 135);
  assert.equal(merged.fsi, 56.2);
  assert.equal(merged.macro_volatility_proxy, 24.4);
  assert.equal(merged.hansard_friction, 59.3);
  assert.equal(merged.treasury_friction, 51.8);
  assert.equal(merged.warning_level, 'Accelerated Degradation');
  assert.equal(merged.tracked_topics.length, 1);

  assert.equal(source.includes('Durable history requires a configured persistent disk.'), false);
  const srHtml = readFileSync(new URL('../systemic-risk.html', import.meta.url), 'utf8');
  assert.equal(srHtml.includes('data.historyNote'), false);
});

test('expanded social telemetry dictionary captures political economy, economy, and politics while rejecting noise', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(source, 'const SOCIAL_NOISE_EXCLUDE_REGEX =', '\nfunction decodeXmlEntities(');
  const helpers = runInNewContext(`${code}; ({ isModelRelevantSocialItem, isModelRelevantHashtag })`, { Set, String });

  const relevantSamples = [
    'ZANU-PF politburo factionalism and 2030 succession debate',
    'RBZ monetary policy committee holds bank rate steady amid ZiG liquidity squeeze',
    'IMF Article IV arrears clearance and Paris Club sovereign debt restructuring',
    'PRAZ procurement audit flags rent-seeking, tenderpreneurs, and clientelism',
    'ZSE and VFEX market reaction to IMTT, PAYE, and corporate tax changes',
    'ARTUZ teachers and ZHDA doctors call stayaway over living wage',
    'Land barons, 99-year lease reform, and Manhize steel beneficiation'
  ];
  for (const sample of relevantSamples) {
    assert.equal(helpers.isModelRelevantSocialItem(sample), true, `Expected relevant: ${sample}`);
  }

  const noiseSamples = [
    'Zimbabwe cricket match highlights vs Ireland T20 wickets',
    'New Zimdancehall official music video premiere in Harare',
    'Prophet says shocking prophecy for Zimbabwe this week',
    'Victoria Falls hotel luxury safari tour travel vlog',
    'Excavators for sale from heavy machinery supplier in Zimbabwe'
  ];
  for (const sample of noiseSamples) {
    assert.equal(helpers.isModelRelevantSocialItem(sample), false, `Expected noise excluded: ${sample}`);
  }
});

test('live core model parameters recalibrate E, Pr, CL, AL, DB and P/I/C from empirical feeds', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(
    source,
    'const MODEL_SIGNAL_BUCKET_REGEX =',
    '\nasync function gatherLiveModelAndStructuralInputs()'
  );
  const helpers = runInNewContext(
    `${code}; ({ computeLiveModelParameters, computeStructuralProvincialTelemetry })`,
    { Object, Array, Number, String, Math, Date }
  );

  const highStressPosts = [
    ...Array.from({ length: 12 }, () => ({ text: 'RBZ ZiG parallel rate gold lithium Mutapa tender corruption' })),
    ...Array.from({ length: 10 }, () => ({ text: 'Police ZRP arrest activists under PVO Bill crackdown ED2030' })),
    ...Array.from({ length: 8 }, () => ({ text: 'Diaspora remittances via Mukuru and WorldRemit keep families afloat' })),
    ...Array.from({ length: 6 }, () => ({ text: 'Mbare vendors informal economy cooperative strike and borehole mutual aid' })),
    ...Array.from({ length: 4 }, () => ({ text: 'Inflation cost of living Pfumvudza maize subsidy civil service salaries' }))
  ];

  const live = helpers.computeLiveModelParameters({
    socialPosts: highStressPosts,
    socialPayload: { sampledPlatforms: ['Bluesky', 'YouTube'] },
    layer2Macro: { source: 'world_bank_v2', Inflation: 68.5, GDP_Growth: 2.1, Debt_GNI: 48.0 },
    timeSeries: {
      observations: [
        { series: 'remittance-purchasing-power', period: '2024', metric: 'remittances_received', value: 2450 },
        { series: 'fx-inflation', period: '2025', metric: 'parallel_fx_premium_pct', value: 52.0 },
        { series: 'remittance-purchasing-power', period: '2024', metric: 'civil_service_real_pay', value: 45.0 },
        { series: 'narrative-throttling', period: '2026-11-20', metric: 'ooni_anomalies', value: 18 }
      ]
    },
    hansardTelemetry: { score: 74.0 },
    treasuryTelemetry: { status: 'available', score: 71.5 }
  });

  assert.equal(live.available, true);
  assert.equal(live.sampledPosts, 40);
  for (const key of ['E', 'Pr', 'CL', 'AL', 'DB']) {
    const param = live.parameters[key];
    assert.ok(param.value >= 1.0 && param.value <= 10.0, `${key} out of range: ${param.value}`);
    assert.equal(param.lineage, 'Live Empirical');
    assert.ok(Array.isArray(param.drivers) && param.drivers.length > 0);
  }
  assert.ok(live.parameters.DB.value > 7.5, `Expected high DB from $2.45B remittances + diaspora share, got ${live.parameters.DB.value}`);
  assert.ok(live.parameters.CL.value > 8.9, `Expected elevated CL from F_parl 74 + OONI + coercion, got ${live.parameters.CL.value}`);
  assert.ok(live.frictionVector.P.value >= 1.0 && live.frictionVector.P.value <= 10.0);
  assert.ok(live.frictionVector.I.value >= 1.0 && live.frictionVector.I.value <= 10.0);
  assert.ok(live.frictionVector.C.value >= 1.0 && live.frictionVector.C.value <= 10.0);
  assert.ok(Number.isFinite(live.derived.phi) && live.derived.phi > 0);
  assert.ok(Number.isFinite(live.derived.praxis) && live.derived.praxis > 0);

  const lowRemit = helpers.computeLiveModelParameters({
    socialPosts: [],
    timeSeries: {
      observations: [
        { series: 'remittance-purchasing-power', period: '2018', metric: 'remittances_received', value: 1300 }
      ]
    }
  });
  assert.ok(lowRemit.parameters.DB.delta < 0, `Expected negative DB delta, got ${lowRemit.parameters.DB.delta}`);
});

test('structural provincial telemetry maps all 10 Zimbabwe provinces and responds to geo-tagged social and Land Portal signals', () => {
  const source = readFileSync(new URL('../server.js', import.meta.url), 'utf8');
  const code = extract(
    source,
    'const MODEL_SIGNAL_BUCKET_REGEX =',
    '\nasync function gatherLiveModelAndStructuralInputs()'
  );
  const helpers = runInNewContext(
    `${code}; ({ computeLiveModelParameters, computeStructuralProvincialTelemetry })`,
    { Object, Array, Number, String, Math, Date }
  );

  const posts = [
    { text: 'Bikita lithium mining concession dispute in Masvingo communal land' },
    { text: 'Marange diamond extraction and Penhalonga gold mining in Manicaland' },
    { text: 'Harare Mbare vendors protest informal tax IMTT and water rationing' },
    { text: 'Hwange power blackout and Kamativi lithium mining in Matabeleland North' },
    { text: 'Manhize Dinson steel and Gweru gold mining corridor in Midlands' }
  ];
  const landPortalData = {
    signals: [
      { indicator: 'Masvingo Bikita communal land concession', note: 'Bikita tenure shift', provider: 'Land Portal' }
    ]
  };
  const liveModelParams = helpers.computeLiveModelParameters({ socialPosts: posts });
  const provincial = helpers.computeStructuralProvincialTelemetry({
    socialPosts: posts,
    socialPayload: { sampledPlatforms: ['Bluesky'] },
    layer2Macro: { source: 'world_bank_v2', Inflation: 42.0, GDP_Growth: 3.0, Debt_GNI: 40.0 },
    hansardTelemetry: { score: 62.0 },
    treasuryTelemetry: { status: 'available', score: 65.0 },
    landPortalData,
    liveModelParams,
    latestTimelineEntry: { phi: 34.5 }
  });

  assert.equal(provincial.available, true);
  assert.equal(provincial.provinceCount, 10);
  assert.equal(provincial.provinces.length, 10);
  assert.ok(provincial.geoMatchedSignals >= 6);
  const masvingo = provincial.provinces.find(p => p.id === 'masvingo');
  const harare = provincial.provinces.find(p => p.id === 'harare');
  assert.ok(masvingo && masvingo.landPortalMatches === 1 && masvingo.socialMentions === 1);
  assert.ok(masvingo.rsrDelta > 0);
  assert.ok(harare && harare.socialMentions === 1 && harare.iefrDelta > 0);
  assert.ok(provincial.summary.adjustedPhi < provincial.summary.basePhi);
});



