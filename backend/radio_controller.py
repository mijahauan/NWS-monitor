import logging
from typing import Optional
from ka9q import RadiodControl, generate_multicast_ip
from ka9q.types import Encoding

logger = logging.getLogger(__name__)


class RadioController:
    def __init__(self, radiod_host: str = "airspy-status.local"):
        self.radiod_host = radiod_host
        self.control: Optional[RadiodControl] = None
        self.active_channels: dict = {}  # ssrc -> freq_hz
        self.squelch_threshold: float = -20.0  # matches HTML slider min (always-open default)
        self.gain_db: float = 15.0
        # Stable, app-specific multicast destination — scopes all channels to
        # this app and makes the SSRC deterministic across server restarts.
        self.destination: str = generate_multicast_ip("nws-monitor")

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
        if not self.control:
            return
        for ssrc in list(self.active_channels):
            try:
                self.control.set_squelch(ssrc,
                    open_threshold=threshold_db,
                    close_threshold=threshold_db - 2.0,
                    snr_squelch=True)
            except Exception as e:
                logger.warning(f"Failed to update squelch on SSRC {ssrc:08x}: {e}")

    def tune_band(self, center_freq_hz: float):
        """No-op: NWS channels self-tune via ensure_channel."""
        pass

    def monitor_repeaters(self, repeaters: list):
        """
        Ensure radiod channels exist for each repeater frequency.
        Removes channels no longer in the list.

        Channel identity = (freq, preset, sample_rate, encoding, destination)
        with gain=0.0 (canonical).  All four parameters are included in the
        SSRC hash, so the SSRC is deterministic across server restarts — no
        orphan scrubbing is needed.
        """
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
                    f"{sorted(f/1e6 for f in new_freqs)} MHz  dest={self.destination}")

        # Remove channels no longer needed
        for ssrc, freq_hz in list(self.active_channels.items()):
            if freq_hz not in new_freqs:
                try:
                    self.control.remove_channel(ssrc)
                    logger.info(f"Removed channel SSRC {ssrc:08x} ({freq_hz/1e6:.3f} MHz)")
                except Exception as e:
                    logger.warning(f"Failed to remove SSRC {ssrc:08x}: {e}")
                del self.active_channels[ssrc]

        # Ensure a channel exists for every requested frequency.
        # destination + encoding + gain=0.0 → stable SSRC; ensure_channel
        # finds and reuses the existing channel if it was created in a
        # previous run with the same parameters.
        for freq_hz in new_freqs:
            try:
                channel = self.control.ensure_channel(
                    frequency_hz=freq_hz,
                    preset="nfm",
                    sample_rate=12000,
                    gain=0.0,
                    destination=self.destination,
                    encoding=Encoding.F32LE,
                    timeout=5.0,
                )
                ssrc = channel.ssrc
                self.active_channels[ssrc] = freq_hz

                try:
                    self.control.set_gain(ssrc, self.gain_db)
                except Exception as e:
                    logger.warning(f"Failed to set gain on SSRC {ssrc:08x}: {e}")

                try:
                    self.control.set_squelch(ssrc,
                        open_threshold=self.squelch_threshold,
                        close_threshold=self.squelch_threshold - 2.0,
                        snr_squelch=True)
                except Exception as sq_err:
                    logger.warning(f"Failed to set squelch on SSRC {ssrc:08x}: {sq_err}")

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
