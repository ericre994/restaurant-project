# Backend — Lists API

FastAPI service for the **list-management** capability (PRD §4.1, TDD §5.1 / §6):
Want-to-Try / Visited / custom lists, list items, and visit recording.

This is the first backend in the repo. It uses **SQLite by default** so it runs
with zero external setup; the models map onto the Postgres schema in TDD §5 —
set `DATABASE_URL` to a Postgres DSN to switch.

## Setup & run

```bash
cd backend                               # run FROM here (see the note below)
pip install -r requirements.txt

python -m app.seed                       # load the Philly seed + create the dev user
uvicorn app.main:app                     # http://127.0.0.1:8000  (UI) · /docs (API)
```

**Two launch gotchas** (both surface as "the server keeps crashing" / a blank UI):

- **Run from `backend/`.** The dev DB default is now an absolute path to
  `backend/app.db`, so the seed is used no matter where you launch from — but
  running as a module (`app.main`) still needs `backend/` on the path. Simplest is
  to `cd backend` first. (`--app-dir backend` from the repo root also works.)
- **`--reload` restarts on every DB write.** With plain `--reload`, WatchFiles
  watches the whole tree including `app.db`; each list/visit write changes the file
  and restarts the server mid-request, which looks like a crash. Omit `--reload`
  for normal use, or exclude the DB if you want hot-reload on code edits:
  ```bash
  uvicorn app.main:app --reload --reload-exclude "*.db*"
  ```

`app.seed` requires `YelpData/output/restaurants_Philadelphia_schema.json` — run
the YelpData pipeline first if it's missing. Without seeding, the API still runs;
you just won't have restaurants to add to lists.

## Dev UI (test harness)

A vanilla-JS UI is served **same-origin** at **http://127.0.0.1:8000/app/** (no
CORS, no build step). The bare root **http://127.0.0.1:8000/** redirects there,
so the base URL just works (the API docs remain at `/docs`). It's a manual test
harness for the list interactions, split into two hash-routed pages:

- **Find Restaurants** (`#/lookup`) — search the Philly seed; each result has an
  **Add to…** picker (any core or custom list) and a **Log visit** button, and
  shows a badge if the restaurant is already in Want-to-Try / Visited.
- **My Lists** (`#/lists`) — the lists sidebar (create / rename / delete custom
  lists) plus the selected list's items, each with **Add to…**, edit notes/tags,
  **Log visit** (repeatable — "Log another visit"), and remove.

Adding to a core list is mutually exclusive (see Behaviors below); adding to a
custom list is additive. The page shows a **login / sign-up gate** on first load
and remembers your session (bearer token in `localStorage`), so you return to your
own lists next visit; **Log out** is in the header. The page lives in
`app/static/index.html` and talks only to the endpoints below.

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

