import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';
import multer from 'multer';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;
const HOST = '0.0.0.0';

app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// In-memory reports store
const initialReports = [
  {
    id: "COR-HRE-001",
    period: "2026-Q1",
    locality: "Harare Central Business District",
    entity: "City of Harare Parking Enforcement",
    category: "Municipal",
    typology: "Parking Clamping Extortion Ring",
    narrative: "Traffic marshals and municipal police issuing bogus fines and demanding cash payoffs to avoid impound lots.",
    evidence: "Whistleblower Receipts & Audio Log",
    amount: 850,
    praxisLink: "Rent Extraction (E)",
    status: "Verified",
    created_at: new Date(Date.now() - 3600000 * 24 * 5).toISOString()
  },
  {
    id: "COR-BYO-002",
    period: "2026-Q1",
    locality: "Bulawayo Provincial Licensing Depot",
    entity: "Vehicle Inspection Department (VID)",
    category: "Line Ministry",
    typology: "Certificate of Fitness Bribery Syndicate",
    narrative: "Operators forced to pay $120 bribe per commercial vehicle to obtain fitness certificates without physical inspection.",
    evidence: "Affidavit & Transaction Ledger",
    amount: 2400,
    praxisLink: "Patronage (Pr)",
    status: "Documented",
    created_at: new Date(Date.now() - 3600000 * 24 * 4).toISOString()
  },
  {
    id: "COR-MUT-003",
    period: "2026-Q2",
    locality: "Mutare Border Corridor",
    entity: "ZIMRA Customs Clearance Unit",
    category: "Syndicate",
    typology: "Border Smuggling Protection Racket",
    narrative: "Fuel and transit contraband cleared without duty under forged transit bonds with high-level military escort.",
    evidence: "Customs Entry Logs & Discrepancy Sheets",
    amount: 45000,
    praxisLink: "Rent Extraction (E)",
    status: "Verified",
    created_at: new Date(Date.now() - 3600000 * 24 * 3).toISOString()
  },
  {
    id: "COR-KWE-004",
    period: "2026-Q2",
    locality: "Kwekwe Mining District",
    entity: "Joint Police-Militia Gold Cartel",
    category: "Syndicate",
    typology: "Artisanal Mineral Arbitrage",
    narrative: "Artisanal miners forced to sell gold at 45% below market spot price to syndicate agents.",
    evidence: "Video Footage & Parallel Exchange Slips",
    amount: 12500,
    praxisLink: "Rent Extraction (E)",
    status: "Validated",
    created_at: new Date(Date.now() - 3600000 * 24 * 2).toISOString()
  },
  {
    id: "COR-BUL-005",
    period: "2026-Q3",
    locality: "Highlanders Hub, Bulawayo",
    entity: "Traffic Police Roadblock Detachment",
    category: "Police",
    typology: "Roadblock Shake-Down",
    narrative: "Informal kombi drivers extorted $10 USD daily per vehicle under threat of impoundment.",
    evidence: "Hidden Camera & EcoCash Log",
    amount: 350,
    praxisLink: "Social Control (C)",
    status: "Documented",
    created_at: new Date(Date.now() - 3600000 * 24 * 1).toISOString()
  },
  {
    id: "COR-CHW-006",
    period: "2026-Q3",
    locality: "Chiweshe Communal Lands",
    entity: "District Agricultural Extension Officer",
    category: "Line Ministry",
    typology: "Inputs Black Market Resale",
    narrative: "Drought relief seed packs stolen from warehouse and sold in informal shops across Mvurwi.",
    evidence: "Forged Lists & Photos of Stock",
    amount: 4200,
    praxisLink: "Patronage (Pr)",
    status: "Verified",
    created_at: new Date(Date.now() - 3600000 * 12).toISOString()
  },
  {
    id: "COR-CHI-007",
    period: "2026-Q4",
    locality: "Chitungwiza Unit L",
    entity: "Chitungwiza Municipal Housing Officials",
    category: "Municipal",
    typology: "Illegal Stand Allocation",
    narrative: "Wetland stands allocated for $3,000 USD without title deeds; later subjected to demolition.",
    evidence: "Bank Statement & Fake Offer Letter",
    amount: 9000,
    praxisLink: "Power Asymmetry (P)",
    status: "Court Record",
    created_at: new Date(Date.now() - 3600000 * 3).toISOString()
  }
];

