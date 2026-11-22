import { relations } from 'drizzle-orm';
import {
  doublePrecision,
  integer,
  jsonb,
  pgTable,
  serial,
  text,
  timestamp,
} from 'drizzle-orm/pg-core';

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  uid: text('uid').notNull().unique(),
  email: text('email').notNull(),
  displayName: text('display_name'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const dailyTelemetrySnapshots = pgTable('daily_telemetry_snapshots', {
  date: text('date').primaryKey(), // Format: YYYY-MM-DD
  phi: doublePrecision('phi').notNull(),
  markovCrisisProb: doublePrecision('markov_crisis_prob').notNull(),
  state: text('state').notNull(),
  macroVolatilityProxy: doublePrecision('macro_volatility_proxy'),
  hansardFriction: doublePrecision('hansard_friction'),
  treasuryFriction: doublePrecision('treasury_friction'),
  fsi: doublePrecision('fsi'),
  warningLevel: text('warning_level'),
  socialVolume: integer('social_volume').notNull(),
  engagementScoreProxy: integer('engagement_score_proxy').notNull(),
  telemetrySource: text('telemetry_source').notNull(),
  sampledPlatforms: jsonb('sampled_platforms').$type<string[]>().notNull().default([]),
  trackedTopics: jsonb('tracked_topics').$type<unknown[]>().notNull().default([]),
  recordedByUid: text('recorded_by_uid').references(() => users.uid),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

export const usersRelations = relations(users, ({ many }) => ({
  telemetrySnapshots: many(dailyTelemetrySnapshots),
}));

export const dailyTelemetrySnapshotsRelations = relations(
  dailyTelemetrySnapshots,
  ({ one }) => ({
    recordedBy: one(users, {
      fields: [dailyTelemetrySnapshots.recordedByUid],
      references: [users.uid],
    }),
  })
);
