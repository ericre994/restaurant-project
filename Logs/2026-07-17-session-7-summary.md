# Session Summary — 2026-07-17 (session 7)

Focus: take the Google Places work from "scaffolded provider" all the way to a **functionally
complete, ToS-compliant Google-live-source foundation for the NYC launch market**. Started by
wiring the provider into the pipeline (session 6's carried-forward item), then — after the user
confirmed the direction — designed and built the four engineering phases of a Philly→NYC data
migration. Ended at **141 backend tests** (up from 103 at the start) across **three PRs (#28 → #29 → #30),
all merged into `master`** by the end of the session.

Working style: heavy on **decision-framing before code**. The user asked feasibility questions
("can I scrape Google to replicate the Yelp dataset for NYC?") and I answered with the ToS reality
(you can store `place_id` forever but only cache other content ~30 days), then used
`AskUserQuestion` to pin the actual intent (live production source, not an owned static corpus)
before writing anything. Cost/ToS facts came from the session-6 research (`google-maps-integration`
memo), not re-derived.

---

## The framing that shaped everything

- **"Scrape and replicate the Yelp Open Dataset for NYC" is not feasible with Google** — not a
  capability limit, a licensing one. Google's terms allow storing `place_id` indefinitely but cap
  caching of other Places content (~30 days). So an *owned static NYC corpus* (the Yelp-dataset
  model) is out; the compliant shape is `restaurants` as a **short-lived, refresh-on-read cache**.
- **User decision (via AskUserQuestion):** Google Places as the **live production source**, not a
  dev fixture and not an ownable corpus. Recorded in `nyc-google-live-source` memory; resolves the
  *default-source* axis of PRD Q1 / TDD §9.
- **Key reframe:** with a write-through cache, **no up-front bulk scrape is needed** — the cache
  fills lazily from real queries. The "replicate all of NYC" instinct is unnecessary for this model.
- **Field split** (permanent vs refreshable): only `place_id` + user data (lists/visits/notes/taste)
  are permanent; name/rating/price/hours/location/address/categories all carry the TTL. "Rarely
  changes" ≠ "permanent" — coordinates are still Content on the clock.

## What shipped (six commits, three stacked PRs)

**PR #28 — RECS_PROVIDER toggle** (`wire-google-provider-toggle`)
- `recommender._retrieve_candidates` dispatches Stage 1 on `RECS_PROVIDER` (`seed` default |
  `google`), resolved by `_resolve_provider` (arg > env > default). Google path **falls back to
  `_sql_retrieve` on any `GooglePlacesError`** — same reliability guarantee as the ranker's offline
  fallback. Cuisine folded into the text query (`_google_query`). `result.retrieval` +
  `recommendation_logs.context.retrieval` + the response body + the dev-UI header record the source.
  103 → 110 tests.

**PR #29 — restaurants TTL cache: write-through + refresh-on-read** (`google-write-through-cache`, Phases 0–2)
- **Phase 0:** `Restaurant.expires_at` (indexed) + `raw` columns (the two TDD §5.1 designed but the
  model lacked). Migration `d4e5f6a7b8c9`, verified up/down round-trip on SQLite.
- **Phase 1:** `app/cache.py::upsert_candidates` — insert-or-refresh by `(source='google_places',
  source_id=place_id)`, derive lat/lon/categories_text, retain `raw`, stamp `expires_at = now + TTL`
  (`RESTAURANT_CACHE_TTL_DAYS`, default 7), and **rewrite candidate id place_id → internal UUID**.
  This is what makes a Google pick *saveable* (proven end-to-end: recommend → save to Want-to-Try →
  201). Ephemeral before; FK to `restaurants.id` couldn't resolve.
- **Phase 2:** `google_places.get_details` (Place Details New, bare-name `DETAILS_FIELD_MASK`) +
  `cache.is_stale` / `cache.refresh_if_stale` (reuses the `services._aware` naive-datetime pattern).
  `GET /restaurants/{id}` refreshes a stale google row via one lazy Details call; **serves the stale
  copy on any fetch error** (no 500); stores a refreshed `place_id` if Google returns one; browse/
  search stay cache-only. 110 → 124 tests.

**PR #30 — NYC location resolution + market cutover** (`nyc-location-resolution`, Phases 3–4)
- **Phase 3:** layered `_resolve_location` — explicit lat/lng → DB-derived index (Philly seed;
  cached NYC ZIPs) → curated NYC neighborhoods (`app/geo_nyc.py`, ~55 centroids, reusing
  `proto.GeoIndex`) → Geocoding API (`app/providers/google_geocoding.py`, NYC-biased) → guidance
  error. Philly dev unchanged (DB index first). 124 → 136 tests.
- **Phase 4:** `recommender._default_center` — google-mode requests with no location default to a
  market center (`RECS_DEFAULT_CENTER="lat,lng"`, else the NYC centroid) so Text Search stays local;
  seed path stays unfiltered. Dev/prod split documented in `.env.example` + CLAUDE.md. 136 → 141.

## Notable engineering moments

- **The write-through changed the id space** (place_id → UUID), which broke the session-7 toggle
  tests' `"g1"` assertions — updated them to assert the rewrite + persistence. Expected fallout,
  caught immediately.
- **Test-DB pollution:** write-through persists `google_places` rows into the session-scoped test
  DB, breaking seed-count invariants (`candidate_count == 3`) out of order. Fixed with an autouse
  `conftest` cleanup fixture that strips google rows after each test.
- **SQLite naive datetimes:** `expires_at` reads back tz-naive; reused the existing
  `services._aware()` convention rather than inventing a new one.
- **Phase 4 surfaced a real interaction:** the NYC default center flows into the seed *fallback*
  too, so the Philly dev seed falls out of the NYC radius (0 rows, not 3). Correct for prod (the
  cache holds NYC rows there); updated `test_google_error_falls_back_to_seed` to pass an explicit
  Philly location. A behavior shift the test caught, not a bug.

## Docs & memory

- New `Design Docs/nyc-google-migration-plan.md` — the phased plan (0–5) with cache read-strategy
  (freshness check, two-cache split, TTL, force-refresh triggers) and cache-miss/not-found handling;
  Phases 0–4 marked done.
- TDD impl-status + §9, PRD, KNOWN_ISSUES, CLAUDE.md, `.env.example` synced.
- Memory: new `nyc-google-live-source` (the decision + phase progress); `env-support-and-google-
  provider-scaffold` updated (provider now wired in).

## State at session end

- Backend suite: **141 passed** (103 → 141; +38). Fully green, fully offline (MockTransport +
  mocked fetches; no key/network).
- **All three PRs merged into `master`** (later in the session, in order): **#28** (toggle) →
  **#29** (cache, Phases 0–2) → **#30** (location + cutover, Phases 3–4). Each merge required
  updating the branch with `master` and a passing required CI `test` check (branch protection);
  each stacked PR was retargeted to `master` after its base merged. The three feature branches were
  then deleted (remote + local) — repo is back to a single `master` branch. Working tree clean.

## Next up

1. **User action:** paste the rotated `GOOGLE_MAPS_API_KEY` into `backend/.env` (search + geocoding
   both use it), then run the smoke CLI / a live `RECS_PROVIDER=google` request against NYC.
2. **Phase 5 (optional):** grid pre-warm — only if cold-cache latency in launch neighborhoods bites;
   the write-through fills the cache lazily otherwise.
3. On paid-account upgrade: set the per-day quota hard-caps the free trial blocked.
4. Consider folding `restaurant_notes` / `list_items.source` / `visits.sentiment` and the new
   cache columns back into the TDD §5.1 tables (schema-vs-docs drift, pre-existing).
