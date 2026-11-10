# Social and news telemetry setup

The scheduled `SocialTelemetry` workflow reads Google News RSS, not social platforms. Its article mentions and estimated topic scores are separate from the dashboard's public social hashtag tracker; news articles are never counted as social posts.

## 1. Deploy the Google Apps Script bridge

Open the target Google Sheet, choose **Extensions → Apps Script**, and replace the editor contents with [`automation/google_apps_script.gs`](./automation/google_apps_script.gs). Save the project.

In Apps Script **Project Settings → Script Properties**, add:

- Property: `SYNC_TOKEN`
- Value: generate a long random token and keep it private

Deploy as a **Web app**, executing as yourself, with access set to **Anyone**. Copy the deployment URL. The read endpoint returns only the telemetry data; writes require the token.

When changing the Apps Script later, saving the editor is not enough to update the live web app. Open **Deploy → Manage deployments**, edit the web app deployment, select **New version**, and deploy it. Keep the same deployment URL in the GitHub secret.

## 2. Configure GitHub Actions

In the repository's **Settings → Secrets and variables → Actions**, configure:

- `PRIVILEGE`: the deployed web app URL
- `KUVHURA`: the same token stored as `SYNC_TOKEN`

The workflow maps these secrets to the publisher's `GOOGLE_SHEETS_WEB_APP_URL` and `GOOGLE_SHEETS_WEB_APP_TOKEN` environment variables. It uses only Python's standard library, so no dependency installation is needed. The scheduled workflow is [`.github/workflows/telemetry_sync.yml`](./.github/workflows/telemetry_sync.yml). It runs every 30 minutes and can also be started with **Actions → KUVHURA Live Social Telemetry Sync → Run workflow**.

## 3. Run the live telemetry stream

The public dashboard is limited to the KUVHURA core summary, Asymmetric Force Equilibrium model, and live Zimbabwe trending telemetry. The core indicators are model summary values, not live measurements. The telemetry is sampled from recent public posts matching Zimbabwe; it is not a platform-wide or global ranking.

Start the Render-compatible WebSocket and health service from the repository root:

```sh
python -m pip install -r requirements.txt
python stream_server.py
```

The HTTP server starts before fetching telemetry, so `/health` can answer while the Node.js backend or public feeds are waking up. The service sends a loading status immediately to new WebSocket clients, fetches the latest `/api/social/hashtags` snapshot in a worker thread, then broadcasts JSON updates every 60 seconds. Configure `KUVHURA_API_BASE_URL` if the Node.js backend is hosted at a different origin. Open `index.html` locally to connect to `ws://localhost:8765`. In GitHub Codespaces, forward port `8765` and open the dashboard; the page detects the forwarded hostname. For other hosted setups, use `?ws=wss://YOUR-STREAM-SERVICE.onrender.com/`. `PORT` takes precedence over `STREAM_PORT` when supplied by Render.

The service responds to health checks at `/health` and `/` (including `HEAD` probes), and accepts WebSocket upgrades at `/`. The Render Blueprint in [`render.yaml`](./render.yaml) uses `python stream_server.py` as the Python service start command. Render's injected `PORT` is used automatically.

### Prescriptive Strategic Orientation Engine

The stream evaluates an orientation only when the backend snapshot includes an `orientationInputs` object containing all four finite numeric fields `regime_durability_index`, `realized_praxis_yield`, `parallel_fx_premium`, and `coercive_load`. Each field must already be normalized to 0–100; the engine does not infer, scale, or substitute missing measurements. The social hashtag endpoint currently does not supply these values, so the dashboard normally reports that it is awaiting inputs.

The experimental `heuristic-v1` matrix emits scores from 0–100 for decentralized mutual aid, structural negotiation, and defensive consolidation. Its respective weights are: low Φ (0.20), Yield (0.30), Pr (0.25), and low CL (0.25); Φ (0.30), Yield (0.20), low Pr (0.20), and low CL (0.30); low Φ (0.25), low Yield (0.20), Pr (0.10), and CL (0.45). The highest score is selected, with ties resolved in the listed order. These uncalibrated assumptions are for prototyping and are not validated recommendations.

Each polling cycle writes a structured orientation evaluation to the stream service's operational logs, including an abstention when inputs are missing or invalid. This log is not durable history. To enable evaluations, the telemetry producer must publish the four normalized values in `orientationInputs`; do not repurpose the dashboard's static summary figures or social counts as substitutes.

## 4. Configure the KUVHURA backend

The Node.js backend samples recent Zimbabwe-matching public posts from Bluesky, three Mastodon instances and Reddit, counts hashtags in that sample, and reports the status and sample size of each feed. The Python WebSocket service broadcasts the backend snapshot to the dashboard. Optional X searches are cached for five minutes and YouTube searches for 15 minutes to respect provider rate limits and quota. The telemetry is not a platform-wide or global ranking. If feeds fail, the dashboard reports that instead of showing synthetic fallback values.

