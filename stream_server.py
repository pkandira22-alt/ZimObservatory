import asyncio
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from aiohttp import web

CONNECTED_CLIENTS = set()
LATEST_TRENDS = None
TREND_REFRESH_SECONDS = 60
TREND_REQUEST_TIMEOUT_SECONDS = 15
DEFAULT_API_BASE_URL = "https://zimobservatory-backend.onrender.com"


async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client connected ({len(CONNECTED_CLIENTS)} total)")
    if LATEST_TRENDS is not None:
        await websocket.send_json(LATEST_TRENDS)
    else:
        await websocket.send_json({
            "type": "stream_status",
            "status": "loading",
            "message": "Waiting for the first Zimbabwe trending telemetry snapshot.",
        })


async def unregister(websocket):
    CONNECTED_CLIENTS.discard(websocket)
    print(f"[{datetime.now(timezone.utc).isoformat()}] Client disconnected ({len(CONNECTED_CLIENTS)} remaining)")


def fetch_trending_telemetry():
    base_url = os.environ.get("KUVHURA_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")
    request = urllib.request.Request(
        f"{base_url}/api/social/hashtags",
        headers={
            "Accept": "application/json",
            "User-Agent": "KUVHURA-Observatory/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=TREND_REQUEST_TIMEOUT_SECONDS) as response:
        payload = json.load(response)

    if not isinstance(payload, dict) or not isinstance(payload.get("hashtags"), list):
        raise ValueError("Social telemetry endpoint returned an unexpected response")

    return {
        "type": "trending_telemetry",
        "status": "available" if payload.get("available") else "no_sources",
        "updatedAt": payload.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
        "telemetry": payload,
        **({"message": payload["message"]} if payload.get("message") else {}),
    }


async def broadcast(packet):
    for websocket in tuple(CONNECTED_CLIENTS):
        if websocket.closed:
            await unregister(websocket)
            continue
        try:
            await websocket.send_json(packet)
        except (ConnectionResetError, RuntimeError) as error:
            print(f"Telemetry delivery failed; removing disconnected client: {error}")
            await unregister(websocket)


async def refresh_trending_telemetry():
    global LATEST_TRENDS
    while True:
        try:
            LATEST_TRENDS = await asyncio.to_thread(fetch_trending_telemetry)
            print(
                f"Zimbabwe trending telemetry refreshed at "
                f"{LATEST_TRENDS['updatedAt']} ({LATEST_TRENDS['status']})"
            )
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
            LATEST_TRENDS = {
                "type": "trending_telemetry",
                "status": "error",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
                "message": f"Zimbabwe trending telemetry could not be loaded: {error}",
                "telemetry": None,
            }
            print(LATEST_TRENDS["message"])

        await broadcast(LATEST_TRENDS)
        await asyncio.sleep(TREND_REFRESH_SECONDS)


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
    trends_task = asyncio.create_task(refresh_trending_telemetry())
    try:
        print(f"KUVHURA telemetry and health server listening on {host}:{port}")
        await trends_task
    finally:
        trends_task.cancel()
        await asyncio.gather(trends_task, return_exceptions=True)
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForecast server stopped.")
