# Technical Design Document — Restaurant Discovery & Management App


|                  |                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------ |
| **Status**       | Draft for review                                                                                 |
| **Author**       | Eric                                                                                             |
| **Version**      | 0.1                                                                                              |
| **Last updated** | June 17, 2026                                                                                    |
| **Reviewers**    | *TBD*                                                                                            |
| **Related docs** | PRD, Cost & Unit Economics Model, API ToS Review, Privacy & Data Handling Notes, Product Roadmap |


---

## 1. Overview

This document describes the technical design for an app that helps people discover, organize, and book restaurants. The product is built around three pillars: **saved restaurant list management**, **AI-powered natural-language recommendations**, and **reservation creation**.

The MVP scope is: natural-language recommendations, want-to-try / visited list management, and reservation availability alerts. A social layer and direct reservation-API partnerships are deliberately out of scope for the MVP and are deferred to later phases to avoid scope creep.

The central technical bet is the **recommendation pipeline**: rather than asking an LLM to search the world, the system pre-filters a small candidate set (15–20 restaurants) from a structured data source, then uses the LLM purely for ranking, scoring, and explanation. This keeps cost and latency bounded and predictable while still delivering the "it understands what I want" experience.

### Assumptions to confirm

These are not yet decided in our planning and are assumed here for concreteness. Please correct any that are wrong; several sections depend on them.


| Area                  | Assumption                                                               | Notes                                                                                |
| --------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Client platform       | Native mobile (iOS + Android), likely cross-platform (e.g. React Native) | Deep-link reservations and push-based alerts strongly imply mobile-first.            |
| Backend language      | Language-neutral REST service over PostgreSQL                            | Examples are given as pseudocode / HTTP; Postgres is fixed by the pgvector decision. |
| Hosting               | Single managed Postgres + stateless app tier + a job runner              | Could be a PaaS or cloud provider; not specified here.                               |
| Auth                  | Third-party identity provider (OAuth / managed auth)                     | We store a provider id, not passwords.                                               |
| Candidate data source | Google Places **or** Yelp Fusion (one primary, the other a fallback)     | ToS and cost tradeoffs handled in the separate API ToS / Cost docs.                  |


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

- **Schema validation:** validate the JSON against a strict schema; on failure, attempt one repair retry, then fall back to the pgvector pre-ranking order so the user still gets results.
- **Hallucination guard:** drop any `restaurant_id` not in the candidate set.
- **Determinism/repro:** log model, prompt version, and the exact candidate set.

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
| email                   | citext UNIQUE    |                     |
| display_name            | text             |                     |
| auth_provider           | text             | e.g. provider name  |
| auth_provider_id        | text             | external subject id |
| home_location           | geography(Point) | nullable            |
| created_at / updated_at | timestamptz      |                     |


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
|                        |                  | UNIQUE(source, source_id) |


**lists**


| Column     | Type            | Notes                                |
| ---------- | --------------- | ------------------------------------ |
| id         | uuid PK         |                                      |
| user_id    | uuid FK → users |                                      |
| type       | text            | `want_to_try` / `visited` / `custom` |
| name       | text            |                                      |
| created_at | timestamptz     |                                      |


**list_items**


| Column        | Type                  | Notes                          |
| ------------- | --------------------- | ------------------------------ |
| id            | uuid PK               |                                |
| list_id       | uuid FK → lists       |                                |
| restaurant_id | uuid FK → restaurants |                                |
| note          | text                  |                                |
| added_at      | timestamptz           |                                |
|               |                       | UNIQUE(list_id, restaurant_id) |


**visits**


| Column        | Type                  | Notes                 |
| ------------- | --------------------- | --------------------- |
| id            | uuid PK               |                       |
| user_id       | uuid FK → users       |                       |
| restaurant_id | uuid FK → restaurants |                       |
| visited_at    | timestamptz           |                       |
| user_rating   | int                   | the user's own rating |
| notes         | text                  |                       |
| created_at    | timestamptz           |                       |


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
| token_usage          | jsonb           | prompt/completion tokens             |
| cost_estimate        | numeric         |                                      |
| created_at           | timestamptz     |                                      |


### 5.2 Indexing

- Geospatial index (GIST) on `restaurants.location` and `users.home_location` for radius queries.
- Vector index (HNSW or IVFFlat) on `restaurants.embedding` and `taste_profiles.embedding`.
- B-tree on all foreign keys and on `restaurants (source, source_id)`.
- Partial index on `availability_alerts (status)` where `status = 'active'` for the polling job.
- GIN on heavily-queried JSONB columns (e.g. `restaurants.categories`) if filtering on them.

### 5.3 Notable design choices

- **Restaurant caching** decouples us from provider latency/rate limits and gives a stable internal id used everywhere else (lists, visits, reservations, logs).
- **JSONB attributes** absorb provider-shaped, evolving fields without schema churn, while frequently-filtered fields are promoted to typed columns.
- **pgvector embeddings** power both candidate pre-ranking and "more like this" without an external vector store.
- **recommendation_logs** is a first-class feedback substrate, not just analytics — it directly feeds taste-profile refinement.

---

## 6. API Design (REST)


| Method              | Path                             | Purpose                                            |
| ------------------- | -------------------------------- | -------------------------------------------------- |
| GET                 | `/me`                            | Current user profile                               |
| GET / PUT           | `/me/taste-profile`              | Read / update taste profile                        |
| POST                | `/recommendations`               | Run pipeline; body: `{ query, location, filters }` |
| POST                | `/recommendations/{id}/feedback` | Record per-item feedback                           |
| GET / POST          | `/lists`                         | List / create lists                                |
| GET / POST / DELETE | `/lists/{id}/items`              | Manage list items                                  |
| POST                | `/visits`                        | Record a visit                                     |
| GET                 | `/restaurants/{id}`              | Restaurant detail                                  |
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

- No password storage; rely on the identity provider.
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

---

## 8. Rollout / Phasing

- **Phase 1 (MVP):** recommendations, lists/visits, availability alerts, deep-link reservations, feedback loop.
- **Phase 2:** direct reservation API integrations (confirm bookings in-app); richer taste-profile learning.
- **Phase 3:** social layer.

---

## 9. Open Questions & Risks

- **Backend language / hosting / auth provider** — not yet chosen (see Assumptions).
- **Client platform** — confirm native mobile vs. cross-platform.
- **Primary data provider** — Google Places vs. Yelp Fusion; ToS and cost differ (see ToS / Cost docs).
- **Embedding model & dimension `N`** — pick the model; fix the vector dimension before writing migrations.
- **Alert polling vs. ToS** — confirm permitted polling cadence per provider.
- **LLM JSON reliability** — measure validation-failure rate early; the repair + pgvector fallback path mitigates it.

---

## 10. Appendix

- **Glossary:** *candidate set* (the 15–20 restaurants the LLM ranks); *taste profile* (structured + embedding representation of a user's preferences); *match score* (LLM-assigned 0–100 fit score).
- **References:** PRD, Cost & Unit Economics Model, API ToS Review, Privacy & Data Handling Notes, Competitive Landscape One-Pager, Product Roadmap.
