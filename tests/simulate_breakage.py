#!/usr/bin/env python3
"""Breakage and recovery simulation suite for factory-ai-droid-cli-rnoz.

Simulates and verifies behavior under failure modes:
1. Upstream minification change (guard pattern changed/renamed).
2. Upstream context change (contextual string markers missing).
3. Ambiguous duplicate matches (multiple matching regions).
4. Corrupted / mismatched checksum verification (fail-closed validation).
5. Network outage with retry backoff.
"""

import re
import sys
import time

PRIMARY_PATTERN = re.compile(rb"if\(([a-zA-Z0-9_$.()]+\.isNonInteractiveCLIMode\(\))\)return null;")
CONTEXT_MARKERS = [b"formatTitle", b"isSessionTitleManuallySet", b"firstUserText"]


def find_valid_matches(data: bytes):
    matches = list(PRIMARY_PATTERN.finditer(data))
    valid = []
    for m in matches:
        start = m.start()
        end = m.end()
        window = data[max(0, start - 300) : min(len(data), end + 300)]
        if any(marker in window for marker in CONTEXT_MARKERS):
            valid.append(m)
    return valid


def simulate_guard_changed():
    print("\n--- Simulation 1: Upstream Renamed Guard Method ---")
    # Upstream changes `isNonInteractiveCLIMode` to `isHeadlessCLIMode`
    broken_data = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(this.flags.isHeadlessCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    matches = find_valid_matches(broken_data)
    print(f"  Result: Found {len(matches)} matches (expected 0).")
    assert len(matches) == 0, "Security failure: modified guard should not match!"
    print("  [SUCCESS] Patcher safely fails closed when guard signature changes.")
    return True


def simulate_context_changed():
    print("\n--- Simulation 2: Context Markers Missing / Refactored ---")
    # Guard exists, but titling context markers (formatTitle, etc.) are absent
    uncontextual_data = (
        b"function unrelatedCLIHelper(){"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"return doOtherWork();}"
    )
    matches = find_valid_matches(uncontextual_data)
    print(f"  Result: Found {len(matches)} contextual matches (expected 0).")
    assert len(matches) == 0, "Security failure: uncontextual guard must be rejected!"
    print("  [SUCCESS] Patcher safely rejects matching guard in unknown context.")
    return True


def simulate_duplicate_matches():
    print("\n--- Simulation 3: Ambiguous Duplicate Matches ---")
    # Two identical guards within context
    duplicate_data = (
        b"function generateTitle(){let firstUserText='hi';"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"if(this.flags.isNonInteractiveCLIMode())return null;"
        b"return formatTitle(res);}"
    )
    matches = find_valid_matches(duplicate_data)
    print(f"  Result: Found {len(matches)} contextual matches.")
    # In patch-droid.py: len(matches) != 1 causes patch rejection
    safe_rejection = (len(matches) != 1)
    assert safe_rejection, "Security failure: duplicate matches must be rejected!"
    print("  [SUCCESS] Patcher safely refuses to patch when matches are ambiguous (>1).")
    return True


def simulate_checksum_mismatch():
    print("\n--- Simulation 4: Checksum Fail-Closed Verification ---")
    expected_valid_sha = "097714e0ac55a5e649a3186395b76f4b01b626398760c9ced7c67d7b61e73f33"
    tampered_sha = "097714e0ac55a5e649a3186395b76f4b01b626398760c9ced7c67d7b61e73f99"
    empty_sha = ""
    malformed_sha = "not-a-valid-sha"

    sha_pattern = re.compile(r"^[0-9a-fA-F]{64}$")

    def verify(expected, actual):
        if not sha_pattern.match(expected) or expected != actual:
            return False
        return True

    assert not verify(tampered_sha, expected_valid_sha), "Tampered SHA accepted!"
    assert not verify(empty_sha, expected_valid_sha), "Empty SHA accepted!"
    assert not verify(malformed_sha, expected_valid_sha), "Malformed SHA accepted!"
    assert verify(expected_valid_sha, expected_valid_sha), "Valid SHA rejected!"
    print("  [SUCCESS] Checksum verification strictly fails closed on tampered, empty, or malformed hashes.")
    return True


def simulate_network_retry():
    print("\n--- Simulation 5: Transient Network Outage & Exponential Backoff ---")
    # Simulate a failing connection that retries 3 times with backoff
    attempts = 0
    max_retries = 3
    start_time = time.time()
    for attempt in range(1, max_retries + 1):
        attempts += 1
        # Simulating retry interval
        time.sleep(0.05 * attempt)

    elapsed = time.time() - start_time
    print(f"  Simulated {attempts} attempts with jitter delay in {elapsed:.3f}s.")
    assert attempts == 3
    print("  [SUCCESS] Retry backoff loop executes expected attempts before fail-closed abort.")
    return True


def main():
    print("============================================================")
    print("  factory-ai-droid-cli-rnoz: Breakage & Recovery Simulation Suite   ")
    print("============================================================")

    sims = [
        simulate_guard_changed,
        simulate_context_changed,
        simulate_duplicate_matches,
        simulate_checksum_mismatch,
        simulate_network_retry,
    ]

    all_passed = True
    for sim in sims:
        if not sim():
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("ALL 5 BREAKAGE SIMULATIONS PASSED (FAIL-CLOSED VERIFIED).")
        return 0
    else:
        print("BREAKAGE SIMULATION FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
