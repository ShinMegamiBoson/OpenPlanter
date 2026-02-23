#!/bin/bash
# Block direct GitHub CLI merge and enforce proper merge workflow (Plan #115)
# Also blocks ANY worktree deletion commands from inside worktrees
# Also blocks direct script calls that bypass make targets
#
# Rules:
# 1. No direct GitHub merge CLI - must use make merge/finish
# 2. No direct python scripts/safe_worktree_remove.py - must use make worktree-remove
# 3. No direct python scripts/finish_pr.py - must use make finish
# 4. No direct python scripts/merge_pr.py - must use make merge/finish
# 5. No merge/finish/worktree-remove from inside a worktree
# 6. Must cd to main FIRST (separate command), then run finish
#
# Exit codes:
#   0 - Allow the operation
#   2 - Block the operation

set -e

# Read the tool input from stdin
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [[ -z "$COMMAND" ]]; then
    exit 0  # No command, allow
fi

# Check if command contains direct GitHub CLI merge
if echo "$COMMAND" | grep -qE 'gh\s+pr\s+merge'; then
    PR_NUM=$(echo "$COMMAND" | grep -oE 'merge\s+[0-9]+' | grep -oE '[0-9]+' || echo "N")

    echo "BLOCKED: Direct GitHub CLI merge is not allowed" >&2
    echo "" >&2
    echo "This bypasses worktree auto-cleanup - orphan worktrees will accumulate." >&2
    echo "" >&2
    echo "Use the proper command instead:" >&2
    echo "  make merge PR=$PR_NUM" >&2
    exit 2
fi

# Block direct calls to safe_worktree_remove.py (must use make worktree-remove)
# This ensures the latest version from main is always used, not a stale worktree copy
# Pattern: matches command starting with or containing '&& python' or '; python' before the script
if echo "$COMMAND" | grep -qE '(^|&&|;|\|)\s*python[3]?\s+scripts/safe_worktree_remove\.py'; then
    WORKTREE=$(echo "$COMMAND" | grep -oE 'worktrees/[^ ]+' || echo "BRANCH")
    BRANCH=$(basename "$WORKTREE" 2>/dev/null || echo "BRANCH")

    echo "BLOCKED: Direct script call is not allowed" >&2
    echo "" >&2
    echo "Running 'python scripts/safe_worktree_remove.py' directly may use a stale" >&2
    echo "copy of the script from your worktree instead of the latest from main." >&2
    echo "" >&2
    echo "Use the proper command instead:" >&2
    echo "  make worktree-remove BRANCH=$BRANCH" >&2
    exit 2
fi

# Block direct calls to finish_pr.py (must use make finish)
# This ensures proper workflow and uses main's scripts
if echo "$COMMAND" | grep -qE '(^|&&|;|\|)\s*python[3]?\s+scripts/finish_pr\.py'; then
    BRANCH=$(echo "$COMMAND" | grep -oE '\-\-branch\s+\S+' | sed 's/--branch\s*//' || echo "BRANCH")
    PR_NUM=$(echo "$COMMAND" | grep -oE '\-\-pr\s+[0-9]+' | grep -oE '[0-9]+' || echo "N")

    echo "BLOCKED: Direct script call is not allowed" >&2
    echo "" >&2
    echo "Running 'python scripts/finish_pr.py' directly may use a stale" >&2
    echo "copy of the script from your worktree instead of the latest from main." >&2
    echo "" >&2
    echo "Use the proper command instead:" >&2
    echo "  make finish BRANCH=$BRANCH PR=$PR_NUM" >&2
    exit 2
fi

