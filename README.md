# NWS Monitor

Displays NOAA Weather Radio transmitter locations on a live map, monitors all
7 standard NWR channels for activity, and streams audio to the browser in
real time using [ka9q-radio](https://github.com/ka9q/ka9q-radio) and
[ka9q-python](https://github.com/ka9q/ka9q-python).

## Frequencies Monitored

| CH | Frequency  |
|----|-----------|
| 1  | 162.400 MHz |
| 2  | 162.425 MHz |
| 3  | 162.450 MHz |
| 4  | 162.475 MHz |
| 5  | 162.500 MHz |
| 6  | 162.525 MHz |
| 7  | 162.550 MHz |

## How It Works

1. On search, `RadioController.monitor_repeaters()` calls `ensure_channel()`
   for each NWS frequency in range.  `ensure_channel` uses deterministic SSRC
   allocation so multiple clients and the activity monitor share the same
   radiod channel without duplication.
2. A background task polls `discover_channels()` every 2 s, reads the SNR
   from each channel's status packet, and pushes activity updates to all
   connected WebSocket clients.
3. When a user clicks "Listen", `AudioStreamer` starts a `ManagedStream` for
   that frequency.  `ManagedStream` self-heals through radiod restarts via
   `ensure_channel` and the `on_stream_restored` callback re-applies squelch.
4. radiod demodulates NFM and outputs **float32 PCM at 12 kHz**.  Samples are
   forwarded as raw bytes to the browser, where the Web Audio API plays them
   directly — no client-side decoding needed.
5. On shutdown (or when the monitored station list changes), channels are
   erased by `remove_channel()`, which tunes radiod to frequency 0.  Actual
   deletion from radiod is asynchronous.

## Architecture

- **Backend**: FastAPI + `ka9q-python` (`ManagedStream`, `RadiodControl`,
  `discover_channels`)
- **Audio pipeline**: radiod NFM → float32 PCM at 12 kHz → WebSocket →
  Web Audio API (`Float32Array`)
- **Activity monitor**: SNR from `ChannelInfo.snr` via `discover_channels()`
- **Frontend**: Leaflet map + Web Audio API

## Setup

```bash
# Create venv and install dependencies (one-time)
python3 -m venv venv
venv/bin/pip install -e /path/to/ka9q-python   # local source, or omit for PyPI
venv/bin/pip install -e .

# Start on port 8001
./nws-monitor.sh start

# Stop / restart / status
./nws-monitor.sh stop
./nws-monitor.sh restart
./nws-monitor.sh status
```

Place TLS certificates in `certs/key.pem` and `certs/cert.pem` for HTTPS;
the server falls back to plain HTTP if they are absent.

## Test Scripts

```bash
# Single-channel create / verify / squelch / remove lifecycle
venv/bin/python scripts/channel_lifecycle.py --host airspy-status.local

# All 7 NWS channels
venv/bin/python scripts/nws_channels.py --host airspy-status.local
```
