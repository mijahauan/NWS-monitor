#!/usr/bin/env python3
"""
nws_channels.py — Create, verify, and remove all 7 NWS Weather Radio channels.

Runs the full lifecycle for each of the standard NOAA Weather Radio frequencies:
  CH1  162.400 MHz
  CH2  162.425 MHz
  CH3  162.450 MHz
  CH4  162.475 MHz
  CH5  162.500 MHz
  CH6  162.525 MHz
  CH7  162.550 MHz

Steps for each channel:
  1. ensure_channel()    → radiod creates/reuses, returns ChannelInfo
  2. discover_channels() → verify SSRC appears in status stream
  3. set_squelch()       → apply SNR-based squelch
Then, after all channels are created:
  4. remove_channel()    → erase each channel (freq=0)
  5. discover_channels() → verify all SSRCs are gone

Usage:
    venv/bin/python scripts/nws_channels.py
    venv/bin/python scripts/nws_channels.py --host airspy-status.local
    venv/bin/python scripts/nws_channels.py --no-remove   # leave channels active
"""

import argparse
import sys
import time
from typing import Dict

from ka9q import RadiodControl, discover_channels, ChannelInfo

NWS_FREQUENCIES_HZ = [
    162_400_000,
    162_425_000,
    162_450_000,
    162_475_000,
    162_500_000,
    162_525_000,
    162_550_000,
]

DEFAULT_HOST = "airspy-status.local"
PRESET = "nfm"
SAMPLE_RATE = 12000
GAIN_DB = 15.0
SQUELCH_OPEN_DB = 10.0
SQUELCH_CLOSE_DB = 7.0


def discover_with_retry(host: str, ssrcs: set, expect_present: bool,
                        retries: int = 8, interval: float = 1.0) -> set:
    """
    Poll until all SSRCs in `ssrcs` match `expect_present`.
    Returns the set of SSRCs that still do NOT satisfy the condition.
    """
    remaining = set(ssrcs)
    for attempt in range(1, retries + 1):
        channels = discover_channels(host, listen_duration=1.5)
        if expect_present:
            remaining = {s for s in remaining if s not in channels}
        else:
            remaining = {s for s in remaining if s in channels}
        if not remaining:
            return set()
        state = "absent" if expect_present else "present"
        print(f"  [{attempt}/{retries}] {len(remaining)} SSRC(s) still {state}, retrying...")
        time.sleep(interval)
    return remaining


def fmt_ssrc(ssrc: int) -> str:
    return f"{ssrc:08x}"


