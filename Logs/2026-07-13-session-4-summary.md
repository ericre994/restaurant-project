# Session Summary — 2026-07-13 (session 4)

Focus: push the **local prototype toward ~80% functional before engaging any external
connectors** (a sequencing decision made this session). Shipped six PRs (#18–#23), all
squash-merged to `master` in order. The recommendation framework got real teeth and the app
got real user accounts. Backend suite: **80 passed** (52 → 80).

Direction: the local prototype comes first — get lists, the recommendation loop, and accounts
working locally before paying the cost/ToS/integration surface of external providers (data
provider, Resy, geocoding, managed auth). Recorded in memory (`local-prototype-before-connectors`,
`auth-local-accounts`).

---

## 1. Personalized offline ranker — PR #18 (`29d67a7`)

The offline path (no `ANTHROPIC_API_KEY`) was a plain rating sort that ignored the diner — so
everyone got the same list. Replaced `_fallback()` with a deterministic **personalized ranker**
(`_score_candidate` + `_heuristic_rank` in `prototype/recommend.py`): a weighted blend of
cuisine-weight fit + query keyword/feature match + price comfort + distance + volume-shrunk
rating, emitting real 0–100 `match_score`s and short reasons. Mode reported as `heuristic (...)`.
Verified on the real seed (date_night → Italian, cheap_eats → Chinese). +6 tests.

## 2. ZIP / neighborhood resolution — PR #19 (`f7835e7`)

`near` accepted only 7 hardcoded landmarks. Now it resolves **any ZIP or neighborhood centroid
derived from the seed** — a `GeoIndex` (`zip_of`, `build_geo_index`, `geo_index_from_seed`):
~56 ZIPs + ~28 named neighborhoods (coords from the data, not hardcoded), fuzzy-matched, unknowns
reported. Backend resolves against a DB-derived index. Regression test: derived centroids
reproduce all 7 old landmarks within **1 km** (0.04–0.70 actual). +10 tests.

## 3. Deterministic retrieval + JSON guard — PR #20 (`351ab32`)

- **Tie-ordering:** both `retrieve()` and `_sql_retrieve` now pre-rank rating → volume → `id`,
  so order is reproducible and the two paths match **exactly** (verified end-to-end on the full
  5,856-row seed). Upgraded the CLAUDE.md invariant from "same set" to exact parity.
- **JSON-mutation footgun:** audited all four JSON write paths (all reassign; all already guarded
  by update-then-fresh-read tests) + added an explicit named guard.
- Fixed a latent bug: `recommender._resolve_location` annotated `Tuple` without importing it.
- +3 tests.

## 4. Local user accounts — PR #21 (`4c85ebb`)

Real email/password accounts so each person owns their lists and resumes next visit.
- `security.py`: **PBKDF2-HMAC-SHA256** hashing + opaque tokens (stdlib — no passlib/JWT).
- `models`: `User.password_hash` + a `sessions` table. Services: create_account / authenticate /
  start_session / user_for_token / end_session (30-day sessions).
- `routers/auth.py`: `POST /auth/{signup,login,logout}`.
- `deps.get_current_user` precedence: **Bearer token → account**; else `X-User-Id` (DEV-ONLY
  bypass, kept so the suite/harness pass); else the fixed dev user.
- Dev UI: a **login / sign-up gate**; token persisted in `localStorage`.
- Migration `b2c3d4e5f6a7` (add `password_hash` + `sessions`); **upgrade and downgrade verified**.
- +9 tests. Verified e2e through the real ASGI app: signup → save a list → reopen with the stored
  token → **list restored** → logout → token rejected.

## 5. Docs sync — PR #22 (`d463212`)

PRD + TDD brought in line with all four features: TDD §5.1 gains `users.password_hash` + a
`sessions` table; §6 lists `/auth/*`; §7.2 updated (PBKDF2, not "no password storage"); §4.1.2 +
status boxes describe the personalized fallback, neighborhood resolution, and deterministic order;
§9 + Assumptions auth rows reworded (local accounts done, managed provider still open). PRD §1.4
gains a User-accounts row; §4.2 reliability reworded.

## 6. Backlog logged — PR #23 (`52a0ae1`)

Eleven items surfaced while using the app, captured in `KNOWN_ISSUES.md` (each with a file
pointer):
- **Frontend fix-now (8):** create-user flow & UI; **name persists after logout** (bug); more
  inviting front page; rolling/live search; **hours show "12am–12am" for closed days** (bug); can't
  view a restaurant's past visit logs; **Want-to-Try button on already-Visited restaurants** (bug);
  add a Recommendations tab.
- **Backend:** price filter is a max, not an exact selection (`$$$$` should return only `$$$$`) —
  a `(decision)`.
- **Recommender:** deprioritize chains & fast food unless explicitly requested.

## Merge mechanics (worth remembering)

- All six branched off `master` independently. Branch protection **requires branches be up to
  date** + a CI `test` job (~30s), so each was `gh pr update-branch`'d onto the new master (which
  re-ran the suite against the integrated state — a real cross-PR check), CI polled to green, then
  squash-merged in order #18 → #23.
- **One conflict:** #21 and #20 both edited `KNOWN_ISSUES.md`. Resolved locally by dropping the
  JSON-mutation open bullet (already moved to Done by #20) and keeping #21's new accounts item;
  full suite (**80**) green on the merged tree before pushing.

## Ops notes

- The existing dev `app.db` predated `password_hash`; `create_all` won't add a column to an
  existing table. Added it non-destructively via `ALTER TABLE users ADD COLUMN password_hash`
  (preserving the 5,856 seeded restaurants) rather than wiping the DB. For a clean setup elsewhere:
  `rm app.db && python -m app.seed`, or `alembic upgrade head` on an Alembic-managed DB.
- Ran the server + prototype, opened `/app/` in the browser to try the login gate, then stopped
  the server.

## State at session end

- `master` history: … #17 → **#18 → #19 → #20 → #21 → #22 → #23**. All CI-green, branches pruned.
- Backend suite: **80 passed.**
- The local prototype advanced substantially: **personalized offline recommendations**,
  **ZIP/neighborhood resolution**, **deterministic retrieval**, and **real user accounts** — with
  the PRD/TDD in sync.
- **Next up** is the fix-now UX/bug batch just logged in `KNOWN_ISSUES.md`: quick bugs
  (name-after-logout, hours "12am–12am", Want-to-Try-on-Visited, exact-price filter), then UX
  builds (rolling search, Recommendations tab, inviting front page, create-user flow), and the
  ranking change (deprioritize chains). External-connector work (production data provider, NYC,
  pgvector/embeddings, managed auth) stays parked by design.
