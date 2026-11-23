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

