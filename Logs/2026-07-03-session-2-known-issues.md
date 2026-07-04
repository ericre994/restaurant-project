# Session Summary — 2026-07-03 (session 2)

Focus: stand up a lightweight **known-issues tracker** for the project and seed it
with both documented open questions and a batch of hand-written issues from the
user. No code changed; one new doc added to the repo root. **Nothing committed yet.**

---

## 1. Chose a tracking approach

Discussed how to track known issues on a solo, pre-production project. Landed on a
two-layer, low-friction approach:

- **`KNOWN_ISSUES.md`** at the repo root — the running scratch list, appended in the
  same commit that discovers/introduces an issue, grouped by area, diffable.
- **GitHub Issues** — promote an item there only when ready to act, so a PR can
  `Fixes #N` (slots into the existing PR-numbered workflow).

Rejected alternatives: pure GitHub Issues (too noisy for "might matter later"
notes), inline `# TODO`s alone (scatter, no overview), and a `## Known issues`
section inside the TDD (keeps the design doc as source of truth, not a bug list).

## 2. Created `KNOWN_ISSUES.md`

Scaffolded and seeded from `CLAUDE.md` "things easy to get wrong" + the PRD/TDD open
questions. Tag legend (`blocker` / `correctness` / `low` / `decision` / `ux`) and a
**fix now / fix later** triage convention. Sections: Backend, Prototype/Recommender,
Data pipeline, Frontend/UX, Open decisions, Done.

Seeded items include: no Postgres-specialized Alembic migration (blocked on
embedding dim `N`), the JSON in-place-mutation footgun, TDD schema drift
(`list_items.tags/source`, `visits.sentiment`), dev-stub auth, `_sql_retrieve`
tie-ordering, real Anthropic API unexercised, no NYC seed data, and the PRD/TDD
open decisions (data provider, embedding model, client platform, cold-start,
availability polling, visited auto-detect, monetization).

## 3. Added the user's 12 hand-written items

Split per the user's own **fix Now / fix in Future** buckets:

- **Frontend / UX — fix now:** restaurant detail view (hours/address/more), clear-
  search control, better want-to-try-vs-visited flow, fuzzy search on Find
  Restaurants, more My Lists sort options (price/tag), cuisine search rework.
- **Frontend / UX — fix later:** map feature, popup/modal fill-in boxes,
  create-new-list UI update.
- **Filed under Backend instead of UI** (data-model / validation, not cosmetic):
  *notes & tags should attach to the restaurant, not the list item where created*
  (needs a model change + migration) and *reject future-dated visits* (server-side
  validation + disable future dates in the modal) — both **fix now**.
- *Unique users / logins* folded into the existing **"Auth is a dev stub"** item
  (fix later) rather than duplicated.

## 4. Session-log convention (new, going forward)

Per user request: **write a session summary to `Logs/` at the end of each session.**
Saved as a durable preference so future sessions follow it. This file is the first
under the new convention. (Same-date sessions get a `-session-N-<topic>` suffix to
avoid clobbering.)

## 5. Committed & merged

- Branched `docs/known-issues-tracker`, committed `KNOWN_ISSUES.md` + this log,
  pushed, and opened **[PR #8](https://github.com/ericre994/restaurant-project/pull/8)**.
- CI green (`test` passed); **squash-merged to `master` as `27c324b`**, branch
  deleted, local `master` fast-forwarded. Docs-only change.

## Known follow-ups (not done this session)

- Optionally open a GitHub issue for the notes/tags-on-restaurant change (the most
  involved item — touches `models.py`, `list_items` schema, needs a migration).
- Optionally add a pointer to `KNOWN_ISSUES.md` from `README.md` / `CLAUDE.md` for
  discoverability.
