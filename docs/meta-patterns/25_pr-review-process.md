# Pattern: PR Review Process

How code reviews work in this codebase.

## Why Reviews Matter

Reviews catch issues that CI cannot:
- Design problems
- Unclear code structure
- Missing edge cases
- Accidental complexity

## Who Reviews

**CC instances can review each other's PRs.** No human bottleneck required, though humans can review too.

**Review your own work only for trivial changes** (< 20 lines, no src/ changes, no new files).

## Review Assignment

There's no formal assignment. Reviews happen opportunistically:

1. **On session start**, check for unreviewed PRs:
   ```bash
   gh pr list --json number,reviews --jq '.[] | select(.reviews | length == 0)'
   ```

2. **Review PRs you didn't author** (check git log for author)

3. **Review within 24 hours** - stale PRs block progress

## Review Checklist

Use this checklist when reviewing. Copy to your review comment.

### Code Quality
- [ ] No `except:` or `except Exception:` without `# exception-ok:` comment
- [ ] No hardcoded values that should be in config
- [ ] No TODO/FIXME without issue link
- [ ] Functions over 50 lines have clear structure or justification

### Testing
- [ ] New code paths have tests
- [ ] Tests cover error paths, not just happy path
- [ ] No `# mock-ok:` without clear justification

### Security
- [ ] No secrets/credentials in code
- [ ] User input validated before use
- [ ] No SQL/command string concatenation

### Documentation
- [ ] Public functions have docstrings (or clear self-documenting names)
- [ ] Complex logic has inline comments
- [ ] Docs updated if behavior changed

## When to Reject

Request changes if:
- Silent exception swallowing (`except: pass`)
- Tests only check happy path for risky code
- Magic numbers without config
- Missing error handling on external calls

## When to Approve

Approve if:
- All checklist items pass (or have documented exceptions)
- CI passes
- Implementation matches plan intent

## How to Review

```bash
# View diff
gh pr diff 123

# Checkout locally to test
gh pr checkout 123

# Submit review
gh pr review 123 --approve --body "Checklist verified."
gh pr review 123 --request-changes --body "Issue: [describe]"
```

## Branch Protection

GitHub branch protection requires:
- 1 approved review before merge
- All CI checks passing

Direct pushes to main are blocked.

## Review Examples

### Good Review Comment (Approve)

```
Checklist verified:
- [x] Code quality items pass
- [x] Tests cover both success and error paths
- [x] No security concerns
- [x] Docs updated

LGTM!
```

### Good Review Comment (Request Changes)

```
Found an issue:

**Problem:** Line 42 has `except:` without justification
**Suggestion:** Either add `# exception-ok: reason` or catch specific exception

Once fixed, happy to approve.
```

### Bad Review Comment

```
Looks good to me
```

(Why bad: No evidence that checklist was reviewed)

## Related

- CLAUDE.md "Cross-Instance Review" section
- `.github/pull_request_template.md`
