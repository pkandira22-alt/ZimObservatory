# Automated social telemetry setup

The workflow reads Google News RSS results for Zimbabwe-related queries every 30 minutes and writes an estimated topic sample to the `SocialTelemetry` tab. Each mention is a matching article, not a social post. Narrative velocity is an index adding 10 points per matching article published in the last 24 hours (capped at 100); polarization is a lexical proxy based on contested-language terms (0–10). Neither is a measured social-media count, sentiment, or validated polarization measure. The publisher uses only Python's standard library.

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

## 3. Run and evaluate the forecasting model

The forecast report uses World Bank annual Zimbabwe GDP growth, ZIMSTAT's monthly weighted CPI inflation series, and monthly Yahoo Finance gold futures history. It runs chronological rolling-origin validation, selects methods on earlier origins, and compares a later holdout with a last-observation benchmark. If both Yahoo chart hosts are rate-limited, the dashboard shows a current Gold API spot quote as context but explicitly withholds a gold forecast until historical data is available. It does not treat the dashboard's Φ formula or media mentions as observed outcomes.

Generate a one-time report from the repository root:

```sh
python forecasting_model.py
```

Run the dashboard forecast service:

```sh
python -m pip install -r requirements.txt
python stream_server.py
```

Keep that terminal open. In VS Code, you can instead select **Run Observatory with Forecast Stream** in the Run and Debug panel; it starts both the dashboard and forecast service, and stops both when the compound session ends. The first historical data refresh can take up to 30 seconds; reports refresh every six hours and each completed report is pushed to connected dashboards over WebSocket. The research-pillar indicators show the latest forecast status, not continuously sampled economic observations. Open `index.html` from the same computer to connect to `ws://localhost:8765`. In GitHub Codespaces, forward port `8765` as **Public** or **Private** and open the dashboard in the browser; the page detects the forwarded Codespaces WebSocket hostname automatically. For other hosted setups, append `?ws=wss://YOUR-FORWARDED-WEBSOCKET-HOST` to the dashboard URL. Use `STREAM_HOST` and `STREAM_PORT` to change the server bind address or port; `PORT` takes precedence when supplied by a hosting provider such as Render.

The forecast server answers HTTP checks at `/health` and `/` (including `HEAD` probes) while accepting WebSocket upgrades at `/`. The Render Blueprint in [`render.yaml`](./render.yaml) defines a separate Python service named `zimobservatory-forecast`, with `/health` as its health-check path. The GitHub Pages dashboard connects to `wss://zimobservatory.onrender.com/` by default; local development and Codespaces keep their existing WebSocket URLs. Render's injected `PORT` is used automatically.

Forecasts are not automatically considered validated: GDP and inflation show a persistence baseline when tested alternatives fail to beat it; the inflation series is the recent monthly weighted CPI reported by ZIMSTAT. The gold trend is provisional because its 12-month holdout origins overlap. Protest forecasts require a dated event dataset; Φ requires historical inputs and a measured outcome. Institutional audit and procurement indicators remain unconnected until a structured, dated source is configured. No custom target was requested.

### Political economy time series

The dashboard time-series panel offers four series aligned to Φ or Realized Praxis drivers. Download its CSV template and import observations with columns `series,period,metric,value,unit,source,source_url`. Accepted periods are annual (`YYYY`), quarterly (`YYYY-Q1`), monthly (`YYYY-MM`), weekly (`YYYY-W01`), or daily (`YYYY-MM-DD`). Every observation needs an HTTP(S) source URL. Future-dated values are rejected, so 2030 remains a horizon rather than a reported observation.

The time slider displays the selected series cumulatively through the chosen period. Imported values are stored only in the current browser and are not uploaded or shared. The panel starts empty: it does not synthesize missing FX, payroll, OAG, narrative, or throttling data, and its driver series are not historical Φ/Praxis scores.

#### Source availability

