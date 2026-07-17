# Technical Design Document — Restaurant Discovery & Management App


|                  |                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| **Status**       | Draft — MVP slice partially implemented                                                          |
| **Author**       | Eric                                                                                             |
| **Version**      | 0.5                                                                                              |
| **Last updated** | July 14, 2026                                                                                    |
| **Reviewers**    | *TBD*                                                                                            |
| **Related docs** | PRD, Cost & Unit Economics Model, API ToS Review, Privacy & Data Handling Notes, Product Roadmap, Git/CI Setup |


---

## 1. Overview

This document describes the technical design for an app that helps people discover, organize, and book restaurants. The product is built around three pillars: **saved restaurant list management**, **AI-powered natural-language recommendations**, and **reservation creation**.

The MVP scope is: natural-language recommendations, want-to-try / visited list management, and reservation availability alerts. A social layer and direct reservation-API partnerships are deliberately out of scope for the MVP and are deferred to later phases to avoid scope creep.

The central technical bet is the **recommendation pipeline**: rather than asking an LLM to search the world, the system pre-filters a small candidate set (15–20 restaurants) from a structured data source, then uses the LLM purely for ranking, scoring, and explanation. This keeps cost and latency bounded and predictable while still delivering the "it understands what I want" experience.

### Implementation status (July 15, 2026)

A first vertical slice is implemented in `backend/` (FastAPI + SQLAlchemy) on top of the `prototype/` recommendation pipeline. The design below remains the target; this box records current reality and where it defers or stands in.

**Built**

