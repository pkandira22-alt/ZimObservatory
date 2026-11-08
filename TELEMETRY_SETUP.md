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

The forecast report uses World Bank annual Zimbabwe GDP growth and inflation indicators and monthly Yahoo Finance gold futures history. It runs chronological rolling-origin validation, selects methods on earlier origins, and compares a later holdout with a last-observation benchmark. It does not treat the dashboard's Φ formula or media mentions as observed outcomes.

Generate a one-time report from the repository root:

```sh
python forecasting_model.py
```

Run the dashboard forecast service:

```sh
python -m pip install -r requirements.txt
python stream_server.py
```

Keep that terminal open. The first historical data refresh can take up to 30 seconds; reports refresh every six hours and each completed report is pushed to connected dashboards over WebSocket. The research-pillar indicators show the latest forecast status, not continuously sampled economic observations. Open `index.html` from the same computer to connect to `ws://localhost:8765`. In GitHub Codespaces, forward port `8765` as **Public** or **Private** and open the dashboard in the browser; the page detects the forwarded Codespaces WebSocket hostname automatically. For other hosted setups, append `?ws=wss://YOUR-FORWARDED-WEBSOCKET-HOST` to the dashboard URL. Use `STREAM_HOST` and `STREAM_PORT` to change the server bind address or port.

Forecasts are not automatically considered validated: the dashboard withholds stale inflation data, reports GDP as a persistence baseline when alternatives fail to beat it, and labels the gold trend provisional because its 12-month holdout origins overlap. Protest forecasts require a dated event dataset; Φ requires historical inputs and a measured outcome. Institutional audit and procurement indicators remain unconnected until a structured, dated source is configured. No custom target was requested.

## 4. Configure the KUVHURA backend

Set `GOOGLE_SHEETS_WEB_APP_URL` in the environment of the Node.js backend (`server.js`), using the same deployed URL. Restart the backend after setting it. The dashboard's social telemetry panel then loads from the sheet automatically; no sheet ID or link needs to be entered in the dashboard.

For local development, set the variable in the shell before starting the server. Without it, the dashboard keeps using its existing direct Bluesky and Mastodon feeds.
