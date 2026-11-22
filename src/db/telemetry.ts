import { desc } from 'drizzle-orm';
import { db, isCloudSqlConfigured } from './index.ts';
import { dailyTelemetrySnapshots } from './schema.ts';

export interface TelemetryTimelineEntry {
  date: string;
  phi: number;
  markov_crisis_prob: number;
  state: string;
  macro_volatility_proxy?: number;
  hansard_friction?: number;
  treasury_friction?: number;
  fsi?: number;
  warning_level?: string;
  social_volume: number;
  engagement_score_proxy: number;
  telemetry_source: string;
  sampled_platforms?: string[];
  tracked_topics?: unknown[];
  updated_at: string;
  persisted?: boolean;
}

function toFiniteOrNull(val: unknown): number | null {
  return typeof val === 'number' && Number.isFinite(val) ? val : null;
}

export async function upsertDailyTelemetrySnapshot(
  entry: TelemetryTimelineEntry,
  recordedByUid?: string | null
): Promise<TelemetryTimelineEntry | null> {
  if (!isCloudSqlConfigured()) {
    return null;
  }
  if (
    !entry ||
    typeof entry.date !== 'string' ||
    !/^\d{4}-\d{2}-\d{2}$/.test(entry.date) ||
    !Number.isFinite(entry.phi) ||
    !Number.isFinite(entry.markov_crisis_prob) ||
    !Number.isFinite(entry.social_volume)
  ) {
    throw new Error('Invalid daily telemetry snapshot payload.');
  }

  const now = entry.updated_at ? new Date(entry.updated_at) : new Date();
  const validNow = Number.isNaN(now.getTime()) ? new Date() : now;

  try {
    const [saved] = await db
      .insert(dailyTelemetrySnapshots)
      .values({
        date: entry.date,
        phi: entry.phi,
        markovCrisisProb: entry.markov_crisis_prob,
        state: String(entry.state || 'Latent Friction'),
        macroVolatilityProxy: toFiniteOrNull(entry.macro_volatility_proxy),
        hansardFriction: toFiniteOrNull(entry.hansard_friction),
        treasuryFriction: toFiniteOrNull(entry.treasury_friction),
        fsi: toFiniteOrNull(entry.fsi),
        warningLevel: entry.warning_level ? String(entry.warning_level) : null,
        socialVolume: Math.max(0, Math.round(entry.social_volume)),
        engagementScoreProxy: Math.max(
          0,
          Math.round(Number.isFinite(entry.engagement_score_proxy) ? entry.engagement_score_proxy : 0)
        ),
        telemetrySource: String(entry.telemetry_source || 'Node social telemetry'),
        sampledPlatforms: Array.isArray(entry.sampled_platforms) ? entry.sampled_platforms : [],
        trackedTopics: Array.isArray(entry.tracked_topics) ? entry.tracked_topics : [],
        recordedByUid: recordedByUid ?? null,
        updatedAt: validNow,
      })
      .onConflictDoUpdate({
        target: dailyTelemetrySnapshots.date,
        set: {
          phi: entry.phi,
          markovCrisisProb: entry.markov_crisis_prob,
          state: String(entry.state || 'Latent Friction'),
          macroVolatilityProxy: toFiniteOrNull(entry.macro_volatility_proxy),
          hansardFriction: toFiniteOrNull(entry.hansard_friction),
          treasuryFriction: toFiniteOrNull(entry.treasury_friction),
          fsi: toFiniteOrNull(entry.fsi),
          warningLevel: entry.warning_level ? String(entry.warning_level) : null,
          socialVolume: Math.max(0, Math.round(entry.social_volume)),
          engagementScoreProxy: Math.max(
            0,
            Math.round(Number.isFinite(entry.engagement_score_proxy) ? entry.engagement_score_proxy : 0)
          ),
          telemetrySource: String(entry.telemetry_source || 'Node social telemetry'),
          sampledPlatforms: Array.isArray(entry.sampled_platforms) ? entry.sampled_platforms : [],
          trackedTopics: Array.isArray(entry.tracked_topics) ? entry.tracked_topics : [],
          updatedAt: validNow,
        },
      })
      .returning();

    return saved ? mapRowToTimelineEntry(saved) : null;
  } catch (error) {
    console.error('Database telemetry snapshot upsert failed:', error);
    throw new Error('Failed to persist daily telemetry snapshot.', { cause: error });
  }
}

export async function getRecentDailyTelemetrySnapshots(
  limitDays = 30
): Promise<TelemetryTimelineEntry[]> {
  if (!isCloudSqlConfigured()) {
    return [];
  }
  const safeLimit = Math.max(1, Math.min(90, Math.floor(limitDays)));
  try {
    const rows = await db
      .select()
      .from(dailyTelemetrySnapshots)
      .orderBy(desc(dailyTelemetrySnapshots.date))
      .limit(safeLimit);

    return rows.reverse().map(mapRowToTimelineEntry);
  } catch (error) {
    console.error('Database telemetry snapshot query failed:', error);
    throw new Error('Failed to load persisted telemetry history.', { cause: error });
  }
}

function mapRowToTimelineEntry(
  row: typeof dailyTelemetrySnapshots.$inferSelect
): TelemetryTimelineEntry {
  const entry: TelemetryTimelineEntry = {
    date: row.date,
    phi: row.phi,
    markov_crisis_prob: row.markovCrisisProb,
    state: row.state,
    social_volume: row.socialVolume,
    engagement_score_proxy: row.engagementScoreProxy,
    telemetry_source: row.telemetrySource,
    updated_at: row.updatedAt instanceof Date ? row.updatedAt.toISOString() : String(row.updatedAt),
    persisted: true,
  };
  if (typeof row.macroVolatilityProxy === 'number' && Number.isFinite(row.macroVolatilityProxy)) {
    entry.macro_volatility_proxy = row.macroVolatilityProxy;
  }
  if (typeof row.hansardFriction === 'number' && Number.isFinite(row.hansardFriction)) {
    entry.hansard_friction = row.hansardFriction;
  }
  if (typeof row.treasuryFriction === 'number' && Number.isFinite(row.treasuryFriction)) {
    entry.treasury_friction = row.treasuryFriction;
  }
  if (typeof row.fsi === 'number' && Number.isFinite(row.fsi)) {
    entry.fsi = row.fsi;
  }
  if (row.warningLevel) {
    entry.warning_level = row.warningLevel;
  }
  if (Array.isArray(row.sampledPlatforms) && row.sampledPlatforms.length > 0) {
    entry.sampled_platforms = row.sampledPlatforms;
  }
  if (Array.isArray(row.trackedTopics) && row.trackedTopics.length > 0) {
    entry.tracked_topics = row.trackedTopics;
  }
  return entry;
}
