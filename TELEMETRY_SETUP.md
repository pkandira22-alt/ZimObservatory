# Automated social telemetry setup

The workflow reads Google News RSS results for Zimbabwe-related queries every 30 minutes and writes an estimated topic sample to the `SocialTelemetry` tab. Each mention is a matching article, not a social post. Narrative velocity is an index adding 10 points per matching article published in the last 24 hours (capped at 100); polarization is a lexical proxy based on contested-language terms (0–10). Neither is a measured social-media count, sentiment, or validated polarization measure. The publisher uses only Python's standard library.

## 1. Deploy the Google Apps Script bridge

Open the target Google Sheet, choose **Extensions → Apps Script**, and replace the editor contents with [`automation/google_apps_script.gs`](./automation/google_apps_script.gs). Save the project.

In Apps Script **Project Settings → Script Properties**, add:

- Property: `SYNC_TOKEN`
- Value: generate a long random token and keep it private

Deploy as a **Web app**, executing as yourself, with access set to **Anyone**. Copy the deployment URL. The read endpoint returns only the telemetry data; writes require the token.

## 2. Configure GitHub Actions

In the repository's **Settings → Secrets and variables → Actions**, add:

- `GOOGLE_SHEETS_WEB_APP_URL`: the deployed web app URL
- `GOOGLE_SHEETS_WEB_APP_TOKEN`: the same token stored as `SYNC_TOKEN`

The scheduled workflow is [`.github/workflows/telemetry_sync.yml`](./.github/workflows/telemetry_sync.yml). It runs every 30 minutes and can also be started with **Actions → KUVHURA Live Social Telemetry Sync → Run workflow**.

## 3. Configure the KUVHURA backend

Set `GOOGLE_SHEETS_WEB_APP_URL` in the environment of the Node.js backend (`server.js`), using the same deployed URL. Restart the backend after setting it. The dashboard's social telemetry panel then loads from the sheet automatically; no sheet ID or link needs to be entered in the dashboard.

For local development, set the variable in the shell before starting the server. Without it, the dashboard keeps using its existing direct Bluesky and Mastodon feeds.
