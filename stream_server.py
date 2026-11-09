import asyncio
import os
import urllib.error
from datetime import datetime, timezone

from aiohttp import web

from forecasting_model import build_forecast_report


CONNECTED_CLIENTS = set()
LATEST_REPORT = None


async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client connected ({len(CONNECTED_CLIENTS)} total)")
    if LATEST_REPORT is not None:
        await websocket.send_json(LATEST_REPORT)


async def unregister(websocket):
    CONNECTED_CLIENTS.discard(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client disconnected ({len(CONNECTED_CLIENTS)} remaining)")


async def refresh_forecasts():
    global LATEST_REPORT
    while True:
        refresh_interval = 6 * 60 * 60
        try:
            LATEST_REPORT = await asyncio.to_thread(build_forecast_report)
            print(f"Forecast report refreshed at {LATEST_REPORT['generatedAt']}")
            for websocket in tuple(CONNECTED_CLIENTS):
                if websocket.closed:
                    await unregister(websocket)
                    continue
                try:
                    await websocket.send_json(LATEST_REPORT)
                except ConnectionResetError as error:
                    print(f"Forecast delivery failed; removing disconnected client: {error}")
                    await unregister(websocket)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            print(f"Forecast refresh failed: {error}")
            refresh_interval = 5 * 60
        await asyncio.sleep(refresh_interval)


async def health(_request):
    return web.Response(text="ok\n")


async def live_endpoint(request):
    websocket = web.WebSocketResponse()
    if not websocket.can_prepare(request).ok:
        return await health(request)

    await websocket.prepare(request)
    try:
        await register(websocket)
        async for _message in websocket:
            pass
    finally:
        await unregister(websocket)
    return websocket


def create_app():
    app = web.Application()
    app.router.add_route("*", "/", live_endpoint)
    app.router.add_route("*", "/health", health)
    return app


async def main():
    host = os.environ.get("STREAM_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("STREAM_PORT", "8765")))
    runner = web.AppRunner(create_app())
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    try:
        print(f"KUVHURA forecast and health server listening on {host}:{port}")
        await refresh_forecasts()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForecast server stopped.")
