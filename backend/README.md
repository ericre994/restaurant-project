# Backend — Lists API

FastAPI service for the **list-management** capability (PRD §4.1, TDD §5.1 / §6):
Want-to-Try / Visited / custom lists, list items, and visit recording.

This is the first backend in the repo. It uses **SQLite by default** so it runs
with zero external setup; the models map onto the Postgres schema in TDD §5 —
set `DATABASE_URL` to a Postgres DSN to switch.

## Setup & run

```bash
cd backend
pip install -r requirements.txt

python -m app.seed                       # load the Philly seed + create the dev user
uvicorn app.main:app --reload            # http://127.0.0.1:8000/docs
```

`app.seed` requires `YelpData/output/restaurants_Philadelphia_schema.json` — run
the YelpData pipeline first if it's missing. Without seeding, the API still runs;
you just won't have restaurants to add to lists.

## Dev UI (test harness)

A single-page vanilla-JS UI is served **same-origin** at
**http://127.0.0.1:8000/app/** (no CORS, no build step). It's a manual test
harness for the list interactions: search the Philly seed, create / rename /
delete lists, add / move / remove restaurants, edit notes & tags, and record
visits. The `X-User-Id` box in the header switches the acting user (blank = the
default dev user), so you can exercise per-user isolation by hand. The page lives
in `app/static/index.html` and talks only to the endpoints below.

## Migrations (Alembic)

Schema is defined by `app/models.py`; migrations are generated from it and live
in `alembic/`. They target whatever `DATABASE_URL` points at (SQLite for dev,
Postgres in prod), so run from `backend/`:

```bash
python -m alembic upgrade head                        # apply
python -m alembic revision --autogenerate -m "msg"    # after changing models.py
```

The initial migration is DB-agnostic (JSON `embedding`, B-tree lat/lng). The
Postgres specialization — `pgvector` embedding + `geography`/GIST radius + GIN
cuisine index (TDD §5.2) — is a deliberate **follow-up** migration, blocked on
fixing the embedding dimension `N` (TDD §9). For dev convenience the app still
does `create_all` on startup; on Postgres use `alembic upgrade head` instead.

## Tests

```bash
cd backend
pytest                                   # uses an isolated temp SQLite DB
```

### Exercising the LLM path without a key

The pipeline falls back to rating-sorted results when no `ANTHROPIC_API_KEY` is
set, so the `mode="llm"` branches (JSON parse, scored picks, `llm_model` logging,
LLM taste summary) wouldn't otherwise be covered. Set `FAKE_LLM=1` to make the
prototype return deterministic, schema-valid fake responses — offline, free, no
network:

```bash
FAKE_LLM=1 pytest                        # tests/test_llm_mode.py covers llm mode
FAKE_LLM=1 uvicorn app.main:app --reload # try the API in llm mode by hand
```

`FAKE_LLM` also takes two variant values for the robustness branches (TDD §4.1.2):

| `FAKE_LLM` | Behavior | Exercises |
| ---------- | -------- | --------- |
| `1` (or any truthy) | valid scored ranking | happy path → `mode=llm` |
| `hallucinate` | adds a bogus id to the picks | hallucination guard drops it → `mode=llm` |
| `malformed` | bad JSON on the first call, valid on retry | one-shot repair retry → `mode=llm-repair` |

`FAKE_LLM` is inert unless set, so it never affects production. For real Claude
output, install `anthropic` and set `ANTHROPIC_API_KEY` instead.

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET    | `/me` | Current user |
| GET    | `/me/taste-profile` | Read the taste profile (created empty on first access) |
| PUT    | `/me/taste-profile` | Set explicit prefs (`dietary_restrictions`, `ambiance_prefs`, cold-start `cuisines_preferred`/`price_pref`) |
| GET    | `/lists` | A user's lists (with item counts) |
| POST   | `/lists` | Create a custom list |
| PATCH  | `/lists/{id}` | Rename a custom list (`name`; core lists are protected) |
| DELETE | `/lists/{id}` | Delete a custom list (core lists are protected) |
| GET    | `/lists/{id}/items` | Items, hydrated; filters: `q`, `cuisine`, `price_max`, `tag` |
| POST   | `/lists/{id}/items` | Add a restaurant (`restaurant_id`, `note`, `tags`, `source`) |
| PATCH  | `/lists/{id}/items/{restaurant_id}` | Edit a saved item's `note` / `tags` / `source` (partial) |
| DELETE | `/lists/{id}/items/{restaurant_id}` | Remove a restaurant from a list |
| POST   | `/lists/{id}/items/{restaurant_id}/move` | Move to another list (`to_list_id`) |
| POST   | `/visits` | Record a visit (`sentiment`, `user_rating`, `notes`) |
| GET    | `/visits` | Visit history |
| GET    | `/restaurants` | Search the seed (`q`, `cuisine`, `price_max`, `limit`) |
| GET    | `/restaurants/{id}` | Restaurant detail |
| POST   | `/recommendations` | Run the retrieve→rank→render pipeline (`query`, `near`/`lat`+`lng`, `radius_km`, `price_max`, `cuisine`, `open_now`, `party_size`); writes a log row, returns its `recommendation_id` |
| POST   | `/recommendations/{id}/feedback` | Record per-item feedback (`restaurant_id`, `action`) — saved / dismissed / visited / thumbs_up / thumbs_down |
| GET    | `/recommendations/{id}` | Inspect a logged recommendation (provenance + feedback) |

