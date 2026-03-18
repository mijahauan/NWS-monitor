import asyncio
import logging
import math
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from backend.nws_data import load_nws_data, get_coordinates_from_input, get_stations_in_range
from backend.radio_controller import RadioController
from backend.audio_streamer import streamer
from ka9q import discover_channels

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory for the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

controller = RadioController()
active_websockets = []

SNR_ACTIVE_THRESHOLD = 3.0   # dB above noise to consider channel "active"
ACTIVITY_POLL_INTERVAL = 2.0  # seconds between SNR polls


async def activity_monitor():
    """Poll radiod for SNR on each monitored channel; broadcast activity updates."""
    while True:
        await asyncio.sleep(ACTIVITY_POLL_INTERVAL)
        if not controller.active_channels or not active_websockets:
            continue
        try:
            channels = await asyncio.to_thread(
                discover_channels, controller.radiod_host, 1.0
            )
            for ssrc, freq_hz in list(controller.active_channels.items()):
                ch = channels.get(ssrc)
                if ch is None:
                    # SSRC not found; try matching by frequency (100 Hz tolerance)
                    ch = next(
                        (c for c in channels.values()
                         if abs(c.frequency - freq_hz) < 100.0),
                        None
                    )
                raw_snr = ch.snr if ch is not None else None
                # Treat -inf (no signal computed) as None so UI shows '--'
                if raw_snr is not None and (math.isinf(raw_snr) or math.isnan(raw_snr)):
                    raw_snr = None
                is_active = raw_snr is not None and raw_snr > SNR_ACTIVE_THRESHOLD
                msg = {
                    "type": "activity",
                    "freq": freq_hz,
                    "isActive": is_active,
                    "snr": round(raw_snr, 1) if raw_snr is not None else None,
                }
                for ws in list(active_websockets):
                    try:
                        await ws.send_json(msg)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"activity_monitor error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("NWS Monitor startup...")
    load_nws_data()
    await controller.connect()
    monitor_task = asyncio.create_task(activity_monitor())
    yield
    # Shutdown
    logger.info("NWS Monitor shutdown...")
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
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
    cert_dir = os.path.join(BASE_DIR, "certs")
    ssl_kwargs = {}
    if os.path.isfile(os.path.join(cert_dir, "key.pem")) and \
       os.path.isfile(os.path.join(cert_dir, "cert.pem")):
        ssl_kwargs = {
            "ssl_keyfile": os.path.join(cert_dir, "key.pem"),
            "ssl_certfile": os.path.join(cert_dir, "cert.pem"),
        }
        logger.info(f"SSL enabled from {cert_dir}")
    else:
        logger.info("No certs found — running without SSL (HTTP)")
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        **ssl_kwargs
    )