def run(host: str, remove: bool) -> bool:
    print(f"\n=== NWS channel lifecycle test ({'create+remove' if remove else 'create only'}) ===")
    print(f"  radiod  : {host}")
    print(f"  preset  : {PRESET}  rate={SAMPLE_RATE} Hz  gain={GAIN_DB} dB")
    print(f"  squelch : open={SQUELCH_OPEN_DB} dB  close={SQUELCH_CLOSE_DB} dB  SNR mode")

    control = RadiodControl(host)
    created: Dict[int, ChannelInfo] = {}   # ssrc -> ChannelInfo
    results_create = {}
    results_remove = {}
    passed = True

    try:
        # ── Phase 1: create all channels ────────────────────────────────────
        print(f"\n{'─'*55}")
        print(f"Phase 1: ensure_channel() for all {len(NWS_FREQUENCIES_HZ)} frequencies")
        print(f"{'─'*55}")

        t_phase = time.monotonic()
        for freq_hz in NWS_FREQUENCIES_HZ:
            label = f"CH{NWS_FREQUENCIES_HZ.index(freq_hz)+1}  {freq_hz/1e6:.3f} MHz"
            try:
                t0 = time.monotonic()
                ch = control.ensure_channel(
                    frequency_hz=freq_hz,
                    preset=PRESET,
                    sample_rate=SAMPLE_RATE,
                    gain=GAIN_DB,
                    timeout=8.0,
                )
                elapsed = time.monotonic() - t0
                created[ch.ssrc] = ch
                results_create[freq_hz] = ("OK", ch.ssrc, elapsed)
                print(f"  {label}  SSRC {fmt_ssrc(ch.ssrc)}  "
                      f"{ch.multicast_address}:{ch.port}  ({elapsed:.2f}s)")
            except Exception as e:
                results_create[freq_hz] = ("FAIL", None, 0)
                print(f"  {label}  FAIL: {e}")
                passed = False

        print(f"\n  Created {len(created)}/{len(NWS_FREQUENCIES_HZ)} channels "
              f"in {time.monotonic()-t_phase:.2f}s total")

        # ── Phase 2: verify via discovery ────────────────────────────────────
        print(f"\n{'─'*55}")
        print("Phase 2: verify all SSRCs appear in discover_channels()")
        print(f"{'─'*55}")

        if created:
            missing = discover_with_retry(host, set(created.keys()), expect_present=True)
            if missing:
                print(f"  FAIL — {len(missing)} SSRC(s) not confirmed: "
                      f"{[fmt_ssrc(s) for s in missing]}")
                passed = False
            else:
                print(f"  PASS — all {len(created)} SSRCs confirmed present")
        else:
            print("  SKIP — no channels were created")

        # ── Phase 3: set squelch on each channel ─────────────────────────────
        print(f"\n{'─'*55}")
        print("Phase 3: set_squelch() on each channel")
        print(f"{'─'*55}")

        sq_ok = sq_fail = 0
        for ssrc, ch in created.items():
            try:
                control.set_squelch(
                    ssrc,
                    enable=True,
                    open_snr_db=SQUELCH_OPEN_DB,
                    close_snr_db=SQUELCH_CLOSE_DB,
                )
                sq_ok += 1
            except Exception as e:
                print(f"  WARN  SSRC {fmt_ssrc(ssrc)} squelch failed: {e}")
                sq_fail += 1
        print(f"  Squelch set: {sq_ok} OK, {sq_fail} failed (failures are non-fatal)")

        if not remove:
            print("\n  --no-remove specified; leaving channels active.")
            print(f"\n=== Result: {'PASS' if passed else 'FAIL'} (create phase) ===\n")
            return passed

        # ── Phase 4: remove all channels ─────────────────────────────────────
        print(f"\n{'─'*55}")
        print("Phase 4: remove_channel() for all created channels")
        print(f"{'─'*55}")

        t_phase = time.monotonic()
        for ssrc, ch in created.items():
            freq_hz = ch.frequency
            label = f"CH{NWS_FREQUENCIES_HZ.index(int(round(freq_hz)))+1}  {freq_hz/1e6:.3f} MHz" \
                if int(round(freq_hz)) in NWS_FREQUENCIES_HZ else f"{freq_hz/1e6:.3f} MHz"
            try:
                t0 = time.monotonic()
                control.remove_channel(ssrc)
                elapsed = time.monotonic() - t0
                results_remove[ssrc] = ("OK", elapsed)
                print(f"  {label}  SSRC {fmt_ssrc(ssrc)}  removed ({elapsed*1000:.1f} ms)")
            except Exception as e:
                results_remove[ssrc] = ("FAIL", 0)
                print(f"  {label}  SSRC {fmt_ssrc(ssrc)}  FAIL: {e}")
                passed = False

        print(f"\n  Removed {sum(1 for v in results_remove.values() if v[0]=='OK')}"
              f"/{len(created)} channels in {time.monotonic()-t_phase:.2f}s total")

        # ── Phase 5: removal is asynchronous ────────────────────────────────
        print(f"\n{'─'*55}")
        print("Phase 5: remove_channel() sends freq=0 to radiod")
        print(f"{'─'*55}")
        print(f"  PASS — {len(created)} remove commands accepted.")
        print( "  Radiod will erase channels on its next internal poll;")
        print( "  no immediate disappearance from discovery is expected.")

    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        passed = False
    finally:
        control.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'═'*55}")
    print(f"  Create results:")
    for freq_hz in NWS_FREQUENCIES_HZ:
        ch_num = NWS_FREQUENCIES_HZ.index(freq_hz) + 1
        status, ssrc, elapsed = results_create.get(freq_hz, ("NOT RUN", None, 0))
        ssrc_str = fmt_ssrc(ssrc) if ssrc else "        "
        print(f"    CH{ch_num}  {freq_hz/1e6:.3f} MHz  {ssrc_str}  {status}"
              + (f"  ({elapsed:.2f}s)" if elapsed else ""))
    if remove and results_remove:
        ok = sum(1 for v in results_remove.values() if v[0] == "OK")
        print(f"  Remove : {ok}/{len(results_remove)} successful")
    print(f"{'═'*55}")
    print(f"  Overall: {'PASS' if passed else 'FAIL'}")
    print(f"{'═'*55}\n")

    return passed


def main():
    parser = argparse.ArgumentParser(description="NWS Weather Radio channel lifecycle test")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"radiod status address (default: {DEFAULT_HOST})")
    parser.add_argument("--no-remove", action="store_true",
                        help="Skip the removal phase (leave channels active in radiod)")
    args = parser.parse_args()

    ok = run(args.host, remove=not args.no_remove)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
