# === META-PROCESS TARGETS ===
# Added by meta-process install.sh

# Configuration
SCRIPTS_META := scripts/meta
PLANS_DIR := docs/plans

# --- Session Start ---
.PHONY: status

status:  ## Show git status
	@git status --short --branch

# --- During Implementation ---
.PHONY: test test-quick check

test:  ## Run pytest
	pytest tests/ -v

test-quick:  ## Run pytest (no traceback)
	pytest tests/ -q --tb=no

check:  ## Run all checks (test, mypy, lint)
	@echo "Running tests..."
	@pytest tests/ -q --tb=short
	@echo ""
	@echo "Running mypy..."
	@mypy src/ --ignore-missing-imports
	@echo ""
	@echo "All checks passed!"

# --- PR Workflow ---
.PHONY: pr-ready pr merge finish

pr-ready:  ## Rebase on main and push
	@git fetch origin main
	@git rebase origin/main
	@git push -u origin HEAD

pr:  ## Create PR (opens browser)
	@gh pr create --fill --web

merge:  ## Merge PR (PR=number required)
ifndef PR
	$(error PR is required. Usage: make merge PR=123)
endif
	@python $(SCRIPTS_META)/merge_pr.py $(PR)

finish:  ## Merge PR + cleanup branch (BRANCH=name PR=number required)
ifndef BRANCH
	$(error BRANCH is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
ifndef PR
	$(error PR is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
	@gh pr merge $(PR) --squash --delete-branch
	@git checkout main && git pull --ff-only
	@git branch -d $(BRANCH) 2>/dev/null || true

# --- Plans ---
.PHONY: plan-tests plan-complete

plan-tests:  ## Check plan's required tests (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-tests PLAN=42)
endif
	@python $(SCRIPTS_META)/check_plan_tests.py --plan $(PLAN)

plan-complete:  ## Mark plan complete with verification (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-complete PLAN=42)
endif
	@python $(SCRIPTS_META)/complete_plan.py --plan $(PLAN)

# --- Help ---
.PHONY: help-meta

help-meta:  ## Show meta-process targets
	@echo "Meta-Process Targets:"
	@echo ""
	@echo "  Session:"
	@echo "    status          Show git status"
	@echo ""
	@echo "  Development:"
	@echo "    test            Run tests"
	@echo "    check           Run all checks"
	@echo ""
	@echo "  PR Workflow:"
	@echo "    pr-ready        Rebase + push"
	@echo "    pr              Create PR"
	@echo "    merge           Merge PR (PR=number)"
	@echo "    finish          Merge + cleanup (BRANCH=name PR=number)"
	@echo ""
	@echo "  Plans:"
	@echo "    plan-tests      Check plan tests (PLAN=N)"
	@echo "    plan-complete   Complete plan (PLAN=N)"

# === META-PROCESS TARGETS ===
# Added by meta-process install.sh

# Configuration
SCRIPTS_META := scripts/meta
PLANS_DIR := docs/plans

# --- Session Start ---
.PHONY: status

status:  ## Show git status
	@git status --short --branch

# --- During Implementation ---
.PHONY: test test-quick check

test:  ## Run pytest
	pytest tests/ -v

test-quick:  ## Run pytest (no traceback)
	pytest tests/ -q --tb=no

check:  ## Run all checks (test, mypy, lint)
	@echo "Running tests..."
	@pytest tests/ -q --tb=short
	@echo ""
	@echo "Running mypy..."
	@mypy src/ --ignore-missing-imports
	@echo ""
	@echo "All checks passed!"

# --- PR Workflow ---
.PHONY: pr-ready pr merge finish

pr-ready:  ## Rebase on main and push
	@git fetch origin main
	@git rebase origin/main
	@git push -u origin HEAD

pr:  ## Create PR (opens browser)
	@gh pr create --fill --web

merge:  ## Merge PR (PR=number required)
ifndef PR
	$(error PR is required. Usage: make merge PR=123)
endif
	@python $(SCRIPTS_META)/merge_pr.py $(PR)

finish:  ## Merge PR + cleanup branch (BRANCH=name PR=number required)
ifndef BRANCH
	$(error BRANCH is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
ifndef PR
	$(error PR is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
	@gh pr merge $(PR) --squash --delete-branch
	@git checkout main && git pull --ff-only
	@git branch -d $(BRANCH) 2>/dev/null || true

# --- Plans ---
.PHONY: plan-tests plan-complete

plan-tests:  ## Check plan's required tests (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-tests PLAN=42)
endif
	@python $(SCRIPTS_META)/check_plan_tests.py --plan $(PLAN)

plan-complete:  ## Mark plan complete with verification (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-complete PLAN=42)
endif
	@python $(SCRIPTS_META)/complete_plan.py --plan $(PLAN)

# --- Help ---
.PHONY: help-meta

help-meta:  ## Show meta-process targets
	@echo "Meta-Process Targets:"
	@echo ""
	@echo "  Session:"
	@echo "    status          Show git status"
	@echo ""
	@echo "  Development:"
	@echo "    test            Run tests"
	@echo "    check           Run all checks"
	@echo ""
	@echo "  PR Workflow:"
	@echo "    pr-ready        Rebase + push"
	@echo "    pr              Create PR"
	@echo "    merge           Merge PR (PR=number)"
	@echo "    finish          Merge + cleanup (BRANCH=name PR=number)"
	@echo ""
	@echo "  Plans:"
	@echo "    plan-tests      Check plan tests (PLAN=N)"
	@echo "    plan-complete   Complete plan (PLAN=N)"

# === META-PROCESS TARGETS ===
# Added by meta-process install.sh

# Configuration
SCRIPTS_META := scripts/meta
PLANS_DIR := docs/plans
GITHUB_ACCOUNT ?= BrianMills2718
PR_AUTO_EXPECTED_REPO ?= $(notdir $(CURDIR))

# --- Session Start ---
.PHONY: status

status:  ## Show git status
	@git status --short --branch

# --- During Implementation ---
.PHONY: test test-quick check

test:  ## Run pytest
	pytest tests/ -v

test-quick:  ## Run pytest (no traceback)
	pytest tests/ -q --tb=no

check:  ## Run all checks (test, mypy, lint)
	@echo "Running tests..."
	@pytest tests/ -q --tb=short
	@echo ""
	@echo "Running mypy..."
	@mypy src/ --ignore-missing-imports
	@echo ""
	@echo "All checks passed!"

# --- PR Workflow ---
.PHONY: pr-ready pr merge finish pr-auto-check pr-auto

pr-ready:  ## Rebase on main and push
	@git fetch origin main
	@git rebase origin/main
	@git push -u origin HEAD

pr:  ## Create PR (opens browser)
	@gh pr create --fill --web

pr-auto-check:  ## Autonomous PR preflight (branch/clean tree/origin/account)
	@python $(SCRIPTS_META)/pr_auto.py --preflight-only --expected-origin-repo $(PR_AUTO_EXPECTED_REPO) --account $(GITHUB_ACCOUNT)

pr-auto:  ## Autonomous PR create + auto-merge request (non-interactive)
	@python $(SCRIPTS_META)/pr_auto.py --expected-origin-repo $(PR_AUTO_EXPECTED_REPO) --account $(GITHUB_ACCOUNT) --fill --auto-merge

merge:  ## Merge PR (PR=number required)
ifndef PR
	$(error PR is required. Usage: make merge PR=123)
endif
	@python $(SCRIPTS_META)/merge_pr.py $(PR)

finish:  ## Merge PR + cleanup branch (BRANCH=name PR=number required)
ifndef BRANCH
	$(error BRANCH is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
ifndef PR
	$(error PR is required. Usage: make finish BRANCH=plan-42-feature PR=123)
endif
	@gh pr merge $(PR) --squash --delete-branch
	@git checkout main && git pull --ff-only
	@git branch -d $(BRANCH) 2>/dev/null || true

# --- Plans ---
.PHONY: plan-tests plan-complete

plan-tests:  ## Check plan's required tests (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-tests PLAN=42)
endif
	@python $(SCRIPTS_META)/check_plan_tests.py --plan $(PLAN)

plan-complete:  ## Mark plan complete with verification (PLAN=N required)
ifndef PLAN
	$(error PLAN is required. Usage: make plan-complete PLAN=42)
endif
	@python $(SCRIPTS_META)/complete_plan.py --plan $(PLAN)

# --- Quality ---
.PHONY: dead-code

dead-code:  ## Run dead code detection
	@python $(SCRIPTS_META)/check_dead_code.py

# --- Help ---
.PHONY: help-meta

help-meta:  ## Show meta-process targets
	@echo "Meta-Process Targets:"
	@echo ""
	@echo "  Session:"
	@echo "    status          Show git status"
	@echo ""
	@echo "  Development:"
	@echo "    test            Run tests"
	@echo "    check           Run all checks"
	@echo ""
	@echo "  PR Workflow:"
	@echo "    pr-ready        Rebase + push"
	@echo "    pr              Create PR"
	@echo "    pr-auto-check   Preflight autonomous PR flow"
	@echo "    pr-auto         Non-interactive PR + auto-merge request"
	@echo "    merge           Merge PR (PR=number)"
	@echo "    finish          Merge + cleanup (BRANCH=name PR=number)"
	@echo ""
	@echo "  Quality:"
	@echo "    dead-code       Run dead code detection"
	@echo ""
	@echo "  Plans:"
	@echo "    plan-tests      Check plan tests (PLAN=N)"
	@echo "    plan-complete   Complete plan (PLAN=N)"
