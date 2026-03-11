You are running inside GitHub Actions for the fork of the `OpenPlanter` repository.

Your job is to sync the fork with upstream and rebase active fork branches on top of the latest upstream main branch.

Repository layout:
- `origin` is the fork: `ThomsenDrake/OpenPlanter`
- `upstream` is the source repo: `ShinMegamiBoson/OpenPlanter`

Constraints:
- Operate only on refs that have already been fetched locally.
- Do not run network commands.
- Do not edit product code, docs, or workflow files.
- Do not add untracked files.
- Only manipulate git branches and commits.
- Leave the repository on the local `main` branch with a clean working tree and no staged changes.

Required outcome:
1. If `origin/main` already matches `upstream/main`, make no changes and say so.
2. Otherwise, move local `main` to exactly `upstream/main`.
3. For every fork branch that exists as `origin/chore/*`:
   - Create or refresh a matching local `chore/*` branch from the remote branch.
   - Determine whether it has commits not already contained in `upstream/main`.
   - If it has unique commits, rebase those commits onto `upstream/main`.
   - If it is already fully contained in `upstream/main`, leave it alone.
4. If any rebase hits conflicts, stop immediately and report the branch name plus the conflicting files.

Guidance:
- Because this is a clean CI checkout, it is acceptable to force local branch pointers when needed.
- Favor deterministic git commands over exploratory edits.
- Keep a short summary of what you changed, including branch names and resulting commit SHAs.
