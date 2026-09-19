#!/usr/bin/env python3
"""
Master E2E Test Suite Runner
Runs all 16 E2E test suites covering direct Frontend <-> Backend interactions.
1.  Auth & Session Lifecycle
2.  Sets CRUD & Library Lifecycle
3.  Cards Editor, Auto-save & Undo
4.  Folders Management & Organization
5.  Sharing & Access Permissions
6.  User Settings, Locale & Themes
7.  SRS Spaced Repetition Reviews
8.  Study Mode: Test (MC, Written, TF, Match)
9.  Extended Study Modes (Spell, Match, Learn)
10. Import / Export (TSV, CSV, JSON)
11. Admin Panel, Users, Backup & Audit
12. Edge Cases, Reload & Error Boundaries
"""

import os
import sys
import time
import subprocess
from datetime import datetime

SUITES = [
    ("Auth & Sessions", "test_auth_e2e.py"),
    ("Sets CRUD & Library", "test_sets_crud_e2e.py"),
    ("Cards Editor & Undo", "test_cards_editor_e2e.py"),
    ("Folders Management", "test_folders_e2e.py"),
    ("Sharing & Links", "test_sharing_e2e.py"),
    ("Settings & Localization", "test_settings_e2e.py"),
    ("SRS Spaced Repetition", "test_srs_review_e2e.py"),
    ("Study Mode: Test", "test_study_test_e2e.py"),
    ("Extended Study: Spell/Match/Learn", "test_study_extended_e2e.py"),
    ("Import / Export", "test_import_export_e2e.py"),
    ("Admin Operations & Audit", "test_admin_e2e.py"),
    ("Edge Cases & Error Recovery", "test_edge_cases_e2e.py"),
    ("Admin Folder Assignment", "test_admin_folder_assignment_e2e.py"),
    ("Result Exit", "test_result_exit_e2e.py"),
    ("Sized Sets", "test_sized_sets_e2e.py"),
    ("User Isolation & Admin Content", "test_user_isolation_and_admin_content_e2e.py"),
]

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    python_bin = sys.executable

    print("\n" + "=" * 75)
    print("  🚀 SELF-HOSTED QUIZLET: FULL E2E REGRESSION TEST RUNNER")
    print(f"  Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Total Suites: {len(SUITES)}")
    print("=" * 75 + "\n")

    results = []
    total_start = time.time()

    for idx, (name, filename) in enumerate(SUITES, 1):
        file_path = os.path.join(script_dir, filename)
        print(f"[{idx}/{len(SUITES)}] Running {name} ({filename})...")
        suite_start = time.time()

        proc = subprocess.run(
            [python_bin, file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        duration = time.time() - suite_start
        success = (proc.returncode == 0)

        # Parse test counts from output
        passed_count = 0
        failed_count = 0
        for line in proc.stdout.splitlines():
            if "Total:" in line and "Passed:" in line and "Failed:" in line:
                try:
                    parts = line.split("|")
                    passed_count = int(parts[1].split(":")[1].strip())
                    failed_count = int(parts[2].split(":")[1].strip())
                except Exception:
                    pass

        status_str = "✅ PASS" if success else "❌ FAIL"
        print(f"    → {status_str} in {duration:.1f}s (Passed: {passed_count}, Failed: {failed_count})\n")

        # Cleanup any stray geckodriver processes that might linger
        try:
            subprocess.run(["pkill", "-f", "geckodriver"], stderr=subprocess.DEVNULL)
        except Exception:
            pass

        results.append({
            "index": idx,
            "name": name,
            "file": filename,
            "passed": success,
            "duration": duration,
            "tests_passed": passed_count,
            "tests_failed": failed_count,
            "output": proc.stdout if not success else "",
        })

    total_duration = time.time() - total_start
    total_passed_suites = sum(1 for r in results if r["passed"])
    total_failed_suites = len(results) - total_passed_suites
    total_tests_passed = sum(r["tests_passed"] for r in results)
    total_tests_failed = sum(r["tests_failed"] for r in results)

    # Print summary table
    print("\n" + "=" * 75)
    print("                      FINAL E2E EXECUTION SCORECARD")
    print("=" * 75)
    print(f"{'#':<3} | {'Test Suite':<35} | {'Status':<8} | {'Tests':<10} | {'Time':<8}")
    print("-" * 75)

    for r in results:
        status_label = "PASS" if r["passed"] else "FAIL"
        test_summary = f"{r['tests_passed']} passed" if r["passed"] else f"{r['tests_failed']} FAILED"
        print(f"{r['index']:<3} | {r['name']:<35} | {status_label:<8} | {test_summary:<10} | {r['duration']:>5.1f}s")

    print("-" * 75)
    print(f"Suites: {total_passed_suites}/{len(SUITES)} passed | Tests: {total_tests_passed} passed, {total_tests_failed} failed | Total Time: {total_duration:.1f}s")
    print("=" * 75 + "\n")

    if total_failed_suites > 0:
        print("❌ FAILURES DETECTED:")
        for r in results:
            if not r["passed"]:
                print(f"\n--- Output of {r['name']} ({r['file']}) ---")
                print(r["output"][-1500:])
        sys.exit(1)
    else:
        print(f"🎉 ALL {len(SUITES)} TEST SUITES PASSED FLAWLESSLY!")
        sys.exit(0)

if __name__ == "__main__":
    main()