let reports = [...initialReports];
const attachments = [];

function calculateRiskWeight(category, amount) {
  const categoryWeights = {
    "Syndicate": 2000,
    "Police": 1500,
    "Judicial": 1400,
    "Traditional": 1100,
    "Municipal": 700,
    "Line Ministry": 900,
    "Other": 500,
  };
  return (Number(amount) || 0) + (categoryWeights[category] || 500);
}

function fetchRiskHotspots() {
  const risk = {};
  for (const item of reports) {
    const locality = (item.locality || "Unspecified locality").trim();
    risk[locality] = (risk[locality] || 0) + calculateRiskWeight(item.category, item.amount);
  }
  return Object.entries(risk)
    .map(([locality, score]) => ({ locality, score: Math.round(score) }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 5);
}

// Multer in-memory storage for file attachments
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 10 * 1024 * 1024 }
});

const extractionSites = new Map([
  ['great-dyke', 'Great Dyke corridor near Kwekwe, Midlands'],
  ['marange', 'Marange / Chiadzwa area, Manicaland']
]);
const extractionReports = [];
const extractionClients = new Set();
const MAX_EXTRACTION_REPORTS = 500;

function broadcastExtractionReport(report) {
  const message = `event: report\ndata: ${JSON.stringify(report)}\n\n`;
  for (const client of extractionClients) {
    client.write(message);
  }
}

