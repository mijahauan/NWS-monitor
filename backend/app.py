import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from backend.nws_data import load_nws_data, get_coordinates_from_input, get_stations_in_range
from backend.radio_controller import RadioController
from backend.audio_streamer import streamer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory for the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

controller = RadioController()
active_websockets = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("NWS Monitor startup...")
    load_nws_data()
    await controller.connect()
    yield
    # Shutdown
    logger.info("NWS Monitor shutdown...")
    # streamer.close_all() # Implement if needed
    await controller.close()

app = FastAPI(lifespan=lifespan)

# Mount local frontend
frontend_dir = os.path.join(BASE_DIR, "frontend")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def get_index():
    index_path = os.path.join(frontend_dir, "index.html")
    with open(index_path, "r") as f:
        return HTMLResponse(f.read())

@app.websocket("/ws/control")
async def websocket_control(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "search":
                loc = data.get("location")
                squelch_db = float(data.get("squelch", 10.0))
                radius_km = float(data.get("radius", 100.0))
                gain_db = float(data.get("gain", 15.0))
                radiod_host = data.get("radiod_host", "airspy-status.local")
                
                if controller.radiod_host != radiod_host:
                    await controller.close()
                    controller.radiod_host = radiod_host
                    await controller.connect()
                    # await controller.start_listener() # Wait, start_listener doesn't exist? Check radio_controller.
                
                controller.set_squelch(squelch_db)
                controller.set_gain(gain_db)
                lat, lon = get_coordinates_from_input(loc)
                if lat is None or lon is None:
                    await websocket.send_json({"type": "error", "message": "Invalid Grid or Lat,Lon"})
                    continue
                
                # Auto-tune to center of NWS band (approx 162.475 MHz)
                controller.tune_band(162475000)

                # Fetch and filter NWS stations
                all_stations = load_nws_data()
                filtered = get_stations_in_range(all_stations, lat, lon, radius_km=radius_km)
                
                await websocket.send_json({
                    "type": "results",
                    "repeaters": filtered, # Keep key 'repeaters' for frontend compatibility or rename
                    "lat": lat,
                    "lon": lon
                })
                
                # Start Monitoring
                asyncio.create_task(asyncio.to_thread(controller.monitor_repeaters, filtered))
                
    except WebSocketDisconnect:
        if websocket in active_websockets:
            active_websockets.remove(websocket)
    except Exception as e:
        logger.error(f"WS error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)

@app.websocket("/ws/audio/{freq_hz}")
async def websocket_audio(websocket: WebSocket, freq_hz: float):
    await websocket.accept()
    await streamer.add_listener(freq_hz, websocket, controller)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await streamer.remove_listener(freq_hz, websocket)

if __name__ == "__main__":
    import uvicorn
    # Paths for SSL (re-use existing certs for firebat)
    cert_dir = "/home/mjh/git/repeater-monitor/certs"
    uvicorn.run(
        "backend.app:app", 
        host="0.0.0.0", 
        port=8001, # Default to 8001 for NWS Monitor
        reload=True,
        ssl_keyfile=f"{cert_dir}/key.pem",
        ssl_certfile=f"{cert_dir}/cert.pem"
    )
