#!/usr/bin/env python3
"""KeyForge Standalone E2E Test Runner.

Executes the 4-Tier Automated Test Suite (deterministic E2E verification)
using standard library unittest.

Usage:
    python run_tests.py
    python run_tests.py --tier 1
    python run_tests.py --tier 2
    python run_tests.py --tier 3
    python run_tests.py --tier 4
    python run_tests.py -v
    python run_tests.py -f  # fail fast
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure test environment defaults are active
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test_super_secret_key_32_characters_long_1234")
os.environ.setdefault("ED25519_PRIVATE_KEY_HEX", "a01fd194d15178191f62e570962a579e61bf728945f79655d9df145eada811ec")
os.environ.setdefault("ED25519_PUBLIC_KEY_HEX", "0043b567534bfa2d55059a05642f75573d420899146f334a9f7fc5fba797bd0b")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_test_stripe_secret_12345")
os.environ.setdefault("LEMONSQUEEZY_WEBHOOK_SECRET", "whsec_test_lemonsqueezy_secret_12345")
os.environ.setdefault("BILLING_MODE", "mock")
os.environ.setdefault("ENVIRONMENT", "testing")


def create_suite(tier: int | None = None) -> unittest.TestSuite:
    """Discover and construct the test suite."""
    loader = unittest.TestLoader()
    tests_dir = PROJECT_ROOT / "tests"

    if tier is not None:
        tier_dirs = {
            1: tests_dir / "tier1_features",
            2: tests_dir / "tier2_boundaries",
            3: tests_dir / "tier3_interactions",
            4: tests_dir / "tier4_workloads",
        }
        target_dir = tier_dirs.get(tier)
        if not target_dir or not target_dir.exists():
            print(f"Error: Invalid or missing tier directory: {target_dir}", file=sys.stderr)
            sys.exit(1)
        return loader.discover(start_dir=str(target_dir), pattern="test_*.py", top_level_dir=str(PROJECT_ROOT))

    return loader.discover(start_dir=str(tests_dir), pattern="test_*.py", top_level_dir=str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="KeyForge E2E Test Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Run specific test tier only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose test execution output")
    parser.add_argument("-f", "--failfast", action="store_true", help="Stop on first failure")
    args = parser.parse_args()

    print("=" * 72)
    print("  KeyForge: Cryptographic Licensing & Quota Gateway E2E Test Suite")
    print("=" * 72)
    tier_label = f"Tier {args.tier}" if args.tier else "Full Matrix (Tiers 1-4)"
    print(f"Target Scope:  {tier_label}")
    print(f"Environment:   Python {sys.version.split()[0]} | OS: {sys.platform}")
    print(f"Billing Mode:  {os.environ.get('BILLING_MODE')}")
    print("-" * 72)

    suite = create_suite(args.tier)
    total_tests = suite.countTestCases()
    print(f"Discovered {total_tests} test cases.")
    print("-" * 72)

    verbosity = 2 if args.verbose else 1
    runner = unittest.TextTestRunner(
        verbosity=verbosity,
        failfast=args.failfast,
        descriptions=True
    )

    start_time = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - start_time

    print("=" * 72)
    print(f"Ran {result.testsRun} tests in {elapsed:.3f}s")

    passed = result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped)
    print(f"Passed:   {passed}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors:   {len(result.errors)}")
    print(f"Skipped:  {len(result.skipped)}")

    if result.wasSuccessful():
        print("\n[SUCCESS] ALL TESTS PASSED (100% E2E VERIFIED)")
        print("=" * 72)
        return 0
    else:
        print("\n[FAILURE] TEST SUITE ENCOUNTERED FAILURES/ERRORS")
        print("=" * 72)
        return 1


if __name__ == "__main__":
    sys.exit(main())
