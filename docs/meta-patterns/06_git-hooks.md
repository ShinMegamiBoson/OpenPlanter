# Pattern: Git Hooks

## Problem

CI catches issues, but feedback is slow. By the time CI fails:
- Developer has context-switched
- Fixes require another commit cycle
- AI assistants may have moved on to other tasks

## Solution

1. Track hooks in repo (not `.git/hooks/` which is ignored)
2. Use `core.hooksPath` to point git at tracked hooks
3. Run fast checks pre-commit (doc-coupling, type checking)
4. Enforce commit message format (plan references)
5. Provide setup script for new clones

## Files

| File | Purpose |
|------|---------|
| `hooks/pre-commit` | Runs before commit is created |
| `hooks/commit-msg` | Validates commit message format |
| `scripts/setup_hooks.sh` | One-time setup after clone |

## Setup

### 1. Create hooks directory

```bash
mkdir hooks
```

### 2. Create pre-commit hook

```bash
#!/bin/bash
# hooks/pre-commit
set -e

echo "Running pre-commit checks..."
REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

# Get staged files
STAGED_PY=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' || true)

# 1. Doc-coupling check
echo "Checking doc-code coupling..."
if ! python scripts/check_doc_coupling.py --strict 2>/dev/null; then
    echo "ERROR: Doc-coupling violation!"
    echo "Run 'python scripts/check_doc_coupling.py --suggest' for help"
    exit 1
fi

# 2. Type checking on changed src/ files
STAGED_SRC=$(echo "$STAGED_PY" | grep '^src/' || true)
if [ -n "$STAGED_SRC" ]; then
    echo "Running mypy..."
    if ! python -m mypy --ignore-missing-imports $STAGED_SRC 2>/dev/null; then
        echo "ERROR: mypy failed!"
        exit 1
    fi
fi

# 3. Lint check (optional)
# if [ -n "$STAGED_PY" ]; then
#     echo "Running ruff..."
#     ruff check $STAGED_PY
# fi

echo "Pre-commit checks passed!"
```

### 3. Create commit-msg hook

```bash
#!/bin/bash
# hooks/commit-msg
COMMIT_MSG_FILE="$1"
FIRST_LINE=$(head -n1 "$COMMIT_MSG_FILE")

# Allow merge commits
if [[ "$FIRST_LINE" =~ ^Merge ]]; then
    exit 0
fi

# Allow fixup/squash commits
if [[ "$FIRST_LINE" =~ ^(fixup!|squash!) ]]; then
    exit 0
fi

# Check for plan reference
if [[ "$FIRST_LINE" =~ ^\[Plan\ \#[0-9]+\] ]]; then
    exit 0
fi

if [[ "$FIRST_LINE" =~ ^\[Unplanned\] ]]; then
    echo "WARNING: Unplanned work. Create a plan before merging."
    exit 0
fi

echo "ERROR: Commit message must include [Plan #N] or [Unplanned]"
echo "  e.g. [Plan #3] Implement feature X"
exit 1
```

### 4. Make hooks executable

```bash
chmod +x hooks/*
```

### 5. Create setup script

```bash
#!/bin/bash
# scripts/setup_hooks.sh
set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR="$REPO_ROOT/hooks"

if [ ! -d "$HOOKS_DIR" ]; then
    echo "ERROR: hooks/ directory not found"
    exit 1
fi

chmod +x "$HOOKS_DIR"/*
git config core.hooksPath hooks

echo "Git hooks configured!"
echo "  - pre-commit: Runs checks before commit"
echo "  - commit-msg: Validates commit message format"
```

### 6. Document in README

```markdown
## Setup

After cloning:
\`\`\`bash
bash scripts/setup_hooks.sh
\`\`\`
```

## Usage

### Normal workflow

```bash
# Hooks run automatically
git add .
git commit -m "[Plan #3] Implement feature X"
# pre-commit runs → commit-msg validates → commit created
```

### Bypass (emergency only)

```bash
git commit --no-verify -m "Emergency fix"
```

### Re-run setup after clone

```bash
bash scripts/setup_hooks.sh
```

## Customization

### Add more pre-commit checks

```bash
# In hooks/pre-commit

# Run tests on changed files
STAGED_TESTS=$(echo "$STAGED_PY" | grep '^tests/' || true)
if [ -n "$STAGED_TESTS" ]; then
    echo "Running affected tests..."
    pytest $STAGED_TESTS -x
fi

# Check for debug statements
if git diff --cached | grep -E '(pdb|breakpoint|console\.log)'; then
    echo "ERROR: Debug statements found!"
    exit 1
fi

# Check for secrets
if git diff --cached | grep -iE '(api_key|password|secret)\s*=\s*["\047]'; then
    echo "ERROR: Possible secret in commit!"
    exit 1
fi
```

### Change commit message format

```bash
# In hooks/commit-msg

# Require conventional commits format
if [[ "$FIRST_LINE" =~ ^(feat|fix|docs|style|refactor|test|chore)(\(.+\))?:\ .+ ]]; then
    exit 0
fi

echo "ERROR: Use conventional commits format"
echo "  e.g. feat(auth): add login button"
exit 1
```

### Add prepare-commit-msg hook

```bash
#!/bin/bash
# hooks/prepare-commit-msg
# Auto-add branch name to commit message

COMMIT_MSG_FILE="$1"
BRANCH=$(git branch --show-current)

# Extract plan number from branch name
if [[ "$BRANCH" =~ ^plan-([0-9]+) ]]; then
    PLAN_NUM="${BASH_REMATCH[1]}"
    # Prepend plan reference if not present
    if ! grep -q "^\[Plan #" "$COMMIT_MSG_FILE"; then
        sed -i "1s/^/[Plan #$PLAN_NUM] /" "$COMMIT_MSG_FILE"
    fi
fi
```

## Limitations

- **Not enforced on force-push** - Someone can bypass with `--no-verify`.
- **New clones need setup** - Must run `setup_hooks.sh` after every clone.
- **Slow checks hurt velocity** - Keep pre-commit fast (<5 seconds).
- **Platform differences** - Bash hooks may not work on Windows without WSL.

## Best Practices

1. **Keep hooks fast** - Run expensive checks in CI, not hooks
2. **Provide bypass** - `--no-verify` for emergencies
3. **Document setup** - Make it obvious in README
4. **Fail with helpful messages** - Tell users how to fix issues
5. **Test hooks** - Run them manually before committing

## See Also

- [Doc-code coupling pattern](10_doc-code-coupling.md) - Often run as pre-commit check
- [Plan workflow pattern](15_plan-workflow.md) - Commit message format ties to plans
