# Automated social telemetry setup

The workflow reads public RSS feeds every 30 minutes and writes an estimated hashtag sample to the `SocialTelemetry` tab. The dashboard reads that tab through the existing Python backend on startup and refreshes it periodically. Feed article matches and the derived mention, velocity, and polarization values are estimates, not a census of social posts or a sentiment analysis.

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

Set `GOOGLE_SHEETS_WEB_APP_URL` in the environment of the server running `server.py`, using the same deployed URL. Restart the backend after setting it. The dashboard's social telemetry panel then loads from the sheet automatically; no sheet ID or link needs to be entered in the dashboard.

For local development, set the variable in the shell before starting the server. Without it, the dashboard keeps using its existing direct Bluesky and Mastodon feeds.
