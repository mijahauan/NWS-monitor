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

The application utilizes a robust audio pipeline aligned to 12kHz, ensuring high-quality, gap-free Opus streaming. It discovers transmitters based on the user's location (Grid Square or Lat/Lon) and allows one-click listening to the live broadcast.

## Architecture

- **Backend**: FastAPI + ka9q-python + Opus (12kHz alignment)
- **Frontend**: Leaflet Map + Web Audio API
- **Radio**: Connects to any `radiod` instance via mDNS status channel.

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