## Behaviors worth knowing

- **Core lists are singletons.** Every user automatically gets one `want_to_try`
  and one `visited` list; they can't be created twice or deleted.
- **Recording a visit reconciles lists.** `POST /visits` removes the restaurant
  from Want-to-Try and adds it to Visited (PRD: marking visited is one action).
- **Auth is a dev stub.** The user is taken from an `X-User-Id` header, defaulting
  to a fixed dev user. Real auth is a TDD open question — swap `deps.get_current_user`
  when decided.
- **Schema extensions:** `list_items.tags`, `list_items.source`, and
  `visits.sentiment` are required by the PRD but not yet in the TDD draft tables.
  Fold them back into the TDD so docs and code agree.
- **Recommendations reuse the prototype.** `app/recommender.py` imports
  `../prototype/recommend.py` (the pipeline's single source of truth) for ranking
  + rendering. The taste profile is derived from the user's visit history
  (sentiment-weighted cuisines). With no `ANTHROPIC_API_KEY`, the endpoint returns
  the rating-sorted fallback (`match_score: null`); set the key to get LLM scores
  and reasons. `near` accepts these landmarks: chinatown, center city, rittenhouse,
  fishtown, south philly, university city, old city.
- **Stage 1 retrieval runs in SQL** (`recommender._sql_retrieve`): price, a geo
  bounding box on indexed `latitude`/`longitude`, and cuisine on `categories_text`,
  ordered by rating — so we never scan every row. Only the exact circular radius
  (bbox is a coarse square) and open-hours stay in Python. Those three columns are
  derived from `location`/`categories` at seed time; re-run `python -m app.seed`
  (after deleting `app.db`) if you change how they're populated.

## Feedback loop (TDD §4.5)

Every `POST /recommendations` writes a `recommendation_logs` row capturing query,
context (filters + taste snapshot), candidate set, model, `prompt_version`,
response, and latency. Clients post per-item actions back to
`/recommendations/{id}/feedback`; actions accumulate per restaurant in
`user_feedback`. Caveat: `token_usage` / `cost_estimate` are left null — the
prototype's `call_llm` discards the LLM usage object, so capturing them means
surfacing usage from `prototype/recommend.py` first.

**Taste aggregation (`app/taste.py`).** Recording a visit or recommendation
feedback calls `taste.refresh()`, which recomputes the user's `taste_profiles`
row: cuisine weights and price band from behavior (visits sentiment-weighted +
feedback actions), preserving explicit `dietary_restrictions` / `ambiance_prefs`.
The recommendation pipeline reads this persisted row (`recommender.load_taste_profile`)
rather than deriving a profile per request. Rules: derived fields are recomputed
from scratch each run (no double-counting); with zero behavioral signal, cold-start
seeds set via PUT survive. Generic Yelp umbrella categories (`Food`, `Restaurants`,
`Food Trucks`, …) are dropped via a category stopword list (`_CATEGORY_STOPWORDS`)
so real cuisines surface. The `derived_summary` is LLM-generated
(`proto.summarize_taste_profile`) and falls back to a deterministic template when
no `ANTHROPIC_API_KEY` is set or the call fails; it's only regenerated when the
derived signal actually changes, since `refresh()` runs on every visit/feedback.

## Next steps

- **[done]** Alembic migrations are generated from `app/models.py` (see the
  Migrations section above). Still to do on Postgres: a follow-up migration that
  replaces the lat/lng bbox with a `geography` + GIST radius query, adds a GIN
  index for cuisine, and switches `embedding` to pgvector (TDD §4.1 / §5.2) —
  gated on fixing the embedding dimension `N`.
- Surface LLM token usage from the prototype so `token_usage` / `cost_estimate`
  get logged (TDD §7.3 observability).
- Move `taste.refresh()` from inline (on each visit/feedback) to a periodic job
  once volume warrants it (TDD §4.5), and compute the `embedding` once an
  embedding model + dimension `N` are chosen.