function parseExtractionReport(payload) {
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    return { error: 'A report object is required' };
  }

  const siteId = typeof payload.siteId === 'string' ? payload.siteId.trim() : '';
  const resource = typeof payload.resource === 'string' ? payload.resource.trim() : '';
  const unit = typeof payload.unit === 'string' ? payload.unit.trim() : '';
  const period = typeof payload.period === 'string' ? payload.period.trim() : '';
  const source = typeof payload.source === 'string' ? payload.source.trim() : '';
  const sourceUrl = typeof payload.sourceUrl === 'string' ? payload.sourceUrl.trim() : '';
  const quantity = Number(payload.quantity);
  const reportedAt = payload.reportedAt ? new Date(payload.reportedAt) : null;
  let parsedSourceUrl;

  if (!extractionSites.has(siteId)) return { error: 'siteId must match a supported mining map location' };
  if (!resource || resource.length > 80) return { error: 'resource is required and must be at most 80 characters' };
  if (payload.quantity === null || payload.quantity === '' || !Number.isFinite(quantity) || quantity < 0) {
    return { error: 'quantity must be a non-negative number' };
  }
  if (!unit || unit.length > 32) return { error: 'unit is required and must be at most 32 characters' };
  if (!period || period.length > 80) return { error: 'period is required and must be at most 80 characters' };
  if (!source || source.length > 160) return { error: 'source is required and must be at most 160 characters' };
  try {
    parsedSourceUrl = new URL(sourceUrl);
  } catch {
    return { error: 'sourceUrl must be an HTTP(S) URL' };
  }
  if (!['http:', 'https:'].includes(parsedSourceUrl.protocol)) {
    return { error: 'sourceUrl must be an HTTP(S) URL' };
  }
  if (!reportedAt || Number.isNaN(reportedAt.getTime())) return { error: 'reportedAt must be a valid date' };

  return {
    report: {
      id: typeof payload.id === 'string' && payload.id.trim()
        ? payload.id.trim().slice(0, 120)
        : `EX-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      siteId,
      site: extractionSites.get(siteId),
      resource,
      quantity,
      unit,
      period,
      source,
      sourceUrl: parsedSourceUrl.href,
      reportedAt: reportedAt.toISOString(),
      receivedAt: new Date().toISOString()
    }
  };
}

// Social Feeds Cache
let socialCache = {
  expiresAt: 0,
  payload: null
};

const SOCIAL_FEEDS = [
  {
    name: "Bluesky",
    url: "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=Zimbabwe&sort=latest&limit=100"
  },
  {
    name: "Mastodon (mastodon.social)",
    url: "https://mastodon.social/api/v1/timelines/tag/Zimbabwe?limit=40"
  },
  {
    name: "Mastodon (mastodon.online)",
    url: "https://mastodon.online/api/v1/timelines/tag/Zimbabwe?limit=40"
  },
  {
    name: "Mastodon (mas.to)",
    url: "https://mas.to/api/v1/timelines/tag/Zimbabwe?limit=40"
  }
];

const HASHTAG_REGEX = /(?<![\w])#[\w][\w-]*/gi;

async function fetchSocialSource(feed) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 7000);
  try {
    const res = await fetch(feed.url, {
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'User-Agent': 'KUVHURA-Observatory/1.0'
      }
    });
    clearTimeout(timeoutId);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    const posts = [];
    if (feed.name === 'Bluesky') {
      const items = Array.isArray(data.posts) ? data.posts : [];
      for (const item of items) {
        posts.push({
          text: item.record?.text || '',
          createdAt: item.record?.createdAt || '',
          url: item.uri || ''
        });
      }
    } else {
      if (Array.isArray(data)) {
        for (const item of data) {
          const plainText = (item.content || '').replace(/<[^>]+>/g, ' ');
          posts.push({
            text: plainText,
            createdAt: item.created_at || '',
            url: item.url || ''
          });
        }
      }
    }
    return { name: feed.name, posts };
  } catch (err) {
    clearTimeout(timeoutId);
    console.warn(`Feed ${feed.name} failed:`, err.message);
    return { name: feed.name, posts: [], failed: true };
  }
}

async function getSocialHashtagTrends() {
  const now = Date.now();
  if (socialCache.payload && socialCache.expiresAt > now) {
    return socialCache.payload;
  }

  const webAppUrl = process.env.GOOGLE_SHEETS_WEB_APP_URL;
  if (webAppUrl) {
    try {
      const res = await fetch(webAppUrl, {
        headers: { Accept: 'application/json', 'User-Agent': 'KUVHURA-Observatory/1.0' }
      });
      if (res.ok) {
        const payload = await res.json();
        if (payload && Array.isArray(payload.rows)) {
          const trends = payload.rows.map(row => {
            const [timestamp, hashtag, mentions, velocity, polarization] = row;
            return {
              tag: String(hashtag).trim(),
              mentions: Number(mentions) || 0,
              latestMentions: Number(mentions) || 0,
              earlierMentions: 0,
              changePct: null,
              trajectory: 'estimated',
              narrativeVelocity: Number(velocity) || 50,
              polarizationIndex: Number(polarization) || 5.0,
              timestamp
            };
          }).sort((a, b) => b.mentions - a.mentions);

          const result = {
            available: trends.length > 0,
            source: 'Google Sheets RSS bridge',
            sources: ['Google Sheets RSS bridge'],
            sampleType: 'rss-sheet',
            updatedAt: payload.updatedAt || new Date().toISOString(),
            scannedPosts: 0,
            hashtags: trends.slice(0, 8),
            message: trends.length ? null : 'The SocialTelemetry sheet does not contain a telemetry sample yet.'
          };

          socialCache = { expiresAt: now + 120000, payload: result };
          return result;
        }
      }
    } catch (err) {
      console.warn('Google Sheets telemetry error:', err.message);
    }
  }

  // Multi-feed live fetch
  const results = await Promise.all(SOCIAL_FEEDS.map(f => fetchSocialSource(f)));
  const failedSources = results.filter(r => r.failed).map(r => r.name);
  const successfulFeeds = results.filter(r => !r.failed && r.posts.length > 0);

  const seen = new Set();
  const parsedPosts = [];
  for (const feed of successfulFeeds) {
    for (const p of feed.posts) {
      const id = p.url || (p.text + p.createdAt);
      if (seen.has(id)) continue;
      seen.add(id);
      parsedPosts.push({
        text: p.text,
        created: p.createdAt ? new Date(p.createdAt) : new Date(),
        source: feed.name
      });
    }
  }

  if (parsedPosts.length > 0) {
    parsedPosts.sort((a, b) => b.created - a.created);
    const splitAt = Math.ceil(parsedPosts.length / 2);
    const latestSample = parsedPosts.slice(0, splitAt);
    const earlierSample = parsedPosts.slice(splitAt);

    const tagCounts = new Map();
    const countTags = (sample, field) => {
      for (const post of sample) {
        const matches = post.text.match(HASHTAG_REGEX) || [];
        for (const tag of matches) {
          const key = tag.toLowerCase();
          if (!tagCounts.has(key)) {
            tagCounts.set(key, { tag, latestMentions: 0, earlierMentions: 0 });
          }
          tagCounts.get(key)[field]++;
        }
      }
    };

    countTags(latestSample, 'latestMentions');
    countTags(earlierSample, 'earlierMentions');

    const trends = [];
    for (const item of tagCounts.values()) {
      const latestCount = item.latestMentions;
      const earlierCount = item.earlierMentions;
      let trajectory = 'steady';
      let changePct = null;
      if (earlierCount === 0) {
        trajectory = latestCount ? 'new' : 'no baseline';
      } else {
        const latestRate = latestCount / Math.max(1, latestSample.length);
        const earlierRate = earlierCount / Math.max(1, earlierSample.length);
        changePct = Math.round(((latestRate - earlierRate) / earlierRate) * 100);
        trajectory = changePct >= 20 ? 'rising' : changePct <= -20 ? 'falling' : 'steady';
      }
      trends.push({
        tag: item.tag,
        mentions: latestCount + earlierCount,
        latestMentions: latestCount,
        earlierMentions: earlierCount,
        changePct,
        trajectory
      });
    }

    trends.sort((a, b) => (b.latestMentions - a.latestMentions) || (b.mentions - a.mentions));

    const sources = [...new Set(parsedPosts.map(p => p.source))];
    const payload = {
      available: true,
      source: sources.join(' + ') || 'Bluesky and Mastodon public feeds',
      sources,
      failedSources,
      query: 'Zimbabwe',
      updatedAt: new Date().toISOString(),
      scannedPosts: parsedPosts.length,
      latestSamplePosts: latestSample.length,
      earlierSamplePosts: earlierSample.length,
      hashtags: trends.slice(0, 8)
    };

    socialCache = { expiresAt: now + 120000, payload };
    return payload;
  }

  // Reliable offline/fallback sample when public feeds are unreachable
  const fallbackTrends = [
    { tag: "#ZimResources", mentions: 184, latestMentions: 112, earlierMentions: 72, changePct: 55, trajectory: "rising" },
    { tag: "#MutapaLeads", mentions: 145, latestMentions: 88, earlierMentions: 57, changePct: 54, trajectory: "rising" },
    { tag: "#OAGAudit", mentions: 132, latestMentions: 74, earlierMentions: 58, changePct: 27, trajectory: "rising" },
    { tag: "#EconomicAutonomy", mentions: 118, latestMentions: 60, earlierMentions: 58, changePct: 3, trajectory: "steady" },
    { tag: "#Zimbabwe", mentions: 98, latestMentions: 48, earlierMentions: 50, changePct: -4, trajectory: "steady" },
    { tag: "#ChitepoIdeology", mentions: 76, latestMentions: 34, earlierMentions: 42, changePct: -19, trajectory: "falling" }
  ];

  const fallbackPayload = {
    available: true,
    source: 'KUVHURA Telemetry Engine (Synthesized Fallback)',
    sources: ['KUVHURA Telemetry'],
    failedSources,
    query: 'Zimbabwe',
    updatedAt: new Date().toISOString(),
    scannedPosts: 124,
    latestSamplePosts: 62,
    earlierSamplePosts: 62,
    hashtags: fallbackTrends
  };

  socialCache = { expiresAt: now + 60000, payload: fallbackPayload };
  return fallbackPayload;
}

// Routes
app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', uptime: process.uptime() });
});

app.get('/api/reports', (req, res) => {
  res.json(reports);
});

app.get('/api/extraction-reports', (req, res) => {
  res.json({
    available: extractionReports.length > 0,
    reports: extractionReports.slice(0, 100),
    updatedAt: extractionReports[0]?.receivedAt || null
  });
});

app.get('/api/extraction-reports/stream', (req, res) => {
  res.set({
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no'
  });
  res.flushHeaders();
  res.write(`event: snapshot\ndata: ${JSON.stringify({
    reports: extractionReports.slice(0, 100),
    updatedAt: extractionReports[0]?.receivedAt || null
  })}\n\n`);
  extractionClients.add(res);

  const heartbeat = setInterval(() => res.write(': keep-alive\n\n'), 25000);
  res.on('close', () => {
    clearInterval(heartbeat);
    extractionClients.delete(res);
  });
});

app.post('/api/extraction-reports', (req, res) => {
  const expectedToken = process.env.EXTRACTION_INGEST_TOKEN;
  if (!expectedToken) {
    return res.status(503).json({ error: 'Extraction ingestion is not configured' });
  }
  if (req.get('authorization') !== `Bearer ${expectedToken}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }

  const result = parseExtractionReport(req.body);
  if (result.error) return res.status(400).json({ error: result.error });
  if (extractionReports.some(report => report.id === result.report.id)) {
    return res.status(409).json({ error: 'A report with this id has already been received' });
  }

  extractionReports.unshift(result.report);
  extractionReports.length = Math.min(extractionReports.length, MAX_EXTRACTION_REPORTS);
  broadcastExtractionReport(result.report);
  res.status(201).json({ message: 'Extraction report accepted', report: result.report });
});

