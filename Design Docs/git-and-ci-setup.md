# Git, GitHub & CI Setup — Summary

|                  |                                                                  |
| ---------------- | ---------------------------------------------------------------- |
| **Status**       | Done                                                             |
| **Last updated** | June 24, 2026                                                    |
| **Repository**   | https://github.com/ericre994/restaurant-project (public)         |
| **Default branch** | `master` (protected)                                           |

This document records the version-control and CI/CD work done for the project:
what was set up, why, and the operational consequences. It is a reference, not a
design proposal.

---

## 1. Repository initialization

The project started as a non-git directory. It was initialized as a local git
repo and pushed to GitHub.

- `git init` (default branch `master`).
- Git identity was already configured on the machine
  (`Eric Li <el2872@nyu.edu>`).
- Remote: `origin` → `https://github.com/ericre994/restaurant-project.git`.

## 2. Commit history

| Commit | Summary |
| ------ | ------- |
| `ae4ac1f` | Initial commit: design docs, Yelp pipeline, prototype, lists/recs backend |
| `ea9a77f` | Add `.gitattributes` to normalize line endings |
| `db0da02` | Add CI workflow: tests (3.9, both LLM modes) + line-ending lint |
| `1d92ff5` | Fix CI: make `import app` resolve under bare `pytest` |
| `a148ed5` | Add committed pre-push hook blocking direct pushes to `master` |
| `01c91e5` | Add top-level README with project overview and CI badge (#1, squash-merged) |

## 3. What is and isn't tracked

A root [`.gitignore`](../.gitignore) deliberately excludes the Yelp Open Dataset
and its derivatives, because it is **academic-use-only** (see `YelpData/`) and
large (~13 GB raw). These are regenerated locally via `YelpData/scripts/`.

Excluded:

- `YelpData/source/` (13 GB raw dataset), `YelpData/output/` (81 MB derived seed),
  `YelpData/logs/`, `YelpData/docs/` (Yelp ToS PDFs)
- `*.db` (the dev SQLite database, ~8.5 MB)
- `__pycache__/`, `.pytest_cache/`, virtualenvs
- `.claude/settings.local.json` (personal Claude Code overrides; the shareable
  config would be `settings.json`)

Tracked: all source (design docs, `prototype/`, `backend/`, `YelpData/scripts/`),
tests, READMEs, CI config, and git hooks.

## 4. Line-ending normalization

[`.gitattributes`](../.gitattributes) stops the "LF will be replaced by CRLF"
churn on Windows:

- `* text=auto eol=lf` — store LF in the repo, check out LF everywhere.
- `*.bat` / `*.cmd` → `eol=crlf` (correct for Windows batch scripts).
- Common binaries (`*.pdf`, `*.tar`, `*.zip`, `*.db`, images) marked `binary` so
  they are never line-ending–converted.

`git add --renormalize .` found no content changes — the repo already stored LF,
so this only prevents future checkout churn.

## 5. GitHub CLI & authentication

- The GitHub CLI (`gh`) was installed via `winget` (v2.95.0) at
  `C:\Program Files\GitHub CLI\gh.exe`. It may not be on older shells' `PATH`;
  a new terminal picks it up.
- The user authenticated interactively (`gh auth login`, account `ericre994`,
  HTTPS, token scopes incl. `repo`, `workflow`).

### Credential-helper workaround (important)

Git Credential Manager (`credential.helper = manager`) is **broken on this
machine** — its UI crashes with a `libSkiaSharp` load error, so plain `git`
operations against GitHub failed. Fix, scoped to github.com only:

```
git config --global --add credential.https://github.com.helper ""        # reset chain (skip GCM)
git config --global --add credential.https://github.com.helper \
  '!"C:/Program Files/GitHub CLI/gh.exe" auth git-credential'             # use gh's token
```

The empty first value resets the helper chain for github.com so GCM is skipped;
GCM remains the helper for any other host. After this, plain `git push` / `pull`
/ `fetch` work via gh's keyring token. To undo:
`git config --global --unset-all credential.https://github.com.helper`.

## 6. Continuous integration

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on push and PR to
`master`. Single job `test` on `ubuntu-latest`, **Python 3.9** (matches the
project's runtime contract — see `CLAUDE.md`):

1. **Line-ending lint** — fails if any tracked file has CRLF in the index
   (`git ls-files --eol | grep '^i/crlf'`), enforcing the `.gitattributes` policy.
2. `pip install -r backend/requirements.txt`.
3. **Run tests (fallback mode)** — `pytest` (29 tests).
4. **Run tests (FAKE_LLM mode)** — `FAKE_LLM=1 pytest`, exercising the LLM path
   offline.

### CI fix worth remembering

The first CI run failed with `ModuleNotFoundError: No module named 'app'`. Tests
import the `app` package, which worked locally only because we ran
`python -m pytest` (adds cwd to `sys.path`); bare `pytest` in CI does not. Fixed
with [`backend/conftest.py`](../backend/conftest.py), which puts `backend/` on
`sys.path` for any invocation/version (the `pythonpath` ini option needs
pytest ≥ 7; the local toolchain is 6.2.4). `backend/pytest.ini` pins `testpaths`.

## 7. Branch protection on `master`

Protection was the goal; the path to it had a constraint.

- **Classic branch protection and rulesets both require GitHub Pro for *private*
  repos** (HTTP 403: "Upgrade to GitHub Pro or make this repository public").
- The repo was made **public** (`gh repo edit --visibility public`), after
  confirming nothing sensitive is exposed (Yelp data, dev DB, and local settings
  are gitignored; no secrets in code).
- A **repository ruleset** ("Protect master", id `18095142`, `enforcement: active`,
  `bypass_actors: []`) was then created on `refs/heads/master`:
  - require a **pull request** (0 approvals → self-merge allowed)
  - require the **`test`** status check (strict / up-to-date)
  - block **force-pushes** (`non_fast_forward`) and **branch deletion**

Verified: a direct `git push --no-verify origin master` was rejected server-side
with *"Required status check 'test' is expected … push declined due to repository
rule violations."* This applies to everyone, including admins, and cannot be
bypassed.

> Note: the gh API call to create the ruleset must pass the JSON body via
> `--input <file>`; piping a here-string through PowerShell mangles it (HTTP 400).

## 8. Local pre-push hook

A second, client-side safety net for fast feedback before a push leaves the
machine. Kept in-repo so it's shared and reviewable:

- [`.githooks/pre-push`](../.githooks/pre-push) — refuses direct pushes to
  `master`; allows feature branches.
- Enabled per-clone with `git config core.hooksPath .githooks` (already set in
  this clone).
- **Bypassable** with `git push --no-verify`, and only active in clones that ran
  the config command — so it's a convenience, not enforcement. The unbypassable
  guarantee is the server-side ruleset (§7).

## 9. Verified end-to-end flow (PR #1)

The full protected flow was demonstrated, not assumed:

1. Direct push to `master` → blocked (local hook **and** server ruleset).
2. Feature branch `chore/repo-readme` pushed → allowed.
3. PR #1 opened → CI auto-ran the `test` job → **success**.
4. PR became `MERGEABLE` / `CLEAN` only because the required check passed.
5. **Squash-merged** (`01c91e5`), remote branch auto-deleted, local synced.

## 10. Working agreement going forward

Direct pushes to `master` are blocked. Normal flow:

```bash
git checkout -b <branch>
# commit work
git push origin <branch>      # local hook allows non-master
gh pr create                  # CI runs on the PR
# merge once the `test` check is green
```

Emergency local bypass (does **not** bypass the server ruleset):
`git push --no-verify`.

## 11. Follow-ups / known issues

- **Git Credential Manager is broken** on this machine (`libSkiaSharp`). Worked
  around for github.com only (§5); raw `git` against other hosts may still fail.
- GitHub Actions emits a cosmetic **Node 20 deprecation** warning for
  `actions/checkout@v4` / `actions/setup-python@v5`; auto-handled by the runner.
- `gh` is not on the default shell `PATH`; use the full path or a fresh terminal.
- Repo is **public** — design docs (PRD/TDD) are world-readable. Revert with
  `gh repo edit --visibility private` (this also disables the ruleset unless on
  Pro).
