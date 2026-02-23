#!/usr/bin/env python3
"""Verify that required tests for a plan exist and pass.

Strict by default for In Progress plans (Plan #70): If a plan is In Progress
but has missing required tests, this script will fail with exit code 1.
This enforces TDD workflow - tests must exist before implementation is complete.

Usage:
    # Check all tests for plan #1
    python scripts/check_plan_tests.py --plan 1

    # TDD mode - show which tests need to be written
    python scripts/check_plan_tests.py --plan 1 --tdd

    # Check all plans with tests defined
    python scripts/check_plan_tests.py --all

    # List plans and their test requirements
    python scripts/check_plan_tests.py --list
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class TestRequirement:
    """A required test for a plan."""
    file: str
    function: str | None = None  # None means all tests in file
    description: str = ""
    is_new: bool = False  # New test to create (TDD) vs existing


@dataclass
class PlanTests:
    """Test requirements for a plan."""
    plan_number: int
    plan_name: str
    plan_file: Path
    status: str
    new_tests: list[TestRequirement] = field(default_factory=list)
    existing_tests: list[TestRequirement] = field(default_factory=list)


def parse_plan_file(plan_file: Path) -> PlanTests | None:
    """Parse a plan file for test requirements."""
    content = plan_file.read_text()

    # Extract plan number from filename
    match = re.match(r"(\d+)_(.+)\.md", plan_file.name)
    if not match:
        return None

    plan_number = int(match.group(1))
    plan_name = match.group(2).replace("_", " ").title()

    # Extract status
    status_match = re.search(r"\*\*Status:\*\*\s*(.+)", content)
    status = status_match.group(1).strip() if status_match else "Unknown"

    plan = PlanTests(
        plan_number=plan_number,
        plan_name=plan_name,
        plan_file=plan_file,
        status=status
    )

    # Find Required Tests section
    tests_section = re.search(
        r"## Required Tests\s*\n(.*?)(?=\n## |\Z)",
        content,
        re.DOTALL
    )

    if not tests_section:
        return plan

    section_content = tests_section.group(1)

    # Parse New Tests table (existing format)
    new_tests_match = re.search(
        r"### New Tests.*?\n\|.*?\n\|[-\s|]+\n((?:\|.*?\n)*)",
        section_content,
        re.DOTALL
    )

    if new_tests_match:
        for line in new_tests_match.group(1).strip().split("\n"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 2:
                test_file = cells[0].strip("`")
                test_func = cells[1].strip("`") if cells[1] else None
                desc = cells[2] if len(cells) > 2 else ""
                plan.new_tests.append(TestRequirement(
                    file=test_file,
                    function=test_func,
                    description=desc,
                    is_new=True
                ))

    # Parse Existing Tests table (existing format)
    existing_match = re.search(
        r"### Existing Tests.*?\n\|.*?\n\|[-\s|]+\n((?:\|.*?\n)*)",
        section_content,
        re.DOTALL
    )

    if existing_match:
        for line in existing_match.group(1).strip().split("\n"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 1:
                pattern = cells[0].strip("`")
                desc = cells[1] if len(cells) > 1 else ""

                # Parse pattern - could be file or file::function
                if "::" in pattern:
                    file_part, func_part = pattern.split("::", 1)
                else:
                    file_part, func_part = pattern, None

                plan.existing_tests.append(TestRequirement(
                    file=file_part,
                    function=func_part,
                    description=desc,
                    is_new=False
                ))

    # NEW (Plan #41): Parse bullet list format
    # Matches: - `tests/foo.py::test_bar`
    # Matches: - `tests/foo.py::TestClass::test_method`
    # Note: Don't anchor to $ as some lines may have trailing content
    bullet_pattern = re.compile(
        r"^-\s+`([^`]+)`",
        re.MULTILINE
    )

    for match in bullet_pattern.finditer(section_content):
        test_spec = match.group(1).strip()
        description = ""  # Bullet format doesn't capture description

        # Parse test spec - could be file, file::func, or file::Class::func
        if "::" in test_spec:
            parts = test_spec.split("::", 1)
            file_part = parts[0]
            func_part = parts[1]  # Could be "test_foo" or "TestClass::test_foo"
        else:
            file_part = test_spec
            func_part = None

        # Check if this test is already in our lists (avoid duplicates from tables)
        is_duplicate = False
        for existing in plan.new_tests + plan.existing_tests:
            if existing.file == file_part and existing.function == func_part:
                is_duplicate = True
                break

        if not is_duplicate:
            # Bullet format tests are treated as "new" (TDD style)
            plan.new_tests.append(TestRequirement(
                file=file_part,
                function=func_part,
                description=description,
                is_new=True
            ))

    # NEW (Plan #41): Parse inline code format
    # Matches: `tests/foo.py::test_bar` - description
    # Matches: `tests/foo.py::TestClass::test_method` description
    # Matches: `tests/foo.py` (file only)
    # Must NOT be preceded by "- " (already handled by bullet format)
    inline_pattern = re.compile(
        r"(?<!- )`(tests/[^`]+)`(?:\s*[-–—]?\s*(.*))?",
        re.MULTILINE
    )

    for match in inline_pattern.finditer(section_content):
        test_spec = match.group(1).strip()
        description = match.group(2).strip() if match.group(2) else ""

        # Parse test spec - could be file, file::func, or file::Class::func
        if "::" in test_spec:
            parts = test_spec.split("::", 1)
            file_part = parts[0]
            func_part = parts[1]  # Could be "test_foo" or "TestClass::test_foo"
        else:
            file_part = test_spec
            func_part = None

        # Check if this test is already in our lists (avoid duplicates)
        is_duplicate = False
        for existing in plan.new_tests + plan.existing_tests:
            if existing.file == file_part and existing.function == func_part:
                is_duplicate = True
                break

        if not is_duplicate:
            # Inline format tests are treated as "new" (TDD style)
            plan.new_tests.append(TestRequirement(
                file=file_part,
                function=func_part,
                description=description,
                is_new=True
            ))

    return plan


def find_plan_files(plans_dir: Path) -> list[Path]:
    """Find all plan files."""
    return sorted(
        [f for f in plans_dir.glob("*.md")
         if re.match(r"\d+_", f.name)],
        key=lambda f: int(f.name.split("_")[0])
    )


def find_test_class(content: str, func_name: str) -> str | None:
    """Find the class containing a test function, if any.

    Returns class name if function is in a class, None if at top level.
    """
    lines = content.split("\n")
    current_class: str | None = None
    func_pattern = re.compile(rf"^\s*def\s+{re.escape(func_name)}\s*\(")
    class_pattern = re.compile(r"^class\s+(\w+)\s*[:\(]")

    for line in lines:
        # Check for class definition (not indented)
        class_match = class_pattern.match(line)
        if class_match:
            current_class = class_match.group(1)

        # Check for function (may be indented if in class)
        if func_pattern.search(line):
            return current_class

    return None


def get_pytest_path(req: TestRequirement, project_root: Path) -> str | None:
    """Get the correct pytest path for a test requirement.

    Returns the full pytest path (with class if needed) or None if test doesn't exist.
    Plan #41: This handles the case where tests are specified without class prefix
    but are actually inside a class.
    """
    test_file = project_root / req.file

    if not test_file.exists():
        return None

    if not req.function:
        return req.file

    content = test_file.read_text()

    # Handle TestClass::test_function format (already complete)
    if "::" in req.function:
        class_name, func_name = req.function.split("::", 1)
        class_pattern = rf"class\s+{re.escape(class_name)}\s*[:\(]"
        func_pattern = rf"def\s+{re.escape(func_name)}\s*\("
        if re.search(class_pattern, content) and re.search(func_pattern, content):
            return f"{req.file}::{req.function}"
        return None

    # Function without class - check if it exists
    func_pattern = rf"def\s+{re.escape(req.function)}\s*\("
    if not re.search(func_pattern, content):
        return None

    # Find if function is in a class
    containing_class = find_test_class(content, req.function)
    if containing_class:
        return f"{req.file}::{containing_class}::{req.function}"
    else:
        return f"{req.file}::{req.function}"


def check_test_exists(req: TestRequirement, project_root: Path) -> bool:
    """Check if a test file/function exists."""
    return get_pytest_path(req, project_root) is not None


def run_tests(requirements: list[TestRequirement], project_root: Path) -> tuple[int, str]:
    """Run pytest for the given requirements. Returns (exit_code, output)."""
    if not requirements:
        return 0, "No tests to run"

    pytest_args = ["pytest", "-v"]

    for req in requirements:
        # Plan #41: Use get_pytest_path to get the correct path with class prefix
        pytest_path = get_pytest_path(req, project_root)
        if pytest_path:
            pytest_args.append(pytest_path)
        elif req.function:
            # Fallback to original format if get_pytest_path returns None
            pytest_args.append(f"{req.file}::{req.function}")
        else:
            pytest_args.append(req.file)

    result = subprocess.run(
        pytest_args,
        cwd=project_root,
        capture_output=True,
        text=True
    )

    return result.returncode, result.stdout + result.stderr


def list_plans(plans_dir: Path) -> None:
    """List all plans and their test requirements."""
    for plan_file in find_plan_files(plans_dir):
        plan = parse_plan_file(plan_file)
        if not plan:
            continue

        total_tests = len(plan.new_tests) + len(plan.existing_tests)
        test_info = f"{total_tests} tests" if total_tests else "no tests defined"
        print(f"#{plan.plan_number:2d} {plan.plan_name:30s} {plan.status:20s} ({test_info})")


def check_plan(plan: PlanTests, project_root: Path, tdd_mode: bool = False, strict: bool = False) -> int:
    """Check tests for a single plan. Returns exit code."""
    print(f"\n{'='*60}")
    print(f"Plan #{plan.plan_number}: {plan.plan_name}")
    print(f"Status: {plan.status}")
    print(f"File: {plan.plan_file}")
    print(f"{'='*60}\n")

    all_requirements = plan.new_tests + plan.existing_tests

    if not all_requirements:
        print("No test requirements defined for this plan.")
        print("Add a '## Required Tests' section to define tests.")
        # Plan #70: Always fail for in-progress plans without tests (was --strict only)
        is_in_progress = "In Progress" in plan.status or "🚧" in plan.status
        if is_in_progress:
            print("\n❌ ERROR: Plan is In Progress but has no tests defined!")
            print("   TDD workflow requires tests to be defined before implementation.")
            return 1
        return 0

    # Plan #41: Only fail for in-progress plans, not complete ones
    # Complete plans have already been verified (or should have been)
    # Missing tests in complete plans are a documentation cleanup issue
    is_complete = "Complete" in plan.status or "✅" in plan.status

    # Check which tests exist
    print("Test Existence Check:")
    print("-" * 40)

    missing_tests: list[TestRequirement] = []
    existing_tests: list[TestRequirement] = []

    for req in all_requirements:
        exists = check_test_exists(req, project_root)
        status = "[EXISTS]" if exists else "[MISSING]"
        test_name = f"{req.file}::{req.function}" if req.function else req.file
        marker = " (NEW)" if req.is_new else ""
        print(f"  {status} {test_name}{marker}")

        if exists:
            existing_tests.append(req)
        else:
            missing_tests.append(req)

    print()

    # TDD Mode: Just report what needs to be written
    if tdd_mode:
        if missing_tests:
            print("TDD Mode - Tests to write:")
            print("-" * 40)
            for req in missing_tests:
                test_name = f"{req.file}::{req.function}" if req.function else req.file
                print(f"  - {test_name}")
                if req.description:
                    print(f"    Purpose: {req.description}")
            return 1
        else:
            print("All required tests exist!")
            print("Run without --tdd to execute them.")
            return 0

    # Normal mode: Run existing tests
    if missing_tests:
        if is_complete:
            print("NOTE: Some documented tests are missing (plan is Complete, not blocking CI).")
            print("Consider updating the plan's Required Tests section.\n")
        else:
            print("❌ ERROR: Some required tests are missing!")
            print("   TDD workflow requires all tests to exist before plan completion.")
            print("   Use --tdd to see what needs to be written.\n")

    if not existing_tests:
        print("No existing tests to run.")
        # Plan #41: Don't fail for Complete plans with missing tests
        if is_complete:
            print("(Plan is Complete - not blocking CI for documentation issue)")
            return 0
        return 1 if missing_tests else 0

    print("Running Tests:")
    print("-" * 40)

    exit_code, output = run_tests(existing_tests, project_root)
    print(output)

    if exit_code == 0 and not missing_tests:
        print("\nAll required tests pass!")
        return 0
    elif exit_code == 0:
        if is_complete:
            print("\nExisting tests pass. (Missing tests noted but not blocking - plan Complete)")
            return 0
        else:
            print("\nExisting tests pass, but some tests are missing.")
            return 1
    else:
        print("\nSome tests failed!")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify plan test requirements",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        "--plan", "-p",
        type=int,
        help="Plan number to check (e.g., 1 for plan #1)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Check all plans with test requirements"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all plans and their test status"
    )
    parser.add_argument(
        "--tdd",
        action="store_true",
        help="TDD mode - show which tests need to be written"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode - fail for In Progress plans without tests defined"
    )
    parser.add_argument(
        "--plans-dir",
        type=Path,
        default=Path("docs/plans"),
        help="Plans directory (default: docs/plans)"
    )

    args = parser.parse_args()

    project_root = Path.cwd()
    plans_dir = project_root / args.plans_dir

    if not plans_dir.exists():
        print(f"Error: Plans directory not found: {plans_dir}")
        return 1

    if args.list:
        list_plans(plans_dir)
        return 0

    if args.plan:
        # Find specific plan
        plan_files = [f for f in find_plan_files(plans_dir)
                     if f.name.startswith(f"{args.plan:02d}_") or
                        f.name.startswith(f"{args.plan}_")]

        if not plan_files:
            print(f"Error: No plan found with number {args.plan}")
            return 1

        plan = parse_plan_file(plan_files[0])
        if not plan:
            print(f"Error: Could not parse plan file: {plan_files[0]}")
            return 1

        return check_plan(plan, project_root, args.tdd, args.strict)

    if args.all:
        exit_code = 0
        # Plan #109: Only RUN tests for In Progress plans
        # Complete plans have their tests verified by pytest tests/ in the test job
        # We just verify Complete plan tests EXIST (documentation check)
        in_progress_statuses = ["In Progress", "🚧"]
        complete_statuses = ["Complete", "✅"]

        for plan_file in find_plan_files(plans_dir):
            plan = parse_plan_file(plan_file)
            if not plan:
                continue

            is_in_progress = any(status in plan.status for status in in_progress_statuses)
            is_complete = any(status in plan.status for status in complete_statuses)

            # Skip plans that aren't In Progress or Complete
            if not is_in_progress and not is_complete:
                continue

            has_tests = plan.new_tests or plan.existing_tests

            # Plan #70: Fail for In Progress plans without tests
            if not has_tests:
                if is_in_progress:
                    print(f"\n❌ Plan #{plan.plan_number} ({plan.plan_name}) is In Progress but has NO tests defined!")
                    print(f"   Add a '## Required Tests' section to: {plan.plan_file}")
                    exit_code = 1
                # Complete plans without tests: skip silently
                continue

            # Plan #109: For Complete plans, only verify tests exist (don't run)
            # The pytest tests/ job already runs all tests
            if is_complete:
                all_requirements = plan.new_tests + plan.existing_tests
                missing = [r for r in all_requirements if not check_test_exists(r, project_root)]
                if missing:
                    print(f"Plan #{plan.plan_number} ({plan.plan_name}): {len(missing)} documented tests missing (non-blocking)")
                continue

            # In Progress plans: run tests (TDD enforcement)
            result = check_plan(plan, project_root, args.tdd, args.strict)
            if result != 0:
                exit_code = 1
        return exit_code

    # Default: show help
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