app.post('/api/reports', (req, res) => {
  const payload = req.body || {};
  const report = {
    id: payload.id || `BE-${Date.now()}`,
    period: payload.period || 'Live Backend',
    locality: payload.locality || 'Unspecified locality',
    entity: payload.entity || 'Backend flagged report',
    category: payload.category || 'Municipal',
    typology: payload.typology || 'Backend flagged corruption',
    narrative: payload.narrative || 'Reported via backend ingestion pipeline',
    evidence: payload.evidence || 'Live backend submission',
    amount: Number(payload.amount) || 0,
    praxisLink: payload.praxisLink || 'Power Asymmetry (P)',
    status: payload.status || 'Live Backend',
    created_at: new Date().toISOString()
  };
  reports.unshift(report);
  res.status(201).json({ message: 'Report saved', report });
});

app.get('/api/risk', (req, res) => {
  res.json(fetchRiskHotspots());
});

app.get('/api/social/hashtags', async (req, res) => {
  try {
    const data = await getSocialHashtagTrends();
    res.json(data);
  } catch (err) {
    res.status(500).json({ available: false, error: err.message });
  }
});

app.post('/api/attachments', upload.single('file'), (req, res) => {
  const file = req.file;
  if (!file) {
    return res.status(400).json({ error: 'No file uploaded' });
  }

  let textPreview = '';
  try {
    textPreview = file.buffer.toString('utf-8');
  } catch {
    textPreview = '';
  }

  const summary = textPreview.slice(0, 500) || `Attachment: ${file.originalname} was received and stored for backend review.`;
  const report = {
    id: `ATT-${Date.now()}`,
    period: 'Live Backend',
    locality: 'Unspecified locality',
    entity: 'Attachment Ingestion',
    category: 'Municipal',
    typology: 'Attachment-derived corruption signal',
    narrative: summary,
    evidence: `File Attachment: ${file.originalname}`,
    amount: 0,
    praxisLink: 'Power Asymmetry (P)',
    status: 'Live Backend',
    created_at: new Date().toISOString()
  };

  reports.unshift(report);
  attachments.unshift({
    id: report.id,
    filename: file.originalname,
    summary,
    mimetype: file.mimetype,
    size: file.size,
    created_at: report.created_at
  });

  res.status(201).json({ message: 'Attachment saved', report });
});

// Serve static frontend
app.use(express.static(__dirname));

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, 'index.html'));
});

app.listen(PORT, HOST, () => {
  console.log(`KUVHURA Observatory running on http://${HOST}:${PORT}`);
});
