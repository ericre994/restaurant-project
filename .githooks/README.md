# Git hooks

Project hooks kept in-repo so they're shared and reviewable. `.git/hooks/` is
not tracked, so hooks are inactive until you point git at this directory:

```bash
git config core.hooksPath .githooks
```

## pre-push

Blocks direct pushes to `master`, nudging changes through pull requests (where
CI runs). It is a **local safety net, not server-side enforcement** — it only
applies in clones that ran the command above, and is bypassable with
`git push --no-verify`.

Real, unbypassable protection is a GitHub branch ruleset, which requires the
repository to be public or on a paid plan (Pro). See the project history for
why that wasn't enabled.
