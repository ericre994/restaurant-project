# NYC / Google Live-Source Migration Plan

**Status:** planning · **Decided:** 2026-07-17 · **Owner:** Eric

Transition the app's data source from the Philadelphia Yelp Open Dataset seed to
**Google Places (New), used live**, for the NYC launch market. This is the
implementation plan behind that decision; the decision itself and its rationale
live in TDD §9 and PRD §8.1.

---

## The decision, in one paragraph

Google Places is the **production live retrieval source** — *not* a scraped,
owned static dataset. Google's Maps Platform terms let you store `place_id`
indefinitely but cap caching of other Places content (name, rating, price,
hours, address, coordinates, categories) at **~30 days**, then require refresh or
deletion. So the compliant shape is `restaurants` as a **write-through,
refresh-on-read cache** keyed by `place_id`, with the durable user-owned data
(lists, visits, notes, taste) layered permanently on top. Verify the exact
caching window against the current Google terms at build time.

### The reframe: no up-front bulk scrape
With a live write-through cache, the cache fills **lazily from real user
queries** — cheaper, always inside the TTL, and it sidesteps the cost and the
20-per-page / 60-per-query enumeration ceiling entirely. "Replicate all of NYC
up front" is unnecessary for this model. An optional grid pre-warm (Phase 5)
becomes a *cache warm*, not an owned corpus.

### What's permanent vs. refreshable
| Bucket | Fields |
|---|---|
| **Permanent** | your internal `id` (UUID), `source_id` (= `place_id`), `expires_at`, and **all user data** (lists, list_items, visits, restaurant_notes, taste_profiles) |
| **Refreshable (≤30-day TTL)** | everything else Google returns: `name`, `rating`, `rating_count`, `price_level`, `hours`, `address`, `location`/`lat`/`lng`, `categories`, `businessStatus`, `raw` |

Note: "rarely changes" ≠ "permanent." Coordinates/address change rarely but are
still Content on the 30-day clock — only `place_id` is legally permanent.

---

## Current state (starting point)

