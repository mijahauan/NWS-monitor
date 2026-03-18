import asyncio
import logging
from typing import Dict, Any, Callable, Optional
from ka9q.types import Encoding
from ka9q.control import RadiodControl

logger = logging.getLogger(__name__)

class RadioController:
    def __init__(self, radiod_host: str = "airspy-status.local"):
        self.radiod_host = radiod_host
        self.control = None
        self.active_channels = {} # SSRC -> {freq_hz, is_active}
        self.squelch_threshold = -20.0 # Force open for testing
        self.gain_db = 0.0 # Start with low gain to avoid saturation
        self.on_activity_change: Callable[[int, bool, float], None] = None
        
    async def connect(self):
        """Connects to radiod via its status multicast address."""
        try:
            self.control = RadiodControl(self.radiod_host)
            self.control.parent = self # Link back for state access
            # Set initial gain
            self.control.set_gain(0, self.gain_db)
            logger.info(f"Connected to radiod at {self.radiod_host}, set gain to {self.gain_db} dB")
        except Exception as e:
            logger.error(f"Failed to connect to radiod: {e}")
            raise

    def set_gain(self, gain_db: float):
        self.gain_db = gain_db
        if self.control:
            self.control.set_gain(0, self.gain_db)
            logger.info(f"Frontend gain set to {self.gain_db} dB")

    def set_squelch(self, threshold_db: float):
        self.squelch_threshold = threshold_db
        logger.info(f"Squelch threshold set to {self.squelch_threshold} dB")

    def tune_band(self, center_freq_hz: float):
        """Tunes the AirspyR2 frontend receiver Center Frequency"""
        if not self.control:
            return
            
        try:
            # Use the higher-level set_frequency for SSRC 0 (frontend)
            self.control.set_frequency(0, center_freq_hz)
            logger.info(f"Tuned frontend radio center frequency to {center_freq_hz / 1e6} MHz")
        except Exception as e:
            logger.error(f"Failed to tune band: {e}")

    def monitor_repeaters(self, repeaters: list):
        """
        Takes a list of repeaters. Reuses existing SSRCs or creates new ones.
        Shuts down unused SSRCs by setting frequency to 0.
        """
        if not self.control:
            return

        new_freqs = set()
        logger.info(f"monitor_repeaters call with {len(repeaters)} repeaters")
        for rep in repeaters:
            try:
                # Support multiple possible keys for frequency
                freq_hz = rep.get("frequency") or rep.get("freq")
                if not freq_hz and rep.get("Downlink"):
                    freq_hz = float(rep["Downlink"]) * 1e6
                
                if freq_hz:
                    new_freqs.add(float(freq_hz))
                else:
                    logger.warning(f"Repeater entry missing frequency: {rep}")
            except Exception as e:
                logger.error(f"Error parsing repeater frequency: {e}")

        logger.info(f"Frequencies to monitor: {[f/1e6 for f in new_freqs]} MHz")

        # 1. Park channels no longer in the list
        existing_ssrcs = list(self.active_channels.keys())
        for ssrc in existing_ssrcs:
            info = self.active_channels[ssrc]
            if info["freq_hz"] not in new_freqs:
                try:
                    # Set frequency to 0 to shut it down
                    self.control.set_frequency(ssrc, 0)
                    logger.info(f"Closed SSRC {ssrc:x} ({info['freq_hz']/1e6} MHz) by setting freq to 0")
                except Exception as e:
                    logger.warning(f"Failed to park SSRC {ssrc:x}: {e}")
                del self.active_channels[ssrc]

        # 2. Ensure channels for frequencies in the list
        for freq_hz in new_freqs:
            try:
                # Use ensure_channel to find or create the channel
                channel_info = self.control.ensure_channel(
                    frequency_hz=freq_hz,
                    preset="nfm",
                    sample_rate=12000,
                    encoding=Encoding.S16LE,
                    gain=self.gain_db,
                    timeout=5.0
                )
                
                ssrc = channel_info.ssrc
                self.active_channels[ssrc] = {
                    "freq_hz": freq_hz,
                    "is_active": False,
                    "info": channel_info
                }
                logger.info(f"Verified channel SSRC {ssrc:x} for {freq_hz/1e6} MHz at {channel_info.multicast_address}")
            except Exception as e:
                logger.error(f"Failed to ensure channel for {freq_hz}: {e}")

    async def close(self):
        if self.control:
            self.control.close()
