import asyncio
import logging
import numpy as np
from typing import Dict, List, Optional
from fastapi import WebSocket
from ka9q import ManagedStream, StreamQuality
from ka9q.types import Encoding

logger = logging.getLogger(__name__)


class AudioStreamer:
    """
    Manages one ManagedStream per frequency and fans audio out to WebSocket listeners.

    ManagedStream (ka9q-python) handles:
      - ensure_channel() on start and after every radiod restart
      - Self-healing: detects packet dropout and re-establishes the channel
      - on_stream_dropped / on_stream_restored callbacks

    NFM preset → radiod demodulates and outputs float32 PCM at the requested
    sample rate.  RadiodStream._parse_samples reads it as np.float32, so no
    custom subclass is needed.  The frontend (app.js) consumes raw Float32Array
    bytes directly via Web Audio API at 12 kHz.
    """

    def __init__(self):
        self.active_streams: Dict[float, ManagedStream] = {}
        self.listeners: Dict[float, List[WebSocket]] = {}

    async def add_listener(self, frequency_hz: float, websocket: WebSocket, controller):
        """Register a WebSocket listener; start a ManagedStream if none exists yet."""
        freq_key = float(frequency_hz)
        self.listeners.setdefault(freq_key, []).append(websocket)
        logger.info(f"Listener added for {freq_key/1e6:.3f} MHz "
                    f"(total: {len(self.listeners[freq_key])})")

        if freq_key in self.active_streams:
            return  # Stream already running; listener will receive next broadcast

        if not controller or not controller.control:
            logger.error(f"Cannot stream {freq_key/1e6:.3f} MHz: no radiod connection")
            try:
                await websocket.close(code=1011, reason="Radio control unavailable")
            except Exception:
                pass
            return

        loop = asyncio.get_running_loop()

        def on_samples(samples: np.ndarray, quality: StreamQuality):
            if loop.is_closed():
                return
            payload = samples.astype(np.float32).tobytes()
            asyncio.run_coroutine_threadsafe(
                self.broadcast(freq_key, payload), loop
            )

        def on_dropped(reason: str):
            logger.warning(f"Stream dropped for {freq_key/1e6:.3f} MHz: {reason}")

        def on_restored(channel):
            logger.info(
                f"Stream restored for {freq_key/1e6:.3f} MHz: "
                f"SSRC {channel.ssrc:08x}"
            )
            # Re-apply post-creation settings (ManagedStream recreates without them)
            gain = getattr(controller, 'gain_db', 15.0)
            sq = getattr(controller, 'squelch_threshold', -20.0)
            try:
                controller.control.set_gain(channel.ssrc, gain)
                controller.control.set_output_encoding(channel.ssrc, Encoding.F32LE)
                controller.control.set_squelch(channel.ssrc,
                    open_threshold=sq, close_threshold=sq - 2.0, snr_squelch=True)
            except Exception as e:
                logger.warning(f"Failed to re-apply settings after restore: {e}")

        # gain=0.0 keeps the SSRC hash identical to monitor_repeaters so both
        # share the same radiod channel.  Actual gain is applied after start.
        stream = ManagedStream(
            control=controller.control,
            frequency_hz=freq_key,
            preset="nfm",
            sample_rate=12000,
            gain=0.0,
            on_samples=on_samples,
            on_stream_dropped=on_dropped,
            on_stream_restored=on_restored,
            drop_timeout_sec=5.0,
            samples_per_packet=240,        # 20 ms at 12 kHz
            deliver_interval_packets=1,    # deliver every packet for low latency
        )

        try:
            await asyncio.to_thread(stream.start)
            gain = getattr(controller, 'gain_db', 15.0)
            try:
                controller.control.set_gain(stream.channel.ssrc, gain)
                controller.control.set_output_encoding(
                    stream.channel.ssrc, Encoding.F32LE
                )
                sq = getattr(controller, 'squelch_threshold', -20.0)
                controller.control.set_squelch(stream.channel.ssrc,
                    open_threshold=sq, close_threshold=sq - 2.0, snr_squelch=True)
            except Exception as e:
                logger.warning(f"Failed to configure stream for {freq_key/1e6:.3f} MHz: {e}")
            self.active_streams[freq_key] = stream
            logger.info(f"ManagedStream started for {freq_key/1e6:.3f} MHz")
        except Exception as e:
            logger.error(f"Failed to start stream for {freq_key/1e6:.3f} MHz: {e}")
            try:
                await websocket.close(code=1011, reason=f"Stream start failed: {e}")
            except Exception:
                pass

    async def remove_listener(self, freq_hz: float, websocket: WebSocket):
        """Deregister a listener; stop the stream when the last listener leaves."""
        listeners = self.listeners.get(freq_hz, [])
        if websocket in listeners:
            listeners.remove(websocket)

        if not listeners:
            self.listeners.pop(freq_hz, None)
            stream = self.active_streams.pop(freq_hz, None)
            if stream:
                await asyncio.to_thread(stream.stop)
                logger.info(f"ManagedStream stopped for {freq_hz/1e6:.3f} MHz "
                            f"(no more listeners)")

    async def broadcast(self, freq_hz: float, payload: bytes):
        """Send audio payload to every registered listener for this frequency."""
        for ws in list(self.listeners.get(freq_hz, [])):
            try:
                await ws.send_bytes(payload)
            except Exception as e:
                logger.debug(f"Broadcast error for {freq_hz/1e6:.3f} MHz: {e}")
                await self.remove_listener(freq_hz, ws)


streamer = AudioStreamer()
