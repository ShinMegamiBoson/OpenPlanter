# Pattern: PR Coordination

## Problem

When multiple AI instances (or humans) work in parallel, PRs get created but:
- Other instances don't know a PR needs review
- Work tracking tables (Active Work) don't get updated
- After merge, cleanup doesn't happen (stale claims remain)

## Solution

1. GitHub Action triggers on PR events (open, close, merge)
2. Automatically updates coordination files (Active Work table, claims)
3. Extracts plan number from PR title `[Plan #N]` for tracking
4. Surfaces review requests visibly

## Files

| File | Purpose |
|------|---------|
| `.github/workflows/pr-coordination.yml` | GitHub Action workflow |
| `scripts/check_claims.py` | Claim management script |
| `.claude/active-work.yaml` | Machine-readable claim storage |
| `CLAUDE.md` | Active Work table (human-readable) |

## Setup

### 1. Create the workflow

```yaml
# .github/workflows/pr-coordination.yml
name: PR Coordination

on:
  pull_request:
    types: [opened, closed, reopened]

permissions:
  contents: write
  pull-requests: read

jobs:
  update-coordination:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install pyyaml

      - name: Extract plan number from PR title
        id: extract
        run: |
          TITLE="${{ github.event.pull_request.title }}"
          if [[ "$TITLE" =~ \[Plan\ #([0-9]+)\] ]]; then
            echo "plan_number=${BASH_REMATCH[1]}" >> $GITHUB_OUTPUT
            echo "has_plan=true" >> $GITHUB_OUTPUT
          else
            echo "has_plan=false" >> $GITHUB_OUTPUT
          fi

      - name: Handle PR opened
        if: github.event.action == 'opened'
        run: |
          # Claim work for this PR
          python scripts/check_claims.py --claim \
            --task "PR #${{ github.event.pull_request.number }}: ${{ github.event.pull_request.title }}" \
            ${{ steps.extract.outputs.has_plan == 'true' && format('--plan {0}', steps.extract.outputs.plan_number) || '' }}

      - name: Handle PR merged
        if: github.event.action == 'closed' && github.event.pull_request.merged
        run: |
          # Release claim and mark plan complete if applicable
          python scripts/check_claims.py --release
          if [ "${{ steps.extract.outputs.has_plan }}" == "true" ]; then
            # Update plan status to complete
            python scripts/sync_plan_status.py --plan ${{ steps.extract.outputs.plan_number }} --status complete
          fi

      - name: Handle PR closed without merge
        if: github.event.action == 'closed' && !github.event.pull_request.merged
        run: |
          # Just release the claim
          python scripts/check_claims.py --release

      - name: Commit coordination updates
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --staged --quiet || git commit -m "[Automated] Update coordination for PR #${{ github.event.pull_request.number }}"
          git push
```

### 2. Create the claims script

```python
#!/usr/bin/env python3
"""Manage work claims."""

import argparse
import yaml
from pathlib import Path
from datetime import datetime

CLAIMS_FILE = Path(".claude/active-work.yaml")

def load_claims() -> dict:
    if CLAIMS_FILE.exists():
        return yaml.safe_load(CLAIMS_FILE.read_text()) or {"claims": []}
    return {"claims": []}

def save_claims(data: dict) -> None:
    CLAIMS_FILE.parent.mkdir(exist_ok=True)
    CLAIMS_FILE.write_text(yaml.dump(data, default_flow_style=False))

def claim(task: str, plan: int | None = None) -> None:
    data = load_claims()
    data["claims"].append({
        "task": task,
        "plan": plan,
        "claimed_at": datetime.now().isoformat(),
        "status": "in_progress"
    })
    save_claims(data)
    print(f"Claimed: {task}")

def release() -> None:
    data = load_claims()
    if data["claims"]:
        released = data["claims"].pop()
        save_claims(data)
        print(f"Released: {released['task']}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--claim", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--task", type=str)
    parser.add_argument("--plan", type=int)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.claim:
        claim(args.task, args.plan)
    elif args.release:
        release()
    elif args.list:
        data = load_claims()
        for c in data["claims"]:
            print(f"- {c['task']} (claimed {c['claimed_at']})")

if __name__ == "__main__":
    main()
```