To add optional platform feeds, set `X_BEARER_TOKEN` to an authorized X API bearer token with recent-search access and/or `YOUTUBE_API_KEY` to a YouTube Data API v3 key in the Node.js backend environment. Keep both values private; `npm run dev` and `npm start` load values from `.env`. X search access and quotas depend on the X developer plan. YouTube contributes hashtags appearing in recent Zimbabwe-related video titles/descriptions, not a YouTube-wide hashtag trend ranking; its search endpoint has a substantially higher quota cost than ordinary API reads.

On Render, add these as environment variables to the `zimobservatory-backend` service, not the forecast service. After saving the variables, redeploy or restart the backend to load them.

Instagram/Facebook and Threads graph access is permission-scoped; TikTok research APIs are restricted; and WhatsApp has no public hashtag search endpoint. They are not included without a suitable authorized data provider. Counts across sources are sample counts, not comparable audience reach, validated sentiment, or population-wide opinion. Public API delays, quotas and outages can reduce coverage.

`GOOGLE_SHEETS_WEB_APP_URL` and `GOOGLE_SHEETS_WEB_APP_TOKEN` are used by the separate GitHub Actions news-to-Sheets publisher, not by the live social tracker.

### Configure the AI copilot

The copilot's cloud responses require a Gemini API key on the Node.js backend. Copy `.env.example` to `.env`, set `GEMINI_API_KEY` to your key, and start the app with `npm run dev`. Keep `.env` private; it is ignored by Git. The backend also accepts a `GEMINIKEY` environment variable. The VS Code **Run KUVHURA Observatory** launch configuration starts the backend and opens the dashboard at `http://localhost:3000`.

Without a key, the dashboard still offers its empirical offline reasoning engine. Cloud AI requires the Node.js backend: GitHub Pages and other static hosts cannot serve the `/api/ai/*` routes. For local use, start the backend and open its port 3000 URL rather than opening `index.html` directly or using a separate static server.

To deploy the GitHub Pages backend and telemetry stream on Render:

1. In Render, create a Blueprint from this repository using [`render.yaml`](./render.yaml), or sync the existing Blueprint after these changes are pushed. This defines both the Node.js API and Python WebSocket services. Set `GEMINI_API_KEY` only if needed by other backend routes; never put the key in the repository.
2. Wait for `/api/health` on the Node.js backend and `/health` on the Python stream service. The stream service uses `KUVHURA_API_BASE_URL` to fetch snapshots; update that environment variable if the Node.js service URL changes.
3. If Render assigns a different WebSocket URL, open the Pages dashboard with `?ws=wss://YOUR-STREAM-SERVICE.onrender.com/`. The page and health endpoint respond without waiting for public feeds; live trends appear when the backend snapshot arrives.

The browser configuration contains only the public backend URL. The Gemini key remains on the backend and is never sent to the browser.

## 5. Stream reported extraction quantities to the map and model

The repository does not currently contain a structured, dated mine-output feed. Its mining map pins are approximate location references, its mining-related social telemetry counts article mentions, and the gold forecast is a market price series; none of those is an extraction quantity. The map therefore starts empty rather than presenting estimates as live production. I checked the [ZIMSTAT mining search](https://zimstat.co.zw/?s=mining) and [MMCZ news](https://www.mmcz.co.zw/news): the public pages provide statistical releases and sector updates, but no machine-readable, mine-level live extraction feed was available. ZIMSTAT's Business Tendency Survey describes quarterly mining capacity-utilization and confidence indicators, not physical quantities. Use ZIMSTAT or Minerals Marketing Corporation publications, or company production reports, only at the cadence and detail actually published by those sources.

To publish a source-attributed report, set `EXTRACTION_INGEST_TOKEN` in the Node.js backend environment and restart the server. A trusted reporter sends each new report to `POST /api/extraction-reports` with an `Authorization: Bearer <token>` header and JSON shaped like:

```json
{
  "id": "source-report-id",
  "siteId": "great-dyke",
  "resource": "gold",
  "quantity": 123.4,
  "unit": "kg",
  "period": "2026-Q3",
  "reportedAt": "2026-10-15T00:00:00Z",
  "source": "Publisher and report title",
  "sourceUrl": "https://publisher.example/report"
}
```

Use only `great-dyke` or `marange` for the currently mapped mining locations; reports for other locations are rejected until the map has a verified location reference. `quantity` and `unit` must reflect the cited source exactly. The API validates the source URL and attribution, then sends accepted reports over `GET /api/extraction-reports/stream` (Server-Sent Events). The map updates its markers and report list, while the Gemini prompt receives the latest reports with an instruction to treat them as unverified reported data. The offline assistant can also display those reports when asked about extraction. No values are synthesized when the feed is empty.

The current Node service keeps extraction reports in memory (up to 500 records), so they are lost when it restarts. The reporter must retain its source data and replay it after restart, or a persistent store should be configured before production use. A live display reflects when a report is ingested; it does not mean the underlying mine output is measured continuously.
