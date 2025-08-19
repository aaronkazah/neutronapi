#!/usr/bin/env python3
"""
Helper script to invoke selected migration tests via manage.py.
Kept under core/tests to avoid cluttering project root.

Usage examples:
  python -m core.tests.db.test_migrations_runner
  python -m core.tests.db.test_migrations_runner run core.tests.db.test_migrations_simple.TestBasicMigrationOperations
"""
import subprocess
import sys
import os


def run_migration_tests():
    test_modules = [
        "core.tests.db.test_migrations_simple.TestBasicMigrationOperations",
        "core.tests.db.test_migrations_simple.TestMigrationManagerBasic",
        "core.tests.db.test_migrations_simple.TestErrorHandling",
    ]

    print("=" * 60)
    print("COMPREHENSIVE MIGRATION TESTS")
    print("=" * 60)

    total_passed = 0
    total_failed = 0
    failures = []

    for test_module in test_modules:
        print(f"\nRunning {test_module}...")
        print("-" * 40)

        result = subprocess.run([
            sys.executable, "manage.py", "test", test_module
        ], capture_output=True, text=True, cwd=os.getcwd())

        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)

        if result.returncode == 0:
            # Coarse parsing for count
            lines = result.stdout.split('\n')
            for line in lines:
                if line.startswith("Ran ") and " test" in line:
                    num_tests = int(line.split()[1])
                    if "OK" in result.stdout:
                        total_passed += num_tests
                    else:
                        total_failed += num_tests
                        failures.append(test_module)
                    break
        else:
            print(f"❌ FAILED: {test_module}")
            failures.append(test_module)
            total_failed += 1

    print("\n" + "=" * 60)
    print("MIGRATION TEST SUMMARY")
    print("=" * 60)
    print(f"Total passed: {total_passed}")
    print(f"Total failed: {total_failed}")

    if failures:
        print("\nFailed test modules:")
        for failure in failures:
            print(f"  - {failure}")

    success = total_failed == 0
    print(f"\nOverall: {'✅ PASSED' if success else '❌ FAILED'}")
    return success


def run_specific_test(test_name: str):
    print(f"Running specific test: {test_name}")
    result = subprocess.run([sys.executable, "manage.py", "test", test_name], cwd=os.getcwd())
    return result.returncode == 0


def list_available_tests():
    print("Available migration test modules:")
    print("  core.tests.db.test_migrations_simple.TestBasicMigrationOperations")
    print("  core.tests.db.test_migrations_simple.TestMigrationManagerBasic")
    print("  core.tests.db.test_migrations_simple.TestErrorHandling")
    print()
    print("Usage:")
    print("  python -m core.tests.db.test_migrations_runner")
    print("  python -m core.tests.db.test_migrations_runner run <dotted.test.path>")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "list":
            list_available_tests()
        elif command == "run" and len(sys.argv) > 2:
            ok = run_specific_test(sys.argv[2])
            sys.exit(0 if ok else 1)
        else:
            print("Unknown command. Use 'list' or 'run <test_name>'")
            sys.exit(1)
    else:
        ok = run_migration_tests()
        sys.exit(0 if ok else 1)