> **Upgrading an existing dev `app.db`:** `create_all` only creates *missing*
> tables — it won't add the new `users.password_hash` column to a DB made before
> accounts existed. If signup 500s on an old `app.db`, delete it and re-seed
> (`rm app.db && python -m app.seed`) for a fresh full schema, or run
> `python -m alembic upgrade head` if that DB is Alembic-managed.

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
| POST   | `/auth/signup` | Create an account (`email`, `password` ≥8 chars, optional `display_name`) → `{token, user}` |
| POST   | `/auth/login` | Log in (`email`, `password`) → `{token, user}` |
| POST   | `/auth/logout` | Invalidate the presented bearer token |
| GET    | `/me` | Current user |
| GET    | `/me/taste-profile` | Read the taste profile (created empty on first access) |
| PUT    | `/me/taste-profile` | Set explicit prefs (`dietary_restrictions`, `ambiance_prefs`, cold-start `cuisines_preferred`/`price_pref`) |
| GET    | `/lists` | A user's lists (with item counts) |
| POST   | `/lists` | Create a custom list |
| PATCH  | `/lists/{id}` | Rename a custom list (`name`; core lists are protected) |
| DELETE | `/lists/{id}` | Delete a custom list (core lists are protected) |
| GET    | `/lists/{id}/items` | Items, hydrated; filters: `q`, `cuisine`, `price_max`, `tag` |
| POST   | `/lists/{id}/items` | Add a restaurant (`restaurant_id`, `source`; `note`/`tags` write through to the shared per-restaurant note); adding to a core list evicts it from the sibling core list |
| PATCH  | `/lists/{id}/items/{restaurant_id}` | Edit `source` (per-item); `note`/`tags` edit the shared per-restaurant note (partial) |
| DELETE | `/lists/{id}/items/{restaurant_id}` | Remove a restaurant from a list |
| POST   | `/lists/{id}/items/{restaurant_id}/move` | Move to another list (`to_list_id`) |
| POST   | `/visits` | Record a visit (`sentiment`, `user_rating`, `notes`, `visited_at`); `visited_at` after today is rejected (422); one row per visit — log as many as you like |
| GET    | `/visits` | Visit history; optional `restaurant_id` filters to one restaurant |
| GET    | `/restaurants` | Search the seed (`q` — typo-tolerant, `fuzzy=false` to opt out; `cuisine`, `price_max`, `limit`) |
| GET    | `/restaurants/cuisines` | Distinct cuisines + counts for the search typeahead (`q` filters) |
| GET    | `/restaurants/{id}` | Restaurant detail (includes `attributes`: hours/features) |
| GET    | `/restaurants/{id}/note` | The current user's shared note + tags for a restaurant (empty when unset) |
| PUT    | `/restaurants/{id}/note` | Set the current user's note/tags for a restaurant — shared across every list it's in (partial) |
| POST   | `/recommendations` | Run the retrieve→rank→render pipeline (`query`, `near`/`lat`+`lng`, `radius_km`, `price_max`, `cuisine`, `open_now`, `party_size`); writes a log row, returns its `recommendation_id` |
| POST   | `/recommendations/{id}/feedback` | Record per-item feedback (`restaurant_id`, `action`) — saved / dismissed / visited / thumbs_up / thumbs_down |
| GET    | `/recommendations/{id}` | Inspect a logged recommendation (provenance + feedback) |

## Behaviors worth knowing

- **Core lists are singletons.** Every user automatically gets one `want_to_try`
  and one `visited` list; they can't be created twice or deleted.
- **Core lists are mutually exclusive.** A restaurant is only ever in Want-to-Try
  *or* Visited, never both: adding it to one core list (via `POST /lists/{id}/items`
  or by recording a visit) removes it from the other. Custom lists are unaffected —
  a restaurant can sit in a core list and any number of custom lists at once.
- **Recording a visit reconciles lists.** `POST /visits` removes the restaurant
  from Want-to-Try and adds it to Visited (PRD: marking visited is one action).
  Each call logs a separate visit row, so a restaurant can have a full visit
  history (fetch it with `GET /visits?restaurant_id=...`). A `visited_at` dated
  after today is rejected (compared by calendar date, so earlier-today is fine).
- **Notes & tags belong to the restaurant, not the list.** They live on
  `restaurant_notes` (one row per user+restaurant), so a note written on a
  restaurant in Want-to-Try shows on that same restaurant in any custom list. The
  list-item endpoints accept/return `note`/`tags` for convenience, but the source
  of truth is the shared record — edit it directly via `GET|PUT /restaurants/{id}/note`.
  `source` is the exception: it's per-save and stays on the list item.
- **Accounts, with a dev bypass.** Real local accounts back the API: `POST /auth/signup`
  and `/auth/login` return an opaque bearer token (stored server-side in `sessions`,
  revoked on logout); send it as `Authorization: Bearer <token>`. Passwords are
  PBKDF2-hashed (`app/security.py`) — no external auth provider or JWT library. The
  legacy `X-User-Id` header still works as a **dev-only** fallback (and the fixed dev
  user when neither is present) so existing tests/scripts keep working; gate or remove
  that bypass for production. A managed external provider is still a TDD open question.
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
