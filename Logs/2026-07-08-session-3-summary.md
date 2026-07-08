# Session Summary — 2026-07-08 (session 3)

Focus: clear the entire **fix-now** batch from `KNOWN_ISSUES.md` (frontend + backend),
fix two bugs found while testing, and keep the trackers and design docs in sync.
Shipped as seven PRs (#10, #12, #13, #14, #15, #16), all squash-merged to `master`.
Dev DB re-seeded to match the new schema.

---

## 1. Frontend/UX fix-now batch — PR #10 (`85b2c59`)

Implemented all six fix-now Frontend/UX items in the dev harness (`backend/app/static/index.html`)
plus the backend endpoints they needed:

- **Restaurant detail view** — click a name (lookup or a list) → modal with address +
  Google Maps link, cuisine chips, formatted hours (today highlighted), feature chips.
  Exposed `attributes` on `RestaurantOut`.
- **Fuzzy name search** — `GET /restaurants?q=` falls back to typo-tolerant matching
  (word-prefix bonus + `SequenceMatcher` ratio) when exact substring underfills; `fuzzy=false`
  opts out.
- **Cuisine typeahead** — new `GET /restaurants/cuisines` (distinct cuisines + counts).
- **Cleaner add flow** — replaced the catch-all "Add to…" dropdown with a one-click
  Want-to-Try toggle + Log visit + a custom-list picker.
- **Clear-search** control; **My Lists sort** dropdown (added/name/price/rating/tag);
  search query persists across re-renders.
- Tests: `tests/test_restaurants.py`. Documented `python -m uvicorn` in `CLAUDE.md`
  (the `uvicorn` console script isn't on PATH here).

## 2. Backend fix-now — PR #12 (`61b98db`)

- **Notes & tags moved to a per-restaurant record.** New `restaurant_notes` table (one row
  per user+restaurant); note/tags follow a restaurant across every list. `list_items` lost
  note/tags (kept `source`, which is per-save). `/lists/{id}/items` still accepts/returns
  note/tags (write-through + hydration); also editable directly via `GET|PUT /restaurants/{id}/note`.
  **Migration `a1b2c3d4e5f6`** backfills (union tags, first non-empty note wins) then drops the
  old columns — exercised upgrade **and** downgrade on a seeded temp DB.
- **Reject future-dated visits.** `POST /visits` 422s a `visited_at` after today (compared by
  calendar date, so earlier-today still passes); modal caps the date picker at today.
- Collapsed a duplicate `get_restaurant` handler that had slipped into #10.
- Tests: `tests/test_restaurant_notes.py`, `tests/test_visit_validation.py`. TDD §5.1/§6 updated
  to v0.4. Full suite: **52 passed.**

## 3. Merge mechanics (worth remembering)

- #11 was authored **stacked on** the #10 branch. Merging #10 with `--delete-branch` **closed**
  #11 (GitHub closes, not retargets, when the base branch is deleted) and left its branch carrying
  #10's now-squashed commits.
- Fix: `git rebase --onto origin/master <old-#10-tip> <branch>` to drop the redundant commits,
  force-push, and open a fresh PR (#12) to `master`. Clean, no conflicts.
- The repo **requires branches be up to date before merging** and runs a CI `test` job (~30s),
  so a second independent PR often needs a rebase-onto-master + wait-for-CI before it will merge
  (hit this on #14). Squash-merge is the repo convention (`(#N)` suffix).

## 4. Two bugs found while testing

- **Price filter didn't apply on change — PR #13 (`317a2f1`).** The cuisine input auto-searched on
  `change` but the price `<select>` had no handler, so picking a price did nothing until Search was
  re-clicked. Added a matching `change` listener. (Backend `price_max` was correct all along.)
- **Maps link opened raw coordinates — PR #14 (`615ac70`).** `?query=lat,lng` dropped a bare pin /
  reverse-geocoded to the nearest business. First tried `?query=name,address` — but for an unlisted
  spot (food truck) Google scattered across the whole region. Final: **name + address biased to the
  coordinates** (`/maps/search/<name, address>/@lat,lng,16z`) — a listed restaurant opens straight
  to its business card, an unlisted one still centers on the right block. Verified both live.

## 5. Docs kept in sync

- **PR #15 (`7ef334d`)** — logged #13 + #14 in `KNOWN_ISSUES.md` Done.
- **PR #16 (`2a8ed00`)** — PRD → v0.4 and TDD prose updated: implementation-status now reflects
  per-restaurant notes/tags, future-visit rejection, and a new Restaurant discovery/browse row
  (fuzzy search, cuisine typeahead, price filter, detail view); §4.1 clarifies notes/tags belong to
  the restaurant while `source` is per-save. Closed the "TDD schema drift" tracker item.

## 6. Dev DB re-seeded

`rm app.db && python -m app.seed` — rebuilt from the current `models.py` (no vestigial
`list_items.note/tags`; `restaurant_notes` present), 5,856 Philadelphia restaurants + the dev user.
The old columns were harmless (ORM ignored them) but the reset gives a pristine local file.
Note: `python -m app.seed` alone is idempotent and would **not** have cleaned them — it skips the
load when the table is non-empty and `create_all` never drops columns.

## State at session end

- `master` history: … #9 → #10 → #12 → #13 → #14 → #15 → #16. All CI-green, branches pruned.
- Full backend suite: **52 passed.** Dev server left running at http://127.0.0.1:8000/app/.
- **The entire fix-now batch (frontend + backend) is done.** Remaining `KNOWN_ISSUES.md` work is all
  parked: blockers (Postgres/pgvector migration, NYC data + production provider), open product/tech
  decisions, and fix-later UX (map view, modal fill-ins, create-list redesign). Auth is still a dev
  `X-User-Id` stub.