- **Accounts & sessions** (§5.1, §6): local **email/password** signup/login (`POST /auth/{signup,login,logout}`) with **PBKDF2-HMAC-SHA256** password hashing (stdlib — no external auth provider or JWT library) and opaque **bearer-token sessions** (a `sessions` table, revoked on logout). Signup now **requires a first name, last name, and a unique `@username`** (3–30 chars, case-insensitive uniqueness); **login stays by email**, and the UI display name is the **first name**. `Authorization: Bearer <token>` identifies the user; the legacy `X-User-Id` header remains a **dev-only** fallback so tests/scripts keep working. Each account's lists/visits/notes are already isolated by `user_id`, so accounts make that per-user data actually private and persistent across visits.
- **List management** (§5.1): want-to-try / visited / custom lists, list items, visits — with list rename (`PATCH /lists/{id}`) and item edit (`PATCH /lists/{id}/items/{restaurant_id}`). A restaurant's `note`/`tags` are per-user-per-restaurant (`restaurant_notes`), shared across every list it's in and editable directly via `GET/PUT /restaurants/{id}/note`; `source` is per-save. The two core lists are **mutually exclusive**: adding a restaurant to one (by an explicit add or by recording a visit) evicts it from the other, while custom lists stay additive. Each visit is a separate row (and can't be dated in the future), so a restaurant keeps a visit history (`GET /visits?restaurant_id=`); visits are also **editable and deletable** (`PATCH`/`DELETE /visits/{id}`, owner-only, same future-date guard).
- **Restaurant discovery / browse**: `GET /restaurants` search over the cache with a **typo-tolerant name match** (exact `ILIKE` first, then a `SequenceMatcher` + word-prefix fuzzy fallback when it underfills; `fuzzy=false` opts out), plus filters: cuisine (`categories_text`, **repeatable — matches any**), **exact multi-select `price`** levels (and legacy `price_max`), and **`rating_min`**. `GET /restaurants/cuisines` returns distinct cuisines + counts for a search typeahead; `GET /restaurants/{id}` returns full detail including `attributes` (hours/features). Open-now / open-24h filtering is applied client-side from the returned `attributes.hours` (the seed encodes both a closed day and a 24-hour day as `0:0-0:0`, disambiguated by a day-pattern heuristic — a Yelp-seed workaround to drop when a real provider lands). Distinct from the recommendation pipeline's Stage-1 retrieval below.
- **Recommendation pipeline** behind `POST /recommendations`, reusing `prototype/recommend.py` as the single source of truth for ranking/render. Stage 1 retrieval runs in SQL (price + geo bounding box + cuisine), pre-ranked by `rating` desc, `rating_count` desc, then `id` asc as a **deterministic tiebreaker** — so retrieval is reproducible and the SQL path matches the prototype's `retrieve()` exactly. `near` resolves **any ZIP or neighborhood centroid derived from the data** (no geocoding service; ~56 ZIPs + ~28 named Philadelphia neighborhoods, fuzzy-matched), superseding the old 7 hardcoded landmarks. The hallucination guard and one-shot repair retry are implemented; the offline fallback (no `ANTHROPIC_API_KEY`) is a **personalized heuristic ranker** — taste-profile cuisine fit + query keywords/features + price comfort + distance + volume-shrunk rating, with real 0–100 `match_score`s — rather than a plain rating sort. All tested (offline).
- **Google Places retrieval provider** (§4.1 Stage 1) — *scaffolded 2026-07-15, **wired into `POST /recommendations` behind a source toggle 2026-07-17**.* `backend/app/providers/google_places.py` calls **Text Search (New)** (`places:searchText`) and maps results into the **same seed-dict shape** the SQL/seed path produces (`recommender._to_seed_dict`), so it's a drop-in alternative Stage-1 source; the rank/render stages are unchanged. It pushes price / open-now / `includedType=restaurant` / a location-bias circle into the request, refines the exact circular radius in Python (prototype `haversine_km`), and applies the same `rating`/`rating_count`/`id` pre-rank. It uses an **Enterprise-tier field mask** (id, name, location, types, rating, userRatingCount, priceLevel, regularOpeningHours) so **one call returns ≤20 candidates as a single billable event** and never touches the pricier Atmosphere fields (reviews/editorial) — those are for lazy Place Details on a detail view. Offline-tested via httpx `MockTransport` (`tests/test_google_places.py`, 12 tests; no key/network). **Source selection** is `RECS_PROVIDER` (`seed` default | `google`), dispatched in `recommender._retrieve_candidates`; the `google` path **falls back to the SQL/seed path on any `GooglePlacesError`** (missing key / API error) so a request always returns results, and `recommendation_logs.context.retrieval` records which source served it (`tests/test_provider_toggle.py`, 7 tests). Cuisine is folded into the text query since Text Search has no structured cuisine filter. **Write-through cache (2026-07-17):** Google candidates are now upserted into `restaurants` (`app/cache.py`, keyed by `(source, source_id=place_id)`) with the new `expires_at` (TTL, default 7 days via `RESTAURANT_CACHE_TTL_DAYS`) and `raw` columns (migration `d4e5f6a7b8c9`), and their ids are rewritten place_id → internal UUID — so a Google pick is persisted and saveable to lists/visits/notes (proven end-to-end). Refresh-on-read of stale rows (Place Details) and NYC location resolution are the next phases. Whether Google becomes the *default* live source, and reconciling Google's caching ToS with the restaurant cache, remain open (PRD §8.1 / §9 below). See `Design Docs/nyc-google-migration-plan.md`.
- **Config / secrets**: the backend now loads `backend/.env` at startup (`app/__init__.py` → `python-dotenv`, absolute path, `override=False` so real env vars and the test harness win; `.env` is gitignored, `.env.example` committed). `GOOGLE_MAPS_API_KEY` (restricted to Places API New + Geocoding) lives there alongside `ANTHROPIC_API_KEY` / optional `DATABASE_URL`.
- **Feedback loop** (§4.5): every recommendation writes a `recommendation_logs` row; `POST /recommendations/{id}/feedback` records per-item actions.
- **Taste profiles** (§4.5): `taste_profiles` is aggregated from visits + feedback; `derived_summary` is LLM-generated with a deterministic template fallback. Read by the pipeline per request (`GET/PUT /me/taste-profile`).
- **Migrations** (§5.2): Alembic migrations generated from the models cover all implemented tables and the incremental deltas (per-restaurant notes; user accounts + sessions; the `username`/`first_name`/`last_name` columns — nullable so pre-existing accounts stay valid, with upgrade+downgrade exercised). They are DB-agnostic (JSON `embedding`, B-tree lat/lng), so they apply to both dev SQLite and Postgres; the Postgres specialization (pgvector, GIST, GIN) is a deferred follow-up (see below).
- **Dev UI**: a single-page vanilla-JS harness served same-origin at `/app` (no CORS, no build step) exercises the browse + list + recommendation APIs. It has three tabs — **Find Restaurants**, **Recommendations**, and **My Lists** — behind a redesigned **landing / auth gate** (welcoming hero + copy; signup collects first/last name, unique `@username`, password + confirm with inline validation; the session token persists in localStorage so you return to your own lists). **Find Restaurants** is a two-column layout: a left **search + filters** sidebar (name search with rolling/debounced live results; a single **Advanced Filters** show/hide toggle over titled facets — multi-select price chips, minimum rating, hours [anytime / open now / open 24h], and a curated cuisine chip set) and a right **results** column. A restaurant **detail view** shows hours (today highlighted; closed/24-hour handled), features, an "Open in Maps" link that resolves the actual business (not raw coordinates), and the per-restaurant **visit history** (each visit editable/deletable). Saving is via a one-click **Want-to-Try** toggle (hidden once visited), **Log visit** (date capped at today), and an **add-to-list picker** listing *every* list with membership check-marks (closes on outside click). **Recommendations** calls `POST /recommendations` and renders ranked picks with match scores + reasons. **My Lists** has per-list sorting/filtering, note/tags editing and list creation via **modals** (not `prompt()`). It stands in for the not-yet-built client app and is explicitly a dev test tool, not production UI.

**Schema deltas folded into §5.1**: `users.username` / `first_name` / `last_name` (required at signup; display name = first name); `restaurant_notes` (per-user-per-restaurant note + tags, shared across lists), `list_items.source`, `visits.sentiment` (required by PRD §4.1); plus dev-only derived columns on `restaurants` (`latitude`, `longitude`, `categories_text`) for SQLite indexing.

**Deferred / dev stand-ins** (consistent with the open questions in §9)

- **Persistence**: SQLite for dev, modeling the Postgres schema. An initial Alembic migration now exists (DB-agnostic); the Postgres specialization — pgvector embeddings + `geography`/GIST + a GIN cuisine index — is a deferred follow-up migration, blocked on fixing the embedding dimension `N` (so `embedding` stays null for now).
- **Auth**: local email/password accounts are now implemented (see Built above); the `X-User-Id` header remains a **dev-only** fallback and should be gated/removed for production. A **managed external identity provider** (OAuth/social) is still an open decision (§9).
- **Observability**: `recommendation_logs.token_usage` / `cost_estimate` are null — the prototype's LLM call doesn't yet surface usage.
- **Not started**: reservations (§4.3), availability alerts (§4.4), the weekly recap (PRD §4.5), and a *periodic* taste-recompute job (refresh runs inline on each visit/feedback for now).
- **Testing**: an offline `FAKE_LLM` mode exercises the LLM / repair / fallback branches without an API key (§7.4); CI runs the suite on every push/PR.

### Assumptions to confirm

These are not yet decided in our planning and are assumed here for concreteness. Please correct any that are wrong; several sections depend on them.


| Area                  | Assumption                                                               | Notes                                                                                |
| --------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Client platform       | Native mobile (iOS + Android), likely cross-platform (e.g. React Native) | Deep-link reservations and push-based alerts strongly imply mobile-first.            |
| Backend language      | Language-neutral REST service over PostgreSQL                            | Examples are given as pseudocode / HTTP; Postgres is fixed by the pgvector decision. |
| Hosting               | Single managed Postgres + stateless app tier + a job runner              | Could be a PaaS or cloud provider; not specified here.                               |
| Auth                  | Local email/password accounts are implemented; a third-party provider (OAuth / managed auth) remains an option | *Updated:* the slice now stores PBKDF2 password hashes + bearer-token sessions locally (§7.2). Adopting a managed provider (store a provider id instead of passwords) is still open (§9). |
| Candidate data source | Google Places **or** Yelp Fusion (one primary, the other a fallback)     | *Google side scaffolded 2026-07-15 (Text Search provider + Cloud project). Cost model: post-March-2025 per-SKU free tiers, ~$35/1k Enterprise Text Search, billed at the mask's most expensive field — so the ≤20-candidates-per-call design = one billable event. **Open blocker:** Google ToS permits storing `place_id` indefinitely but restricts caching other Places content, which conflicts with the durable restaurant cache — the deciding factor vs Yelp. See §9.* |


---

## 2. Goals and Non-Goals

### Goals

- Return a ranked, explained set of restaurant recommendations from a natural-language query in a few seconds.
- Let users maintain want-to-try and visited lists, and record visits.
- Let users set an availability alert for a restaurant and be notified when a matching reservation slot opens.
- Initiate reservations via deep link to the provider's booking flow.
- Capture a feedback loop that improves recommendation quality over time.
- Keep per-recommendation cost and latency low and predictable.

### Non-Goals (MVP)

- Social features (sharing, following, friend activity).
- Direct, in-app reservation booking via partner APIs (deep-link only for now).
- Multi-city editorial content, menus, or photo hosting.
- Real-time table inventory beyond what alert polling provides.

---

## 3. System Architecture

### 3.1 Components

- **Client app** — issues recommendation queries, renders result cards (match score + explanation), manages lists/visits, sets alerts, opens reservation deep links, receives push notifications.
- **Backend API** — stateless service exposing REST endpoints; owns business logic, auth verification, and orchestration of the recommendation pipeline.
- **Recommendation orchestrator** — the module that runs the three-step pipeline (retrieve → rank → render payload). Lives inside the backend.
- **PostgreSQL (with pgvector + PostGIS-style geospatial)** — system of record plus the restaurant cache and embeddings.
- **External data provider** — Google Places / Yelp Fusion for candidate retrieval and restaurant metadata.
- **LLM provider** — ranking, scoring, and explanation generation; also taste-profile summarization and embedding generation (embeddings may come from the same or a dedicated embeddings model).
- **Job runner** — background workers for availability-alert polling, cache refresh/expiry, and periodic taste-profile recomputation.
- **Push notification service** — delivers alert notifications to the client.

### 3.2 High-level flow (recommendation request)

```
Client
  │  POST /recommendations  { query, location, filters }
  ▼
Backend API ──► Recommendation Orchestrator
                   │ 1. Load taste_profile (+ embedding) for user
                   │ 2. Candidate retrieval:
                   │      - check restaurants cache (by geo + filters)
                   │      - call Places/Yelp for misses → upsert cache
                   │      - narrow to 15–20 candidates
                   │      - (optional) pgvector re-rank vs taste embedding
                   │ 3. Assemble LLM prompt (query + profile + candidates)
                   │ 4. Call LLM → structured JSON (ranked picks, scores, reasons)
                   │ 5. Validate/parse JSON, hydrate with restaurant details
                   │ 6. Write recommendation_logs row
                   ▼
              Response: ranked results with match scores + explanations
  ▼
Client renders cards; user actions (save / dismiss / visit) ──► feedback endpoint
```

---

## 4. Detailed Component Design

### 4.1 Recommendation pipeline (core)

The pipeline has three stages, matching the architecture we agreed on.

**Stage 1 — Data retrieval & candidate pre-filtering.**
The orchestrator builds a structured query from the user's natural-language request plus explicit filters (location radius, price, open-now, cuisine if specified) and the user's taste profile. It first checks the local `restaurants` cache; cache misses (or stale entries) trigger a call to the external provider, and results are upserted into the cache. The candidate set is deliberately capped at **15–20 restaurants**. This cap is the main cost/latency control: the LLM never sees more than this many candidates.

Optionally, when more than ~20 viable candidates exist, the orchestrator uses **pgvector** similarity between each restaurant's embedding and the user's taste embedding to pre-rank and trim to the top candidates before the LLM call. This makes the candidate set smarter without spending LLM tokens.

**Stage 2 — LLM ranking & reasoning.**
The orchestrator assembles a single prompt containing: (a) the user's natural-language query, (b) a compact representation of the taste profile, and (c) the candidate list as structured data. The LLM is instructed to return **only JSON** — a ranked list of picks, each with a stable restaurant identifier, a numeric match score, and a short natural-language explanation. The LLM ranks and explains; it does not invent restaurants or facts outside the candidate set.

**Stage 3 — JSON-driven UI rendering.**
The backend validates and parses the JSON (rejecting/repairing malformed output — see §4.1.2), hydrates each pick with full restaurant detail from the cache, and returns a clean payload the client maps directly to result cards. The client does not parse free-form text.

#### 4.1.1 Prompt assembly (the backend function on your roadmap)

The prompt-assembly function is the heart of Stage 2. Its contract:

- **Inputs:** `query` (string), `taste_profile` (structured), `candidates` (array of compact restaurant records), `constraints` (party size, location, etc.), `prompt_version`.
- **Output:** a fully-formed messages array plus the `prompt_version` used (logged for reproducibility).

Schematic of the assembled prompt:

```
SYSTEM:
  You are a restaurant recommender. Rank ONLY the candidates provided.
  Never invent restaurants or facts not present in the candidate data.
  Return ONLY valid JSON matching the schema. No prose, no markdown.

USER:
  Request: "<user query>"
  Diner profile: <compact taste profile: cuisines, price, dietary, ambiance>
  Constraints: <party size, when, distance>
  Candidates: <array of {id, name, cuisine, price_level, rating, distance,
                           key attributes}>

  Return JSON:
  {
    "picks": [
      { "restaurant_id": "...", "match_score": 0-100,
        "reasons": ["...", "..."] }
    ]
  }
```

Design notes:

- Keep candidate records **compact** — only fields that affect ranking — to control token cost.
- Version the prompt (`prompt_version`) and log it, so quality changes are attributable.
- Pass a stable `restaurant_id` for each candidate and require the model to echo it, so results map back deterministically to cache rows.

#### 4.1.2 Robustness of LLM output

- **Schema validation:** validate the JSON against a strict schema; on failure, attempt one repair retry, then fall back so the user still gets results. *(Implemented)* the fallback is a **deterministic personalized ranker** — it scores the candidates offline by taste-profile cuisine fit + query keyword/feature match + price comfort + distance + volume-shrunk rating (real 0–100 scores + short reasons), which also serves as the offline default until the LLM is enabled. On Postgres it composes with the pgvector pre-ranking order.
- **Hallucination guard:** drop any `restaurant_id` not in the candidate set.
- **Determinism/repro:** log model, prompt version, and the exact candidate set. Stage-1 pre-rank order is itself deterministic (rating, then volume, then `id`).

### 4.2 Restaurant data ingestion & caching

External data is cached in the `restaurants` table to cut cost, latency, and external rate-limit pressure, and to give us a stable internal id for every place. Each cached row has a TTL (`expires_at`); reads past TTL trigger a refresh on next access or via the job runner. The raw provider payload is retained in a `raw` JSONB column so we can re-derive structured fields without re-fetching. Embeddings are computed once per restaurant (or on metadata change) and stored for pgvector similarity.

### 4.3 Reservations (deep-link-first)

For the MVP, a reservation is an **intent**: the backend records party size, requested time, provider, and the constructed deep-link URL, then the client opens the provider's booking flow. We do not yet confirm bookings programmatically. The `reservations` table and `provider`/`status` fields are structured so that a later migration to direct partner APIs (confirming bookings in-app) is additive rather than a rewrite.

### 4.4 Availability alerts

A user creates an alert for a restaurant with a desired date, time window, and party size. The job runner polls provider availability for active alerts on a schedule (with backoff and per-provider rate limiting), and when a matching slot is found it flips the alert to `triggered` and sends a push notification. Alerts expire after their target date passes. Polling cadence and provider ToS constraints are tracked in the API ToS doc.

### 4.5 Feedback loop

Every recommendation request writes a `recommendation_logs` row. User actions on the results — saving to a list, dismissing, marking visited — are written back as feedback. Periodically (job runner), feedback is aggregated to refine the user's `taste_profile`: updating preference weights, regenerating the natural-language summary, and recomputing the taste embedding. This is the mechanism by which recommendation quality improves over time.

---

## 5. Data Model

PostgreSQL with pgvector for embeddings, geospatial types for location, and JSONB for flexible, provider-shaped attributes. Nine tables.

### 5.1 Tables

**users**


| Column                  | Type             | Notes               |
| ----------------------- | ---------------- | ------------------- |
| id                      | uuid PK          |                     |
| email                   | citext UNIQUE    | login identifier    |
| username                | text UNIQUE      | *(implemented)* required `@handle` chosen at signup (case-insensitive unique); identity/mentions — login is still by email |
| first_name              | text             | *(implemented)* required at signup |
| last_name               | text             | *(implemented)* required at signup |
| display_name            | text             | shown in UI chrome; set to the first name for real accounts |
| password_hash           | text             | *(implemented)* PBKDF2-HMAC-SHA256, stored `pbkdf2_sha256$iters$salt$hash`; null for the dev-stub user |
| auth_provider           | text             | *(future)* external identity-provider name — unused until a managed provider is chosen (§9) |
| auth_provider_id        | text             | *(future)* external subject id |
| home_location           | geography(Point) | nullable            |
| created_at / updated_at | timestamptz      |                     |


**sessions** *(implemented)* — opaque bearer-token login sessions (local auth)


| Column     | Type            | Notes                                                            |
| ---------- | --------------- | ---------------------------------------------------------------- |
| token      | text PK         | random URL-safe secret; sent as `Authorization: Bearer <token>`  |
| user_id    | uuid FK → users | ON DELETE CASCADE                                                |
| created_at | timestamptz     |                                                                  |
| expires_at | timestamptz     | 30-day TTL; row deleted on logout                                |


**taste_profiles** (one per user)


| Column               | Type                   | Notes                          |
| -------------------- | ---------------------- | ------------------------------ |
| id                   | uuid PK                |                                |
| user_id              | uuid FK → users UNIQUE | one profile per user           |
| cuisines_preferred   | jsonb                  | weighted preferences           |
| price_pref           | int[]                  | acceptable price levels        |
| dietary_restrictions | jsonb                  |                                |
| ambiance_prefs       | jsonb                  | e.g. quiet, lively, date-night |
| derived_summary      | text                   | LLM-generated NL summary       |
| embedding            | vector(N)              | taste embedding for pgvector   |
| updated_at           | timestamptz            |                                |


**restaurants** (cache of external data)


| Column                 | Type             | Notes                     |
| ---------------------- | ---------------- | ------------------------- |
| id                     | uuid PK          | internal stable id        |
| source                 | text             | `google` / `yelp`         |
| source_id              | text             | external place id         |
| name                   | text             |                           |
| location               | geography(Point) |                           |
| address                | text             |                           |
| price_level            | int              |                           |
| categories             | jsonb            |                           |
| attributes             | jsonb            | hours, features, etc.     |
| rating / rating_count  | numeric / int    |                           |
| embedding              | vector(N)        | restaurant embedding      |
| raw                    | jsonb            | raw provider payload      |
| cached_at / expires_at | timestamptz      | TTL for refresh           |
| latitude / longitude   | double           | *(dev)* derived from `location`; B-tree indexed for the SQLite geo bounding-box query |
| categories_text        | text             | *(dev)* lowercased, comma-joined categories for cuisine `LIKE` matching |
|                        |                  | UNIQUE(source, source_id) |


**lists**


| Column     | Type            | Notes                                |
| ---------- | --------------- | ------------------------------------ |
| id         | uuid PK         |                                      |
| user_id    | uuid FK → users |                                      |
| type       | text            | `want_to_try` / `visited` (core: one each per user, mutually exclusive) / `custom` |
| name       | text            |                                      |
| created_at | timestamptz     |                                      |

Invariant: a restaurant is in at most one of the two **core** lists at a time — adding it to `want_to_try` or `visited` (or recording a visit) removes it from the other. `custom` lists are additive and unaffected. Enforced in application logic, not a DB constraint.


**list_items**


| Column        | Type                  | Notes                          |
| ------------- | --------------------- | ------------------------------ |
| id            | uuid PK               |                                |
| list_id       | uuid FK → lists       |                                |
| restaurant_id | uuid FK → restaurants |                                |
| source        | text                  | attribution for *this* save: "saved from a friend", "saw on Instagram" — genuinely per-membership, so it lives here |
| added_at      | timestamptz           |                                |
|               |                       | UNIQUE(list_id, restaurant_id) |

`note` and `tags` are **not** on this table: a user's annotation is a property of the *restaurant*, not of one list membership, so it lives on `restaurant_notes` (below) and follows the restaurant across every list it appears in.


**restaurant_notes**


| Column        | Type                  | Notes                          |
| ------------- | --------------------- | ------------------------------ |
| id            | uuid PK               |                                |
| user_id       | uuid FK → users       |                                |
| restaurant_id | uuid FK → restaurants |                                |
| note          | text                  | free-text note                 |
| tags          | jsonb                 | cuisine / neighborhood / occasion tags (PRD §4.1) |
| updated_at    | timestamptz           |                                |
|               |                       | UNIQUE(user_id, restaurant_id) |

One note per user per restaurant, shared across Want-to-Try, Visited, and every custom list the restaurant is in. The `/lists/{id}/items` endpoints accept and hydrate `note`/`tags` for convenience (write-through to this table), and it's editable directly via `GET/PUT /restaurants/{id}/note`.


**visits**


| Column        | Type                  | Notes                 |
| ------------- | --------------------- | --------------------- |
| id            | uuid PK               |                       |
| user_id       | uuid FK → users       |                       |
| restaurant_id | uuid FK → restaurants |                       |
| visited_at    | timestamptz           |                       |
| sentiment     | text                  | 1-tap `loved` / `liked` / `wouldnt_return` (PRD §4.1; highest taste signal) |
| user_rating   | int                   | the user's own rating |
| notes         | text                  |                       |
| created_at    | timestamptz           |                       |

Invariant: `visited_at` must not be after today (a visit can't be logged for a future day). Enforced in application logic (compared by calendar date, so an earlier-today timestamp is still accepted).


**reservations**


| Column         | Type                  | Notes                                   |
| -------------- | --------------------- | --------------------------------------- |
| id             | uuid PK               |                                         |
| user_id        | uuid FK → users       |                                         |
| restaurant_id  | uuid FK → restaurants |                                         |
| party_size     | int                   |                                         |
| requested_time | timestamptz           |                                         |
| provider       | text                  | e.g. resy / opentable                   |
| status         | text                  | `deep_link_initiated` (+ future states) |
| deep_link_url  | text                  |                                         |
| created_at     | timestamptz           |                                         |


**availability_alerts**


| Column          | Type                  | Notes                                            |
| --------------- | --------------------- | ------------------------------------------------ |
| id              | uuid PK               |                                                  |
| user_id         | uuid FK → users       |                                                  |
| restaurant_id   | uuid FK → restaurants |                                                  |
| desired_date    | date                  |                                                  |
| time_window     | tstzrange             | acceptable window                                |
| party_size      | int                   |                                                  |
| provider        | text                  |                                                  |
| status          | text                  | `active` / `triggered` / `expired` / `cancelled` |
| last_checked_at | timestamptz           |                                                  |
| created_at      | timestamptz           |                                                  |


**recommendation_logs** (feedback loop)


| Column               | Type            | Notes                                |
| -------------------- | --------------- | ------------------------------------ |
| id                   | uuid PK         |                                      |
| user_id              | uuid FK → users |                                      |
| query_text           | text            |                                      |
| context              | jsonb           | geo, filters, taste snapshot         |
| candidate_set        | jsonb           | candidate ids + source               |
| llm_model            | text            |                                      |
| prompt_version       | text            |                                      |
| llm_response         | jsonb           | ranked picks, scores, reasons        |
| shown_restaurant_ids | jsonb           | what the user actually saw           |
| user_feedback        | jsonb           | saved / dismissed / visited per item |
| latency_ms           | int             |                                      |
| token_usage          | jsonb           | prompt/completion tokens *(currently null — see Implementation status)* |
| cost_estimate        | numeric         | *(currently null pending LLM usage capture)* |
| created_at           | timestamptz     |                                      |


### 5.2 Indexing

- Geospatial index (GIST) on `restaurants.location` and `users.home_location` for radius queries.
- Vector index (HNSW or IVFFlat) on `restaurants.embedding` and `taste_profiles.embedding`.
- B-tree on all foreign keys and on `restaurants (source, source_id)`.
- Partial index on `availability_alerts (status)` where `status = 'active'` for the polling job.
- GIN on heavily-queried JSONB columns (e.g. `restaurants.categories`) if filtering on them.
- *(Dev/SQLite)* The current backend approximates the geo and cuisine indexes with B-tree indexes on derived `restaurants.latitude`/`longitude` (a bounding-box prefilter, refined to an exact radius in code) and a `LIKE` over `categories_text`. These collapse into the GIST + GIN indexes above on Postgres.

### 5.3 Notable design choices

- **Restaurant caching** decouples us from provider latency/rate limits and gives a stable internal id used everywhere else (lists, visits, reservations, logs).
- **Notes/tags on `restaurant_notes`, not `list_items`.** An annotation ("great for groups", "get the tasting menu") describes a restaurant, not a particular list membership. Keying it on (user, restaurant) means it survives moving a restaurant between lists and shows everywhere the restaurant appears. `source` is the deliberate exception — where a save came from *is* per-membership, so it stays on `list_items`.
- **JSONB attributes** absorb provider-shaped, evolving fields without schema churn, while frequently-filtered fields are promoted to typed columns.
- **pgvector embeddings** power both candidate pre-ranking and "more like this" without an external vector store.
- **recommendation_logs** is a first-class feedback substrate, not just analytics — it directly feeds taste-profile refinement.

---

## 6. API Design (REST)


| Method              | Path                             | Purpose                                            |
| ------------------- | -------------------------------- | -------------------------------------------------- |
| POST                | `/auth/signup`                   | *(implemented)* Create account — email, password, first/last name, unique `@username` → `{ token, user }` |
| POST                | `/auth/login`                    | *(implemented)* Log in (email + password) → `{ token, user }` |
| POST                | `/auth/logout`                   | *(implemented)* Invalidate the current bearer token |
| GET                 | `/me`                            | Current user profile                               |
| GET / PUT           | `/me/taste-profile`              | Read / update taste profile                        |
| POST                | `/recommendations`               | Run pipeline; body: `{ query, location, filters }` |
| POST                | `/recommendations/{id}/feedback` | Record per-item feedback                           |
| GET / POST          | `/lists`                         | List / create lists                                |
| PATCH / DELETE      | `/lists/{id}`                    | Rename / delete a custom list (core lists protected) |
| GET/POST/PATCH/DELETE | `/lists/{id}/items`            | Manage items: add (evicts from the sibling core list), edit `source` + write-through `note`/`tags`, move, remove |
| GET / POST          | `/visits`                        | Record a visit (rejects future `visited_at`) / list visit history (optional `?restaurant_id=`) |
| PATCH / DELETE      | `/visits/{id}`                   | *(implemented)* Edit / delete a logged visit (owner-only; same future-date guard) |
| GET                 | `/restaurants` · `/restaurants/{id}` | Search the cache (typo-tolerant `q`; repeatable `cuisine`; exact multi `price` + `price_max`; `rating_min`) / restaurant detail |
| GET                 | `/restaurants/cuisines`          | Distinct cuisines + counts for the search typeahead |
| GET / PUT           | `/restaurants/{id}/note`         | Read / set the current user's shared note + tags for a restaurant |
| POST                | `/reservations`                  | Create reservation intent → returns deep link      |
| GET / POST / DELETE | `/availability-alerts`           | Manage alerts                                      |


**Background jobs:** availability-alert poller, cache refresh/expiry sweep, taste-profile recompute.

---

## 7. Cross-cutting Concerns

### 7.1 Performance & cost

- LLM cost is bounded by the **15–20 candidate cap** and compact candidate records; both are the primary cost levers.
- Cache-first retrieval minimizes external API spend and tail latency.
- Target a recommendation round-trip of a few seconds; the dominant term is the single LLM call.
- Detailed projections live in the separate Cost & Unit Economics Model.

### 7.2 Security & privacy

- Passwords: the implemented local auth stores **PBKDF2-HMAC-SHA256** hashes (per-password salt, ~240k iterations) — never plaintext — and issues opaque, revocable bearer-token sessions. If a managed identity provider is adopted later (§9), password storage can move to it.
- Taste profiles, visits, and location are personal data — covered by the Privacy & Data Handling Notes; apply least-privilege access and encryption in transit/at rest.
- External provider data is cached under their ToS (retention/attribution rules tracked in the API ToS Review).

### 7.3 Observability

- Log per-recommendation latency, token usage, cost, and prompt version (in `recommendation_logs`).
- Monitor external API error/rate-limit rates and alert-poll success.
- Track LLM JSON-validation failure rate as a quality signal.

### 7.4 Testing

- Unit tests for prompt assembly (golden prompts per `prompt_version`) and JSON parsing/repair.
- Contract tests against provider API response shapes (with recorded fixtures).
- Integration tests for the full pipeline against a seeded cache, asserting schema-valid output and correct hydration.
- *(Implemented)* An offline `FAKE_LLM` mode returns deterministic, schema-valid LLM responses (with `hallucinate` / `malformed` variants) so the `llm` / `llm-repair` / `fallback` branches are tested without an API key. CI runs the suite (fallback + `FAKE_LLM`) on every push/PR.

---

## 8. Rollout / Phasing

- **Phase 1 (MVP):** recommendations, lists/visits, availability alerts, deep-link reservations, feedback loop.
- **Phase 2:** direct reservation API integrations (confirm bookings in-app); richer taste-profile learning.
- **Phase 3:** social layer.

---

## 9. Open Questions & Risks

- **Backend language / hosting / auth provider** — not yet chosen (see Assumptions). *Update: the implemented slice uses Python / FastAPI. Auth is now **local email/password** accounts (PBKDF2 hashes + bearer-token sessions), which resolves the "how do users own their data" product need; the `X-User-Id` header remains a dev-only fallback to gate/remove for production. Still open: whether to adopt a **managed external identity provider** (OAuth/social) instead of local passwords.*
- **Client platform** — confirm native mobile vs. cross-platform.
- **Primary data provider** — Google Places vs. Yelp Fusion; ToS and cost differ. *Update 2026-07-15: the **Google path is de-risked and scaffolded** — Cloud project + Places API (New)/Geocoding enabled, a working Text Search Stage-1 provider (`app/providers/google_places.py`), and a verified cost model (per-SKU free tiers; ~$35/1k Enterprise; ≤20 candidates per billable call). **Two things still gate the final choice:** (1) launch-market (NYC) coverage/quality — Google has it, the Yelp Open Dataset does not; (2) Google's caching ToS (store `place_id` indefinitely, but not other content long-term) vs. the durable restaurant cache — pointing toward treating the `restaurants` table as a short-lived, refresh-on-read cache for Google-sourced fields. **Update 2026-07-17:** the provider is now **wired into `recommend()` behind a `RECS_PROVIDER` toggle** (`seed` default | `google`), so both sources are runnable without committing to one — this decision is now about which becomes the *default*, not about integration work. The Google path falls back to the seed path on error. The dev seed remains the Yelp Open Dataset (Philadelphia; academic-use-only, no NYC coverage).*
- **Embedding model & dimension `N`** — pick the model; fix the vector dimension before the pgvector migration. *Still open; the initial (DB-agnostic) Alembic migration stores `embedding` as JSON/null, and Stage 1 pre-ranks by rating as a stand-in until a real embedding + pgvector column land.*
- **Alert polling vs. ToS** — confirm permitted polling cadence per provider.
- **LLM JSON reliability** — measure validation-failure rate early; the repair + personalized-fallback path mitigates it. *Update: schema validation, hallucination guard, one-shot repair, and a personalized heuristic fallback ranker are implemented and tested (offline via `FAKE_LLM`). The real Anthropic API has not yet been exercised end-to-end, so the live failure rate is unmeasured.*

---

## 10. Appendix

- **Glossary:** *candidate set* (the 15–20 restaurants the LLM ranks); *taste profile* (structured + embedding representation of a user's preferences); *match score* (LLM-assigned 0–100 fit score).
- **References:** PRD, Cost & Unit Economics Model, API ToS Review, Privacy & Data Handling Notes, Competitive Landscape One-Pager, Product Roadmap.