- **`RECS_PROVIDER` toggle shipped** (PR #28): `recommender._retrieve_candidates`
  dispatches Stage 1 to `seed` (default) or `google`; the Google path calls Text
  Search and falls back to the seed path on error. **But the `google` path is
  ephemeral** — candidates are ranked and returned, never persisted.
- **`restaurants` schema gap**: PK is a UUID (`id`), external id in `source_id`,
  with a `(source, source_id)` unique constraint. **No `expires_at` / `raw`
  columns** (the TDD §5.1 design has them; `models.py` never got them).
- **FK reality**: `list_items`, `restaurant_notes`, `visits` all FK to
  `restaurants.id`. So a Google place must be **persisted first** before a user
  can save/visit/note it — today they can't.
- **Id-space mismatch**: `google_places._map_place` emits candidates with
  `id = place_id`; the DB uses UUID PKs. Phase 1 reconciles this.
- **Location resolution**: `recommender._geo_index` is built from the Philly
  seed, so `near="chinatown"`-style resolution is Philadelphia-only today.

---

## Phase 0 — Schema: make `restaurants` a real TTL cache  *(foundation)*

**Goal:** give the cache the columns the refresh-on-read model needs.

- Add `expires_at: datetime | null` (drives refresh-on-read) and
  `raw: JSON | null` (retain the full Google payload) to `models.Restaurant`.
- Generate an **Alembic migration** from the updated model; keep `create_all`
  in sync so tests (which seed via `create_all`) match the migration.
- No behavior change yet — columns are nullable and unused until Phase 1.

**Files:** `backend/app/models.py`, `backend/alembic/versions/*` (new migration).
**Tests:** existing suite stays green; add a migration/round-trip smoke check.
**Done when:** the two columns exist, migration applies cleanly, suite green.

---

## Phase 1 — Write-through on retrieval  *(the core — makes Google picks saveable)*

**Goal:** a restaurant you search in NYC becomes a persisted, saveable row.

- On a Google retrieval, **upsert** each candidate into `restaurants` by
  `(source='google_places', source_id=place_id)`: insert new rows (mint the
  UUID), refresh rows past `expires_at`, set `expires_at = now + TTL`, and
  populate the derived `latitude`/`longitude`/`categories_text` columns (same
  derivation `seed.py` uses). Store the payload in `raw`.
- **Rewrite each candidate's `id`** from `place_id` → the row UUID *before*
  ranking, so ranked output, `by_id`, and — critically — list/visit/note saves
  all use the durable internal id. The hallucination guard still holds (ids come
  from the candidate set).
- Likely a small `recommender`-level helper or a new `cache.py` module; keep the
  provider (`google_places.retrieve`) pure (no DB) so it stays MockTransport-
  testable.

**Files:** `backend/app/recommender.py` (+ maybe `backend/app/cache.py`).
**Tests:** offline via MockTransport — assert upsert creates/refreshes rows,
ids are rewritten to UUIDs, a Google pick is then addable to a list, re-query
within TTL doesn't re-fetch, past TTL refreshes.
**Done when:** with `RECS_PROVIDER=google` (mocked), a recommendation persists
candidates and one can be saved to Want-to-Try.

---

## Phase 2 — Refresh-on-read for detail / browse

**Goal:** stale rows self-heal on access; detail views stay fresh.

- `GET /restaurants/{id}`: if a Google-sourced row is past `expires_at`, refresh
  it via a single lazy **Place Details** call before returning (the cost-optimal
  pattern — one place, only when actually viewed).
- Optionally factor the refresh so a future background job runner can reuse it;
  start with on-read only.

**Files:** `backend/app/routers/restaurants.py`, `providers/google_places.py`
(add a `get_details(place_id)` path), `cache.py`.
**Tests:** offline — expired row triggers a (mocked) Details refresh; fresh row
does not.
**Done when:** viewing an expired restaurant refreshes it; fresh ones don't call out.

---

## Phase 3 — NYC location resolution

**Goal:** `near=` works for NYC, not just Philadelphia.

- Replace/augment the Philly-seed `_geo_index` with: (a) the **Geocoding API**
  (already enabled) for arbitrary text → coords, and/or (b) a small curated **NYC
  neighborhood-centroid table** for the hot paths. Client-supplied `lat`/`lng`
  keeps working unchanged.
- Decide caching for geocoded results (Geocoding has its own ToS/cost).

**Files:** `backend/app/recommender.py` (`_resolve_location` / `_geo_index`), a
geocoding helper, possibly a static NYC-neighborhoods data file.
**Tests:** offline — known NYC neighborhood/ZIP resolves to expected coords
(mock Geocoding); unknown still 422s with guidance.
**Done when:** an NYC neighborhood query returns NYC candidates.

---

## Phase 4 — Market cutover & dev/prod split

**Goal:** run NYC/Google in production while keeping tests offline & deterministic.

- Offline tests stay on the **Philly Yelp seed** (`RECS_PROVIDER=seed`, no
  key/network) — the deterministic fixture. Google stays MockTransport-tested,
  plus one live smoke test.
- Production config: `RECS_PROVIDER=google`, key set, NYC default coords.
- Update the dev-UI defaults / docs for the NYC context; keep the Yelp-seed hours
  workaround gated so it drops when Google data lands (KNOWN_ISSUES).

**Files:** config/docs, `app/static/index.html` defaults, `.env.example`.
**Done when:** prod serves NYC via Google; `pytest` runs fully offline on Philly.

---

## Phase 5 — Optional grid pre-warm  *(only if cold-cache latency matters)*

**Goal:** avoid a cold cache in launch neighborhoods.

- One-time **Nearby Search (New)** grid over target NYC areas
  (`includedTypes:["restaurant"]` + per-cell location restriction), subdividing
  dense cells (the 60-per-query cap), dedupe by `place_id`, upsert via the Phase
  1 path. This is a *cache warm* under the same TTL — not an owned corpus.
- Gate behind a script; log what was covered/dropped (no silent truncation).

**Files:** `backend/scripts/prewarm_nyc.py` (new).
**Done when:** target areas have warm cache rows; cost logged against the budget.

---

## Cache read strategy (Phases 1–2 design)

**One-line rule:** serve from cache when the row is fresh; call the API only to
*discover* new places, to refresh a *stale* row, or to fetch fields you never
cached.

### The default freshness check
Every Google-sourced row carries `expires_at`. On any read of a known restaurant:

```
if row exists and now < row.expires_at:
    serve from DB                     # free, fast — the common case
else:                                 # missing OR stale
    call Google, upsert row, set expires_at = now + TTL, serve
```

### It differs by operation
| Operation | Cache vs API |
|---|---|
| Save to list / record visit / add note | **Always cache/DB** — references the internal row by id; no API call, freshness irrelevant. |
| Detail view (`GET /restaurants/{id}`) | **Cache-first.** Fresh → serve from DB. Stale → one lazy **Place Details** call, refresh, serve. |
| Search / recommend (Stage 1) | **Must call the Search API** — you can't *discover* new places from a cache that only knows what it has already seen. |

### Two caches
- **Entity cache** — `restaurants` rows keyed by `place_id`, TTL = `expires_at`.
  The important one.
- **Search-result cache** (optional) — query+location+filters → the place_id
  list, short TTL, so a user re-running an identical search doesn't re-bill. A
  cost optimization, not core.

### Three triggers that force an API call even on a *fresh* row
1. **Missing fields, not staleness.** The Search/Enterprise mask caches the
   ranker's fields; a detail view wanting **reviews/photos** (Atmosphere tier)
   was never cached → call Place Details anyway. Freshness ≠ completeness.
2. **User-forced refresh** (pull-to-refresh) → call regardless of TTL.
3. **Freshness-critical flows** (e.g. verify not `CLOSED_PERMANENTLY` before a
   reservation) → tighter check than the general TTL.

### TTL choice
`expires_at` window = **min(ToS ceiling, your UX/cost choice)**. The ~30-day cap
is a legal ceiling, not a target; volatile fields (rating, review count, hours,
business status) argue for **shorter** TTLs. Default **7 days**; lengthen toward
30 only under cost/quota pressure. One `expires_at` per row — a single Place
Details call refreshes the whole row, so fields aren't TTL'd individually.

### Optional latency win
**Stale-while-revalidate**: serve a slightly-stale row immediately and refresh in
the background (job runner) instead of blocking the read. Adds complexity — a
later optimization, not Phase 1/2.

### Cache miss & not-found handling
A cache miss is never a dead end — it's a trigger to call Google once and
populate the cache — except when the place truly doesn't exist.

| Situation | Behavior |
|---|---|
| **Search in a cold area** | Normal lazy-fill: call Search, **write-through upsert** all candidates, rank, serve. First user pays the call; the rest hit a warm cache. No pre-population needed. |
| **Search returns zero results** | Not a cache issue — empty candidate set; pipeline returns no picks / graceful fallback. |
| **Detail view, internal UUID not in DB** | **404.** Rare by construction — search already upserted every candidate before it could be clicked (unless TTL cleanup deleted the row). |
| **Detail view, a raw `place_id` never cached** (deep link / external save) | **Fetch-through**: one Place Details call, upsert, serve. Miss → fill. |
| **Place genuinely doesn't exist / dead `place_id`** | Google `NOT_FOUND` → **404.** If Details returns a **refreshed** place_id, store the new one and drop the old (place_id is the permanent key — keep it correct). |

## Cross-cutting notes

- **Cost control** (session-6 model, verify SKUs at build): one Text/Nearby
  Search = one billable event, ≤20 results, **Enterprise** field mask (ranker's
  fields, no Atmosphere). Place Details only lazily on a detail view. Budget
  alert at $10/mo is the interim guard until paid-account per-day quota caps.
- **`recommendation_logs`**: it snapshots candidate names/ratings — treat that as
  transient audit data keyed by `place_id`/internal id, not a durable content
  store. Revisit when touching that table.
- **Key**: `GOOGLE_MAPS_API_KEY` in `backend/.env` is still empty — a live call
  needs the user to paste a rotated key. Phases 0–3 are all testable offline
  without it.

## Recommended starting point
**Phase 0 + Phase 1** — the spine. Self-contained, fully offline-testable, and
everything else depends on it.
