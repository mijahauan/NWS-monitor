# NWS Monitor

A dedicated NOAA Weather Radio (NWR) monitor built on the [repeater-monitor](https://github.com/mijahauan/repeater-monitor) architecture. 

Displays NWS transmitter locations on a live map, monitors the 7 standard NWR channels for activity, and streams audio to the browser in real time.

## Frequencies Monitored

- 162.400 MHz (CH 1)
- 162.425 MHz (CH 2)
- 162.450 MHz (CH 3)
- 162.475 MHz (CH 4)
- 162.500 MHz (CH 5)
- 162.525 MHz (CH 6)
- 162.550 MHz (CH 7)

## How It Works

The application leverages the high-level `ensure_channel` API from `ka9q-python` for deterministic SSRC management and efficient multicast resource sharing. It automatically discovers NWS transmitters based on your location and provides real-time S16LE-based audio streaming (normalized to float32) for clear reception.

## Architecture

- **Backend**: FastAPI + ka9q-python (high-level API)
- **Audio Pipeline**: S16LE decoding with 12kHz alignment + Web Audio playback
- **Radio**: Connects to `radiod` via mDNS; handles gain and squelch dynamically for close-range stability.
- **Frontend**: Leaflet Map + Web Audio API

## Setup & Usage

```bash
# Start the monitor on port 8001
./nws-monitor.sh start

# Stop
./nws-monitor.sh stop
```

Access the UI at `https://<hostname>:8001`.

## Credits

Based on the `repeater-monitor` project.
