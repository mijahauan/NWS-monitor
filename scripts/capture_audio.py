#!/usr/bin/env python3
"""
capture_audio.py — Capture a few seconds of NFM audio and save as WAV.

Creates a channel, receives float32 samples via ManagedStream, and writes
them to a WAV file for offline verification of demodulation quality.

Usage:
    venv/bin/python scripts/capture_audio.py
    venv/bin/python scripts/capture_audio.py --host airspy-status.local --freq 162.475 --duration 10 --out /tmp/nws.wav
"""

import argparse
import sys
import time
import threading
import wave
import struct
import numpy as np

from ka9q import RadiodControl, ManagedStream
from ka9q.types import Encoding

DEFAULT_HOST     = "airspy-status.local"
DEFAULT_FREQ_MHZ = 162.475
SAMPLE_RATE      = 12000
GAIN_DB          = 15.0
DEFAULT_DURATION = 10.0


def run(host: str, freq_hz: float, duration: float, out_path: str):
    print(f"Capturing {duration}s of NFM audio from {freq_hz/1e6:.3f} MHz on {host}")
    print(f"Output: {out_path}")

    chunks = []
    done = threading.Event()

    def on_samples(samples: np.ndarray, quality):
        chunks.append(samples.astype(np.float32).copy())
        if sum(len(c) for c in chunks) >= SAMPLE_RATE * duration:
            done.set()

    def on_dropped(reason):
        print(f"  Stream dropped: {reason}")

    def on_restored(channel):
        print(f"  Stream restored: SSRC {channel.ssrc:08x}")
        try:
            control.set_output_encoding(channel.ssrc, Encoding.F32LE)
        except Exception as e:
            print(f"  Warning: could not re-apply F32LE after restore: {e}")

    control = RadiodControl(host)
    stream = ManagedStream(
        control=control,
        frequency_hz=freq_hz,
        preset="nfm",
        sample_rate=SAMPLE_RATE,
        gain=0.0,
        on_samples=on_samples,
        on_stream_dropped=on_dropped,
        on_stream_restored=on_restored,
        samples_per_packet=240,
        deliver_interval_packets=1,
    )

    try:
        print("Starting stream...")
        stream.start()

        # Force F32LE and disable squelch (ManagedStream has no encoding param;
        # existing channels may have squelch enabled from a previous session)
        try:
            control.set_gain(stream.channel.ssrc, GAIN_DB)
            control.set_output_encoding(stream.channel.ssrc, Encoding.F32LE)
            control.set_squelch(stream.channel.ssrc, snr_squelch=False)
            print(f"  SSRC {stream.channel.ssrc:08x}  gain={GAIN_DB}dB  F32LE  squelch=open")
        except Exception as e:
            print(f"  Warning: post-start config failed: {e}")

        deadline = time.monotonic() + duration + 3.0
        while not done.is_set() and time.monotonic() < deadline:
            time.sleep(0.1)

        stream.stop()
    finally:
        control.remove_channel(stream.channel.ssrc)
        control.close()

    if not chunks:
        print("ERROR: no samples received")
        return False

    audio = np.concatenate(chunks)
    total_sec = len(audio) / SAMPLE_RATE
    rms = float(np.sqrt(np.mean(audio ** 2)))
    peak = float(np.max(np.abs(audio)))
    print(f"\nCaptured {len(audio)} samples ({total_sec:.1f}s)  RMS={rms:.4f}  peak={peak:.4f}")

    # Clamp and convert to int16 for WAV
    audio_clipped = np.clip(audio, -1.0, 1.0)
    int16_data = (audio_clipped * 32767).astype(np.int16)

    with wave.open(out_path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(int16_data.tobytes())

    print(f"Saved {out_path}  ({SAMPLE_RATE} Hz mono int16)")
    if rms < 0.001:
        print("WARNING: RMS very low — channel may be silent or gain too low")
    elif rms > 0.5:
        print("WARNING: RMS high — consider reducing gain to avoid clipping")
    else:
        print("RMS looks reasonable for speech/broadcast audio")
    return True


def main():
    parser = argparse.ArgumentParser(description="Capture NFM audio to WAV for offline inspection")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--freq", type=float, default=DEFAULT_FREQ_MHZ,
                        help="Frequency in MHz")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION,
                        help="Capture duration in seconds")
    parser.add_argument("--out", default="/tmp/nws_capture.wav",
                        help="Output WAV path")
    args = parser.parse_args()

    ok = run(args.host, args.freq * 1e6, args.duration, args.out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
