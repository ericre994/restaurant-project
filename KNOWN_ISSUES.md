# Known Issues

Running list of things worth fixing, grouped by area. Low-friction by design: append a
one-liner in the same commit that discovers or introduces an issue. Promote an item to a
[GitHub issue](https://github.com/ericre994/restaurant-project/issues) once you're ready to
act on it (so a PR can `Fixes #N`), and check it off here when it lands.

Tags: `(blocker)` gates other work · `(correctness)` wrong behavior / data · `(low)` minor /
cleanup · `(decision)` needs a product/technical call before code · `(ux)` frontend / UX.
Triage: **fix now** items are the current batch; **fix later** items are parked.

Design docs are the source of truth — where an item mirrors a documented open question, the
reference is noted so the two stay in sync.

---

## Backend

- [ ] **No Postgres-specialized migration yet.** The initial Alembic migration is DB-agnostic
  (JSON `embedding`, B-tree lat/lng). The Postgres follow-up — pgvector + `geography`/GIST
  radius + GIN cuisine index — is unwritten and blocked on the embedding dimension `N`. (blocker)
  — TDD §5.2
- [ ] **JSON-column in-place mutation doesn't persist.** SQLAlchemy doesn't track in-place
  edits to JSON columns; updates must reassign a new object (`log.user_feedback = {...}`).
  Audit every JSON-column write (`recommendation_logs.user_feedback`, `attributes`, etc.) for
  this footgun. (correctness) — CLAUDE.md
- [ ] **Local accounts shipped; dev bypass + external-provider decision remain.** Real
  email/password accounts now back the product goal (each person's lists are their own):
  `POST /auth/signup` / `/auth/login` issue an opaque bearer-token session, passwords are
  PBKDF2-hashed (`app/security.py`, `routers/auth.py`), and the dev UI has a login gate that
  persists the token. Still open: (a) the `X-User-Id` dev bypass in `deps.get_current_user`
  should be gated behind a dev flag or removed for production; (b) whether to adopt a managed
  external provider (OAuth / social login) vs. keep local passwords. (decision) — TDD §9
- [ ] **`token_usage` / `cost_estimate` always null** in `recommendation_logs` — stay null
  until the prototype surfaces LLM usage. (low)
_Both **fix now** backend items shipped — see **Done** below._

## Prototype / Recommender

- [ ] **`_sql_retrieve` tie-ordering** can differ from the prototype's `retrieve()` among exact
  `rating` + `rating_count` ties. Verified to return the same candidate *set*; confirm the
  order difference is harmless downstream. (low) — CLAUDE.md
- [ ] **Real Anthropic API not yet exercised** end-to-end. The LLM ranking path is validated
  offline only (`FAKE_LLM`); JSON-reliability failure rate against the live API is unmeasured.
  (correctness) — PRD §3, TDD §9

## Data pipeline

- [ ] **No NYC data in the seed.** The Yelp Open Dataset has no NYC coverage, but NYC is the
  PRD launch market. Philadelphia is the stand-in. Resolving this depends on the production
  data-provider decision below. (blocker) — CLAUDE.md, PRD
- [ ] **Yelp dataset is academic-use only** — fine for local dev, cannot ship to production.
  Superseded once the production provider lands. (blocker) — CLAUDE.md, `YelpData/docs/`

## Frontend / UX

### Fix now
_All shipped — see **Done** below._

### Fix later
- [ ] **Map feature.** Show restaurant locations on a map. (ux)
- [ ] **Popup / modal boxes for fill-in sections.** Move inline fill-in fields into modals. (ux)
- [ ] **UI update for the create-new-list flow.** (ux)

> Two more items you wrote down landed in **Backend** because they're data-model / validation
> changes, not just UI: *notes & tags belong to the restaurant* and *reject future-dated
> visits* (both **fix now**). *Unique users / logins* is folded into the **Auth is a dev stub**
> item (fix later).

## Open decisions (block real migrations / launch)

- [ ] **Production data provider** — Google Places vs. Yelp Fusion (coverage, ToS, unit
  economics). Blocks NYC data and production readiness. (decision) — PRD Q1, TDD §9
- [ ] **Embedding model & dimension `N`** — pick the model and fix `N` before the pgvector
  migration. Until then `embedding` stays null and Stage 1 pre-ranks by rating. (decision)
  — TDD §9
- [ ] **Client platform** — native mobile vs. cross-platform. No client app exists yet.
  (decision) — TDD §9
- [ ] **Cold-start taste profile** — explicit quiz, import from Google Maps saves, or both.
  (decision) — PRD Q2
- [ ] **Availability polling & ToS** — is there a compliant Resy/OpenTable availability source
  pre-partnership, and at what cadence? Gates the alerts feature. (decision) — PRD Q3, TDD §9
- [ ] **"Visited" auto-detect** — location-based (with consent) vs. fully manual in MVP.
  (decision) — PRD Q4
- [ ] **Monetization direction** — subscription / booking referral / defer. Affects roadmap
  sequencing. (decision) — PRD Q5

---

## Done

<!-- Move checked items here with the PR number, e.g.:
- [x] Short description — #12
-->

### Frontend / UX — fix-now batch (dev harness `backend/app/static/index.html`)
- [x] **Restaurant detail view.** Click a restaurant name (lookup or a list) to open a modal
  with address (+ Google Maps link), cuisine chips, formatted hours (today highlighted), and
  feature chips. `attributes` exposed on `RestaurantOut`; `GET /restaurants/{id}` serves it.
- [x] **Clear-search option.** "Clear" button resets name/cuisine/price and results.
- [x] **Better add-to want-to-try vs. visited.** Replaced the catch-all "Add to…" dropdown with
  a one-click **＋ Want to Try** toggle + **Log visit** (→ Visited) + a compact custom-list picker.
- [x] **Fuzzy search on Find Restaurants.** `GET /restaurants?q=` falls back to typo-tolerant
  matching (prefix bonus + `SequenceMatcher` ratio) when exact substring underfills. `fuzzy=false`
  opts out. Covered by `tests/test_restaurants.py`.
- [x] **More sort options in My Lists.** Sort dropdown: recently added / name / price / rating / tag.
- [x] **Cuisine search bar rework.** Typeahead backed by a new `GET /restaurants/cuisines`
  (distinct categories + counts); picking a suggestion searches immediately.

### Backend — fix-now batch
- [x] **Notes & tags belong to the restaurant, not the list item.** New `restaurant_notes` table
  (one row per user+restaurant); note/tags follow a restaurant across every list. `/lists/{id}/items`
  write-through + hydrate; direct `GET|PUT /restaurants/{id}/note`; `list_items.source` stays
  per-save. Migration `a1b2c3d4e5f6` backfills (union tags, first non-empty note) then drops the
  old columns; upgrade+downgrade exercised. Covered by `tests/test_restaurant_notes.py`.
- [x] **Reject future-dated visits.** `POST /visits` 422s a `visited_at` dated after today (UTC,
  compared by calendar date so earlier-today still passes); the log-visit modal sets the date
  picker's `max` to today. Covered by `tests/test_visit_validation.py`.
- [x] **TDD schema drift folded in.** TDD §5.1 now documents `restaurant_notes`, `list_items.source`,
  and `visits.sentiment` (dropped the moved-out `list_items.tags`); §6 lists the `/restaurants/{id}/note`
  + `/restaurants/cuisines` endpoints; bumped to v0.4.

### Follow-up bug fixes (found while testing the batch)
- [x] **Price filter didn't apply until Search was re-clicked** — #13. The cuisine input auto-searched
  on `change` but the price `<select>` had no handler, so picking a price did nothing. Added a matching
  `change` listener; the filter now applies live. (Backend `price_max` was correct all along.)
- [x] **Maps link opened raw coordinates, not the restaurant** — #14. "Open in Maps" used
  `?query=lat,lng` (bare pin / nearest-business reverse-geocode). Now searches name + address biased to
  the coordinates (`/maps/search/<name, address>/@lat,lng,16z`): a listed restaurant opens straight to
  its business card, an unlisted one still centers on the right block instead of scattering region-wide.
