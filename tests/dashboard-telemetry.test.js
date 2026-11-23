import { readFileSync } from 'node:fs';
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