# Block direct calls to merge_pr.py (must use make merge or make finish)
# This script cleans up worktrees after merge, which can break shell CWD
# Also ensures we use main's version of the script, not a stale worktree copy
if echo "$COMMAND" | grep -qE '(^|&&|;|\|)\s*python[3]?\s+(scripts/)?merge_pr\.py'; then
    PR_NUM=$(echo "$COMMAND" | grep -oE '[0-9]+' | head -1 || echo "N")

    echo "BLOCKED: Direct script call is not allowed" >&2
    echo "" >&2
    echo "Running 'python scripts/merge_pr.py' directly may:" >&2
    echo "  - Use a stale copy from your worktree instead of main" >&2
    echo "  - Break your shell if CWD is in a worktree being cleaned up" >&2
    echo "" >&2
    echo "Use the proper command instead:" >&2
    echo "  make merge PR=$PR_NUM" >&2
    echo "Or for full workflow (from main):" >&2
    echo "  make finish BRANCH=<branch> PR=$PR_NUM" >&2
    exit 2
fi

# Get the working directory from the tool input
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Check if CWD is inside a worktree
if [[ "$CWD" == */worktrees/* ]]; then
    # Extract main directory and branch info for error messages
    MAIN_DIR=$(echo "$CWD" | sed 's|/worktrees/.*||')
    BRANCH=$(basename "$CWD")

    # Block ANY worktree deletion command from inside a worktree
    # This includes: make finish, make worktree-remove, safe_worktree_remove.py
    # Skip git commands (they can't delete worktrees - that's caught by block-worktree-remove.sh)
    # This avoids false positives from commit messages containing these words
    if ! echo "$COMMAND" | grep -qE '^git\s' && echo "$COMMAND" | grep -qE '(^|&&|;|\|)\s*(make\s+(finish|worktree-remove)|python.*safe_worktree_remove)'; then
        # Extract PR number if present
        PR_NUM=$(echo "$COMMAND" | grep -oE 'PR=[0-9]+' | grep -oE '[0-9]+' || echo "")

        # Build the finish command
        if [[ -n "$PR_NUM" ]]; then
            FINISH_CMD="make finish BRANCH=$BRANCH PR=$PR_NUM"
        else
            FINISH_CMD="make finish BRANCH=$BRANCH PR=<PR_NUMBER>"
        fi

        # Save pending command to file for easy execution after cd
        # The script includes a CWD check to prevent the "cd X && bash script.sh" bypass
        PENDING_FILE="$MAIN_DIR/.claude/pending-finish.sh"
        mkdir -p "$MAIN_DIR/.claude"
        cat > "$PENDING_FILE" << 'SCRIPT_EOF'
#!/bin/bash
# Auto-generated by enforce-make-merge.sh
# IMPORTANT: Run this AFTER 'cd' to main (as a SEPARATE command, not with &&)

# CWD safety check: Ensure we're actually in main, not a worktree
# This catches the "cd X && bash script.sh" pattern where the subshell cd
# doesn't change the parent shell's CWD
if [[ "$PWD" == */worktrees/* ]]; then
    echo "═══════════════════════════════════════════════════════════════" >&2
    echo "ERROR: Still in a worktree! The 'cd' didn't work." >&2
    echo "═══════════════════════════════════════════════════════════════" >&2
    echo "" >&2
    echo "You probably ran: cd /path/to/main && bash .claude/pending-finish.sh" >&2
    echo "" >&2
    echo "This doesn't work because 'cd' in '&&' runs in a subshell," >&2
    echo "so your shell's working directory stays in the worktree." >&2
    echo "" >&2
    echo "Run these as TWO SEPARATE commands:" >&2
    echo "" >&2
    echo "  cd <main-directory>" >&2
    echo "  bash .claude/pending-finish.sh" >&2
    echo "" >&2
    echo "═══════════════════════════════════════════════════════════════" >&2
    exit 1
fi

SCRIPT_EOF
        if [[ -n "$PR_NUM" ]]; then
            echo "$FINISH_CMD" >> "$PENDING_FILE"
        else
            echo "# TODO: Replace <PR_NUMBER> with actual PR number" >> "$PENDING_FILE"
            echo "$FINISH_CMD" >> "$PENDING_FILE"
        fi
        chmod +x "$PENDING_FILE"

        echo "═══════════════════════════════════════════════════════════════" >&2
        echo "BLOCKED: Cannot run this from inside a worktree!" >&2
        echo "═══════════════════════════════════════════════════════════════" >&2
        echo "" >&2
        echo "Your shell is in: $CWD" >&2
        echo "Deleting worktrees from here breaks your shell (CWD becomes invalid)." >&2
        echo "" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "DO THIS (two separate commands):" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "" >&2
        echo "  cd $MAIN_DIR" >&2
        echo "" >&2
        echo "  $FINISH_CMD" >&2
        echo "" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "Or after cd, run: bash .claude/pending-finish.sh" >&2
        echo "═══════════════════════════════════════════════════════════════" >&2
        exit 2
    fi

    # Block make merge from worktree (suggest finish from main)
    # Pattern includes optional -C flag: make -C /path merge
    if echo "$COMMAND" | grep -qE '(^|&&|\|\||;)\s*make\s+(-C\s+\S+\s+)?merge(\s|$)'; then
        PR_NUM=$(echo "$COMMAND" | grep -oE 'PR=[0-9]+' | grep -oE '[0-9]+' || echo "")

        if [[ -n "$PR_NUM" ]]; then
            FINISH_CMD="make finish BRANCH=$BRANCH PR=$PR_NUM"
        else
            FINISH_CMD="make finish BRANCH=$BRANCH PR=<PR_NUMBER>"
        fi

        # Save pending command to file for easy execution after cd
        # The script includes a CWD check to prevent the "cd X && bash script.sh" bypass
        PENDING_FILE="$MAIN_DIR/.claude/pending-finish.sh"
        mkdir -p "$MAIN_DIR/.claude"
        cat > "$PENDING_FILE" << 'SCRIPT_EOF'
#!/bin/bash
# Auto-generated by enforce-make-merge.sh
# IMPORTANT: Run this AFTER 'cd' to main (as a SEPARATE command, not with &&)

# CWD safety check: Ensure we're actually in main, not a worktree
# This catches the "cd X && bash script.sh" pattern where the subshell cd
# doesn't change the parent shell's CWD
if [[ "$PWD" == */worktrees/* ]]; then
    echo "═══════════════════════════════════════════════════════════════" >&2
    echo "ERROR: Still in a worktree! The 'cd' didn't work." >&2
    echo "═══════════════════════════════════════════════════════════════" >&2
    echo "" >&2
    echo "You probably ran: cd /path/to/main && bash .claude/pending-finish.sh" >&2
    echo "" >&2
    echo "This doesn't work because 'cd' in '&&' runs in a subshell," >&2
    echo "so your shell's working directory stays in the worktree." >&2
    echo "" >&2
    echo "Run these as TWO SEPARATE commands:" >&2
    echo "" >&2
    echo "  cd <main-directory>" >&2
    echo "  bash .claude/pending-finish.sh" >&2
    echo "" >&2
    echo "═══════════════════════════════════════════════════════════════" >&2
    exit 1
fi

SCRIPT_EOF
        echo "$FINISH_CMD" >> "$PENDING_FILE"
        chmod +x "$PENDING_FILE"

        echo "═══════════════════════════════════════════════════════════════" >&2
        echo "BLOCKED: Cannot run 'make merge' from inside a worktree" >&2
        echo "═══════════════════════════════════════════════════════════════" >&2
        echo "" >&2
        echo "Your shell is in: $CWD" >&2
        echo "Use 'make finish' from main for the complete workflow." >&2
        echo "" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "DO THIS (two separate commands):" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "" >&2
        echo "  cd $MAIN_DIR" >&2
        echo "" >&2
        echo "  $FINISH_CMD" >&2
        echo "" >&2
        echo "───────────────────────────────────────────────────────────────" >&2
        echo "Or after cd, run: bash .claude/pending-finish.sh" >&2
        echo "═══════════════════════════════════════════════════════════════" >&2
        exit 2
    fi
fi

exit 0