### 3. Create the claims file

```yaml
# .claude/active-work.yaml
claims: []
```

### 4. Add Active Work table to CLAUDE.md

```markdown
## Active Work

| Instance | Task | Plan | Claimed | Status |
|----------|------|------|---------|--------|
| - | - | - | - | - |
```

## Usage

### Automatic (via GitHub Actions)

1. **Create PR with plan link**: `[Plan #3] Implement feature X`
2. **On PR open**: Workflow claims work, updates Active Work table
3. **On PR merge**: Workflow releases claim, marks plan complete
4. **On PR close (no merge)**: Workflow releases claim

### Manual (when needed)

```bash
# Claim work
python scripts/check_claims.py --claim --task "Working on feature X" --plan 3

# List active claims
python scripts/check_claims.py --list

# Release claim
python scripts/check_claims.py --release

# Check for stale claims (>4 hours old)
python scripts/check_claims.py

# Clean up old completed entries
python scripts/check_claims.py --cleanup
```

### PR Title Convention

```
[Plan #N] Short description    # Links to plan, enables auto-tracking
[Unplanned] Short description  # No plan link, still tracked
Fix typo in readme             # No tracking (discouraged)
```

## Merging PRs

### Check if approval is required

```bash
# Check branch protection
gh api repos/OWNER/REPO/branches/main/protection 2>&1 | grep -q "not protected" && echo "No approval required"
```

### Merge workflow

| Branch Protection | Review Process | Merge Command |
|-------------------|----------------|---------------|
| None | Comment review, then merge | `gh pr merge N --squash --delete-branch` |
| Requires approval | Need different user to approve | `gh pr review N --approve` (then merge) |
| Requires CI | Wait for checks to pass | `gh pr merge N --auto --squash` |

**Common pattern (no branch protection):**
```bash
# 1. Review with comment (can't approve own PR)
gh pr review 46 --comment --body "LGTM - reviewed changes"

# 2. Merge directly
gh pr merge 46 --squash --delete-branch
```

**Note:** GitHub always blocks self-approval (`--approve` on your own PR), but if branch protection doesn't require approval, you can still merge directly.

## Customization

### Change stale threshold

```python
STALE_HOURS = 4  # Claims older than this are flagged
```

### Add Slack/Discord notification

```yaml
- name: Notify on PR open
  if: github.event.action == 'opened'
  run: |
    curl -X POST ${{ secrets.SLACK_WEBHOOK }} \
      -d '{"text": "PR needs review: ${{ github.event.pull_request.html_url }}"}'
```

### Require plan number

```yaml
- name: Validate PR title
  if: github.event.action == 'opened'
  run: |
    TITLE="${{ github.event.pull_request.title }}"
    if [[ ! "$TITLE" =~ \[Plan\ #[0-9]+\] ]] && [[ ! "$TITLE" =~ \[Unplanned\] ]]; then
      echo "PR title must include [Plan #N] or [Unplanned]"
      exit 1
    fi
```

## Limitations

- **GitHub-specific** - Uses GitHub Actions. Adapt for GitLab CI, etc.
- **Race conditions** - If two PRs merge simultaneously, coordination file may conflict.
- **Token permissions** - Needs `contents: write` to push updates.
- **Branch protection** - May conflict with protected branches requiring reviews.

## See Also

- [Claim system pattern](18_claim-system.md) - More detailed claim management
- [Plan workflow pattern](../15_plan-workflow.md) - How plans integrate with PRs

## Current Implementation (Simplified)

The full GitHub Actions workflow above is **not currently implemented**. Instead, we use a simpler approach:

```bash
# Discover PRs needing review
gh pr list                      # Direct GitHub query
python scripts/meta_status.py   # Aggregates claims, PRs, plan progress
```

**Why simplified?**
- Branch protection blocks direct pushes to main (required for auto-updating tables)
- `gh pr list` provides the same information without manual table maintenance
- Single source of truth (GitHub) eliminates stale/incorrect table state

**If automation is needed later:** Implement the workflow above with a GitHub App or PAT that can bypass branch protection for coordination-only updates.
