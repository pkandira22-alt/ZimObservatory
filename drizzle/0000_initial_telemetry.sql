CREATE TABLE "daily_telemetry_snapshots" (
	"date" text PRIMARY KEY NOT NULL,
	"phi" double precision NOT NULL,
	"markov_crisis_prob" double precision NOT NULL,
	"state" text NOT NULL,
	"macro_volatility_proxy" double precision,
	"hansard_friction" double precision,
	"treasury_friction" double precision,
	"fsi" double precision,
	"warning_level" text,
	"social_volume" integer NOT NULL,
	"engagement_score_proxy" integer NOT NULL,
	"telemetry_source" text NOT NULL,
	"sampled_platforms" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"tracked_topics" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"recorded_by_uid" text,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" serial PRIMARY KEY NOT NULL,
	"uid" text NOT NULL,
	"email" text NOT NULL,
	"display_name" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "users_uid_unique" UNIQUE("uid")
);
--> statement-breakpoint
ALTER TABLE "daily_telemetry_snapshots" ADD CONSTRAINT "daily_telemetry_snapshots_recorded_by_uid_users_uid_fk" FOREIGN KEY ("recorded_by_uid") REFERENCES "public"."users"("uid") ON DELETE no action ON UPDATE no action;