| Candidate series | Public source | Coverage and limitation |
|---|---|---|
| Monthly inflation + parallel FX premium | The dashboard reads ZIMSTAT's monthly weighted CPI workbook (the current index series starts in April 2024); [ZIMSTAT CPI releases](https://zimstat.co.zw/consumer-price-index/) publish the monthly PDF/XLS files. [RBZ exchange rates](https://www.rbz.co.zw/index.php/research/markets/exchange-rates) provide an official-rate reference. | Currency/weight/methodology changes need review. No matched, source-attributable historical parallel-market rate series was identified. World Bank CPI is annual and is not substituted for missing monthly data. |
| Remittances + civil-service purchasing power | [World Bank personal remittances received API](https://api.worldbank.org/v2/country/ZW/indicator/BX.TRF.PWKR.CD.DT?format=json&per_page=200). | Annual current US$ observations include personal transfers and compensation of employees. No public machine-readable civil-service pay series by grade, currency, and period was identified. |
| Auditor-General leakage | [Auditor-General document library](https://auditorgeneral.gov.zw/document-library/) and its [WordPress API](https://auditorgeneral.gov.zw/wp-json/wp/v2/pages/262). | The index links to reports rather than structured leakage values; the checked library listed reports for 2021–2025. Audit findings are not automatically proven losses. 2018–2030 is not a continuous observed series, and 2026–2030 cannot be filled with projections. |
| Narrative velocity + throttling | [GDELT DOC API](https://api.gdeltproject.org/api/v2/doc/doc?query=Zimbabwe&mode=timelinevol&format=json) and [OONI Zimbabwe measurements](https://api.ooni.io/api/v1/measurements?probe_cc=ZW&limit=2). | GDELT volume is news coverage, not social-media activity. OONI provides individual network measurements; anomalies alone do not prove deliberate throttling or state attribution. No direct, continuous state-throttling series was identified. |

These are source leads, not preloaded observations. For any imported data, retain the source's dates, definitions, units, and caveats; only compare periods after checking comparability.

## 4. Configure the KUVHURA backend

Set `GOOGLE_SHEETS_WEB_APP_URL` in the environment of the Node.js backend (`server.js`), using the same deployed URL. Restart the backend after setting it. The dashboard's social telemetry panel then loads from the sheet automatically; no sheet ID or link needs to be entered in the dashboard.

For local development, copy `.env.example` to `.env` and set the variable there, or set it in the shell before starting the server. `npm run dev` and `npm start` load `.env` automatically. Without it, the dashboard keeps using its existing direct Bluesky and Mastodon feeds.

### Configure the AI copilot

The copilot's cloud responses require a Gemini API key on the Node.js backend. Copy `.env.example` to `.env`, set `GEMINI_API_KEY` to your key, and start the app with `npm run dev`. Keep `.env` private; it is ignored by Git. The backend also accepts a `GEMINIKEY` environment variable. The VS Code **Run KUVHURA Observatory** launch configuration starts the backend and opens the dashboard at `http://localhost:3000`.

Without a key, the dashboard still offers its empirical offline reasoning engine. Cloud AI requires the Node.js backend: GitHub Pages and other static hosts cannot serve the `/api/ai/*` routes. For local use, start the backend and open its port 3000 URL rather than opening `index.html` directly or using a separate static server.

To deploy the GitHub Pages backend and forecast stream on Render:

1. In Render, create a Blueprint from this repository using [`render.yaml`](./render.yaml), or sync the existing Blueprint after these changes are pushed. This defines both the Node.js API and Python forecast WebSocket services. Set `GEMINI_API_KEY` if prompted; never put the key in the repository.
2. Wait for both Render services to become healthy: `/api/health` for the backend and `/health` for the forecast service. The Pages dashboard uses the forecast service URL above. If Render assigns a different forecast URL, open the dashboard with `?ws=wss://YOUR-FORECAST-SERVICE.onrender.com/`. If the backend URL differs from `https://zimobservatory-backend.onrender.com`, update `KUVHURA_API_BASE_URL` in [`api-config.js`](./api-config.js) to the assigned HTTPS origin and redeploy the Pages site.
3. Reload the dashboard. Render's free services may take a short time to wake after inactivity.

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
