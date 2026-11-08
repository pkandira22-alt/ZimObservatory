import asyncio
import json
import os
import urllib.error
from datetime import datetime, timezone

import websockets

from forecasting_model import build_forecast_report


CONNECTED_CLIENTS = set()
LATEST_REPORT = None


async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client connected ({len(CONNECTED_CLIENTS)} total)")
    if LATEST_REPORT is not None:
        await websocket.send(json.dumps(LATEST_REPORT))


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
            if CONNECTED_CLIENTS:
                websockets.broadcast(CONNECTED_CLIENTS, json.dumps(LATEST_REPORT))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as error:
            print(f"Forecast refresh failed: {error}")
            refresh_interval = 5 * 60
        await asyncio.sleep(refresh_interval)


async def handler(websocket):
    try:
        await register(websocket)
        await websocket.wait_closed()
    finally:
        await unregister(websocket)


async def main():
    host = os.environ.get("STREAM_HOST", "0.0.0.0")
    port = int(os.environ.get("STREAM_PORT", "8765"))
    async with websockets.serve(handler, host, port):
        print(f"KUVHURA forecast WebSocket listening on {host}:{port}")
        await refresh_forecasts()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForecast server stopped.")
