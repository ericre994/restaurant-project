# Session Summary — 2026-07-14 (session 5)

Focus: clear the **fix-now UX/bug backlog** logged at the end of session 4, then act on two
new user-driven feature lists. Everything shipped in **one squash-merged PR (#25)** to `master`.
Backend suite: **91 passed** (80 → 91). All frontend work is in the dev harness
(`backend/app/static/index.html`); several items also touched the backend.

Working style this session: the user fed requirements incrementally and made product calls when
asked (notably the hours-labeling and the identity-model questions). I verified frontend changes
by driving the running server with **headless Chrome** (dump-DOM + screenshots) since the
browser-extension MCP wasn't connected.

---

## Batch #1 — original fix-now UX/bugs (8 items)

All in `index.html`:
- **Name persists after logout (bug).** Root cause was CSS: `nav`/`.who` `display:flex` overrode
  the `[hidden]` attribute (author display beats the UA rule), so the chrome never hid. Fix:
  `nav[hidden], .who[hidden] { display: none }` + clear the label in `setChrome`. *(This same
  hidden-attr footgun recurred twice more this session — see below.)*
- **Hours "12:00 AM – 12:00 AM" (bug).** The Yelp seed encodes both a closed day and a 24-hour day
  as `0:0-0:0`. Product call (user chose the contextual heuristic): all-zero week → **"Open 24
  hours"** (Wawa/McDonald's/diners — 102 in seed), a lone zero-day among real hours → **"Closed"**
  (the "closed Mondays" pattern — 653/666). Tagged **`YELP_SEED_HOURS`** in code + `KNOWN_ISSUES`
  to delete when the real provider lands.
- **Want-to-Try shown on Visited (bug).** `wantButton` returns null when visited (both call sites
  guard); "Log another visit" is the action.
- **Rolling live search.** Debounced (300 ms) input; Enter cancels the pending call; a request-seq
  guard stops a slow response overwriting a newer one.
- **Past visit logs surfaced** in the detail modal (reads already-loaded `visitsByRestaurant`).
- **Recommendations tab** — new nav route calling `POST /recommendations`, renders ranked picks +
  match % + reasons.
- **Create-user flow & inviting front page** — redesigned split landing (hero + feature bullets)
  and a signup form with confirm-password, show-password, and inline validation.

## Batch #2 — accounts identity + more (4 items)

- **Mandatory name + unique @username.** Product call (user chose "name + separate @username"):
  signup now requires first name, last name, and a unique `@username` (3–30 chars, case-insensitive);
  **login stays by email**; display name = first name. Backend: new `users.username`/`first_name`/
  `last_name` (`models.py`), `create_account` + `UsernameTaken` (`services.py`), `SignupRequest`/
  `UserOut` (`schemas.py`), `routers/auth.py` validation, migration **`c3d4e5f6a7b8`** (nullable so
  existing accounts stay valid; **upgrade+downgrade exercised**).
- **Edit/delete visits.** `PATCH`/`DELETE /visits/{id}` (owner-only, future-date guard); detail
  view's visit history gained per-visit Edit (reuses the visit modal) + Delete.
- **Add-to-list picker** shows every list with membership check-marks (`loadCore` now builds
  `listMembership`); replaced the custom-only dropdown.
- **Unified search + advanced filters.** Backend: `/restaurants` gained `rating_min`, exact
  multi-select `price`, and repeatable (OR'd) `cuisine`. Hours filtered **client-side** (needs the
  user's local time + the hours JSON; validated the algorithm in Python, 9/9 cases).

## Batch #3 — polish (4 items) + follow-ups

- **Add-to-list closes on outside click** (global handler; Escape too); close-time reconcile only
  re-renders when membership actually changed.
- **Edit note/tags** moved from chained `prompt()` dialogs into a **modal**.
- **Create-new-list** redesigned: **＋ New list** button → titled modal (replaces the inline
  name+＋).
- **Two-column lookup**: search + filters sidebar (left), results (right). Filters live under a
  single **Advanced Filters** show/hide master toggle over titled facets *(after iterating: first
  per-filter `<details>`, then per the user's follow-up a single all-filters toggle labeled
  "▾ Advanced Filters")*. This toggle hit the **hidden-attr override bug a third time** —
  `.adv-filters[hidden]/.lookup-facets[hidden] { display: none }`.

## Docs

- **PRD + TDD → v0.5** (dated 2026-07-14): users table + signup (`username`/`first_name`/
  `last_name`, display = first name); `PATCH`/`DELETE /visits/{id}`; `/restaurants` filters;
  rewritten dev-UI paragraph (3 tabs, two-column lookup, modals, membership picker); migration note.
- Renamed `Design Docs/restaurant-app-prd_2.md` → `restaurant-app-prd.md` (via `git mv`; updated the
  one reference in `CLAUDE.md`).
- `KNOWN_ISSUES.md`: all four Done batches carry `— #25`; parked "price is a max" decision annotated
  as partially addressed (lookup now does exact multi-select; recommendations still `price_max`).

## Deferred to Fix later (recorded in KNOWN_ISSUES)

- Distinguish the search tool from the recommendation tool (they overlap) — needs a rethink.
- Geo-location for more accurate search (consent-gated, only if wanted).

## Ops / verification notes

- Frontend has no JS test runner and no Node in this env; verified via **headless Chrome** against
  the live server: `--dump-dom` to confirm JS parses/renders, and screenshots of each surface. For
  logged-in shots, used a temporary same-origin `_probe.html` in `static/` that set the token in
  `localStorage` then drove the page (deleted after).
- **Stale-server gotcha:** uvicorn runs without `--reload`, so backend `.py` edits need a restart to
  take effect (static `index.html` is served fresh per request and doesn't). Missed this once —
  filter params looked ignored until the restart.
- The dev `app.db` was **cleared and re-seeded** mid-session on request (`rm app.db && python -m
  app.seed`, 5,856 restaurants). The new account columns come from `create_all`/migration.

## TODO carried forward

- **`todo-research-google-maps-api`** (memory + `KNOWN_ISSUES`, planned **2026-07-15**): research
  Google Maps / Places API costing, setup, and integration — feeds the open "Production data
  provider" decision (Google Places vs. Yelp Fusion).

## State at session end

- `master` history: … #24 → **#25** (`aeea9a1`, squash). CI green (`test`); branch pruned; local
  `master` synced.
- Backend suite: **91 passed** (added `test_visit_edit.py`; username + filter cases).
- **All fix-now Frontend/UX items are now Done.** The dev harness is a genuinely usable three-tab
  app (accounts with names/username, faceted search, recommendations, lists with modals & visit
  editing).
- **Next up:** tomorrow's Google Maps API research; then the parked Fix-later items and
  external-connector work (production data provider → NYC data, pgvector/embeddings, managed auth)
  stay parked by design until the local prototype decision-gates clear.
