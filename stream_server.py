import asyncio
import json
import random
import websockets
from datetime import datetime

CONNECTED_CLIENTS = set()

async def register(websocket):
    CONNECTED_CLIENTS.add(websocket)
    print(f"[{datetime.now()}] Client connected")

async def unregister(websocket):
    CONNECTED_CLIENTS.remove(websocket)
    print(f"[{datetime.now()}] Client disconnected")

async def broadcast(message):
    if CONNECTED_CLIENTS:
        websockets.broadcast(CONNECTED_CLIENTS, json.dumps(message))

async def live_data_ingestion_loop():
    while True:
        try:
            gold_price = 2650.0 + random.uniform(-12.0, 12.0)
            rent_extraction_e = round(min(10.0, max(3.0, (gold_price / 2500) * 8.8)), 1)
            
            pr = 7.6  
            cl = 8.9  
            al = 2.8  
            db = 6.8  
            
            regime_phi = round((rent_extraction_e * pr * cl) / ((al * db) + 0.1), 1)
            praxis_yield = round((8.0 * max(1.0, al * 1.1)) / (rent_extraction_e + pr + cl), 2)

            payload = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "goldPrice": round(gold_price, 2),
                "rentExtractionE": rent_extraction_e,
                "regimePhi": regime_phi,
                "praxisYield": praxis_yield,
                "trendingVector": "Live Stream: #ZimResources & #MutapaLeads Active Surge",
                "narrativeVelocity": round(random.uniform(78.0, 96.5), 1),
                "polarizationIndex": round(random.uniform(7.0, 9.2), 1)
            }

            await broadcast(payload)
            print(f"[{datetime.now()}] Broadcasted live packet -> Φ: {regime_phi} | Yield: {praxis_yield}")
        except Exception as e:
            print(f"Stream error: {e}")

        await asyncio.sleep(2)

async def handler(websocket):
    await register(websocket)
    try:
        async for message in websocket:
            pass
    except websockets.ConnectionClosed:
        pass
    finally:
        await unregister(websocket)

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("🚀 KUVHURA Real-Time Streaming Server running on ws://localhost:8765")
        await live_data_ingestion_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped.")
