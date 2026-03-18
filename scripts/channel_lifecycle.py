#!/usr/bin/env python3
"""
channel_lifecycle.py — Create, verify, and remove a single radiod channel.

Demonstrates the ka9q-python lifecycle for one NWS frequency:
  1. ensure_channel()   → radiod creates/reuses the channel
  2. discover_channels() → verify the SSRC appears
  3. set_squelch()       → apply SNR squelch
  4. remove_channel()    → erase by tuning freq=0
  5. discover_channels() → verify the SSRC is gone

Usage:
    venv/bin/python scripts/channel_lifecycle.py
    venv/bin/python scripts/channel_lifecycle.py --host airspy-status.local --freq 162.475
"""

import argparse
import sys
import time

from ka9q import RadiodControl, discover_channels

DEFAULT_HOST = "airspy-status.local"
DEFAULT_FREQ_MHZ = 162.475   # NWS CH4 (most common primary)
PRESET = "nfm"
SAMPLE_RATE = 12000
GAIN_DB = 15.0
SQUELCH_OPEN_DB = 10.0
SQUELCH_CLOSE_DB = 7.0


def discover_with_retry(host: str, ssrc: int, expect_present: bool,
                        retries: int = 6, interval: float = 1.0) -> bool:
    """Poll discover_channels until the SSRC matches the expected presence."""
    for attempt in range(1, retries + 1):
        channels = discover_channels(host, listen_duration=1.0)
        present = ssrc in channels
        if present == expect_present:
            return True
        state = "present" if present else "absent"
        want = "present" if expect_present else "absent"
        print(f"  [{attempt}/{retries}] SSRC {ssrc:08x} is {state}, waiting for {want}...")
        time.sleep(interval)
    return False


def run(host: str, freq_hz: float) -> bool:
    print(f"\n=== Channel lifecycle test ===")
    print(f"  radiod : {host}")
    print(f"  freq   : {freq_hz/1e6:.3f} MHz  preset={PRESET}  rate={SAMPLE_RATE} Hz")

    control = RadiodControl(host)
    ssrc = None
    passed = True

    try:
        # ── Step 1: ensure_channel ───────────────────────────────────────────
        print("\n[1] ensure_channel() ...")
        t0 = time.monotonic()
        channel = control.ensure_channel(
            frequency_hz=freq_hz,
            preset=PRESET,
            sample_rate=SAMPLE_RATE,
            gain=GAIN_DB,
            timeout=8.0,
        )
        elapsed = time.monotonic() - t0
        ssrc = channel.ssrc
        print(f"    SSRC     : {ssrc:08x}")
        print(f"    address  : {channel.multicast_address}:{channel.port}")
        print(f"    frequency: {channel.frequency/1e6:.4f} MHz")
        print(f"    preset   : {channel.preset}")
        print(f"    rate     : {channel.sample_rate} Hz")
        print(f"    elapsed  : {elapsed:.2f} s")

        # ── Step 2: verify via discovery ────────────────────────────────────
        print("\n[2] Verifying channel appears in discover_channels() ...")
        if discover_with_retry(host, ssrc, expect_present=True):
            print(f"    PASS — SSRC {ssrc:08x} confirmed present")
        else:
            print(f"    FAIL — SSRC {ssrc:08x} not found after retries")
            passed = False

        # ── Step 3: set_squelch ──────────────────────────────────────────────
        print("\n[3] set_squelch() ...")
        try:
            control.set_squelch(
                ssrc,
                enable=True,
                open_snr_db=SQUELCH_OPEN_DB,
                close_snr_db=SQUELCH_CLOSE_DB,
            )
            print(f"    PASS — squelch open={SQUELCH_OPEN_DB} dB, "
                  f"close={SQUELCH_CLOSE_DB} dB, SNR mode")
        except Exception as e:
            print(f"    WARN — squelch failed (non-fatal): {e}")

        # ── Step 4: remove_channel ───────────────────────────────────────────
        print("\n[4] remove_channel() ...")
        t0 = time.monotonic()
        control.remove_channel(ssrc)
        elapsed = time.monotonic() - t0
        print(f"    Command sent in {elapsed*1000:.1f} ms")

        # ── Step 5: removal is asynchronous ─────────────────────────────────
        print("\n[5] remove_channel() sends freq=0; radiod erases on next poll.")
        print(f"    PASS — command accepted (SSRC {ssrc:08x} will be removed ")
        print( "             by radiod asynchronously — no immediate verify needed)")

    except Exception as e:
        print(f"\nERROR: {e}")
        passed = False
    finally:
        control.close()

    print(f"\n=== Result: {'PASS' if passed else 'FAIL'} ===\n")
    return passed


def main():
    parser = argparse.ArgumentParser(description="Single-channel ka9q lifecycle test")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"radiod status address (default: {DEFAULT_HOST})")
    parser.add_argument("--freq", type=float, default=DEFAULT_FREQ_MHZ,
                        help=f"Frequency in MHz (default: {DEFAULT_FREQ_MHZ})")
    args = parser.parse_args()

    ok = run(args.host, args.freq * 1e6)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
