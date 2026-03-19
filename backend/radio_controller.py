import logging
import threading
from typing import Optional
from ka9q import RadiodControl
from ka9q.discovery import discover_channels
from ka9q.types import Encoding

logger = logging.getLogger(__name__)


class RadioController:
    def __init__(self, radiod_host: str = "airspy-status.local"):
        self.radiod_host = radiod_host
        self.control: Optional[RadiodControl] = None
        self.active_channels: dict = {}  # ssrc -> freq_hz
        self.squelch_threshold: float = 10.0
        self.gain_db: float = 15.0
        self._monitor_lock = threading.Lock()

    async def connect(self):
        """Connect to radiod via its status multicast address."""
        try:
            self.control = RadiodControl(self.radiod_host)
            logger.info(f"Connected to radiod at {self.radiod_host}")
        except Exception as e:
            logger.error(f"Failed to connect to radiod: {e}")
            raise

    def set_gain(self, gain_db: float):
        self.gain_db = gain_db
        logger.info(f"Gain set to {self.gain_db} dB (applied to new channels)")

    def set_squelch(self, threshold_db: float):
        self.squelch_threshold = threshold_db
        logger.info(f"Squelch threshold set to {self.squelch_threshold} dB")

    def tune_band(self, center_freq_hz: float):
        """No-op: NWS channels self-tune via ensure_channel."""
        pass

    def monitor_repeaters(self, repeaters: list):
        """
        Ensure radiod channels exist for each repeater frequency.
        Removes channels no longer in the list (freq=0 erase).
        """
        if not self._monitor_lock.acquire(blocking=False):
            logger.info("monitor_repeaters: already running, skipping concurrent call")
            return
        try:
            self._monitor_repeaters_locked(repeaters)
        finally:
            self._monitor_lock.release()

    def _monitor_repeaters_locked(self, repeaters: list):
        if not self.control:
            logger.warning("monitor_repeaters: no radiod connection")
            return

        new_freqs: set = set()
        for rep in repeaters:
            try:
                freq_hz = rep.get("frequency") or rep.get("freq")
                if not freq_hz and rep.get("Downlink"):
                    freq_hz = float(rep["Downlink"]) * 1e6
                if freq_hz:
                    new_freqs.add(float(freq_hz))
                else:
                    logger.warning(f"Repeater entry missing frequency: {rep}")
            except Exception as e:
                logger.error(f"Error parsing repeater frequency: {e}")

        logger.info(f"Monitoring {len(new_freqs)} frequencies: "
                    f"{sorted(f/1e6 for f in new_freqs)} MHz")

        # Remove channels no longer needed (erase via freq=0)
        for ssrc, freq_hz in list(self.active_channels.items()):
            if freq_hz not in new_freqs:
                try:
                    self.control.remove_channel(ssrc)
                    logger.info(f"Removed channel SSRC {ssrc:08x} ({freq_hz/1e6:.3f} MHz)")
                except Exception as e:
                    logger.warning(f"Failed to remove SSRC {ssrc:08x}: {e}")
                del self.active_channels[ssrc]

        # Scrub orphaned channels at our target frequencies (left by previous
        # server runs that used a different gain/encoding in the SSRC hash).
        # Use 100 Hz tolerance — radiod may echo back a slightly imprecise float.
        FREQ_TOL = 100.0
        try:
            existing = discover_channels(self.radiod_host, listen_duration=1.0)
            for ssrc, ch in list(existing.items()):
                freq_match = any(abs(ch.frequency - f) < FREQ_TOL for f in new_freqs)
                if freq_match and ssrc not in self.active_channels:
                    try:
                        self.control.remove_channel(ssrc)
                        logger.info(f"Scrubbed orphan SSRC {ssrc:08x} ({ch.frequency/1e6:.3f} MHz)")
                    except Exception as e:
                        logger.warning(f"Failed to scrub SSRC {ssrc:08x}: {e}")
        except Exception as e:
            logger.warning(f"Failed to discover existing channels for scrub: {e}")

        # Ensure a channel exists for every requested frequency
        for freq_hz in new_freqs:
            try:
                # gain=0.0 keeps the SSRC hash stable — changing the gain
                # slider would otherwise produce a different SSRC and a
                # duplicate channel.  Apply actual gain separately below.
                channel = self.control.ensure_channel(
                    frequency_hz=freq_hz,
                    preset="nfm",
                    sample_rate=12000,
                    gain=0.0,
                    timeout=5.0,
                )
                ssrc = channel.ssrc
                self.active_channels[ssrc] = freq_hz

                try:
                    self.control.set_gain(ssrc, self.gain_db)
                except Exception as e:
                    logger.warning(f"Failed to set gain on SSRC {ssrc:08x}: {e}")

                # Set F32LE separately (not in ensure_channel — encoding is also
                # part of the SSRC hash and ManagedStream cannot pass it)
                try:
                    self.control.set_output_encoding(ssrc, Encoding.F32LE)
                except Exception as e:
                    logger.warning(f"Failed to set F32LE on SSRC {ssrc:08x}: {e}")

                try:
                    self.control.set_squelch(ssrc, snr_squelch=False)
                except Exception as sq_err:
                    logger.warning(f"Failed to disable squelch on SSRC {ssrc:08x}: {sq_err}")

                logger.info(
                    f"Channel SSRC {ssrc:08x} ready: {freq_hz/1e6:.3f} MHz → "
                    f"{channel.multicast_address}:{channel.port}"
                )
            except Exception as e:
                logger.error(f"Failed to ensure channel for {freq_hz/1e6:.3f} MHz: {e}")

    async def close(self):
        if self.control:
            for ssrc in list(self.active_channels.keys()):
                try:
                    self.control.remove_channel(ssrc)
                except Exception:
                    pass
            self.active_channels.clear()
            self.control.close()
            self.control = None
