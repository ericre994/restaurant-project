# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

An **early-stage** project for a restaurant discovery & management app. The design is far ahead of the code; there is no client app yet, and the backend covers only the first feature slice. The repo holds:

- **`Design Docs/`** — the PRD (`restaurant-app-prd_2.md`) and Technical Design Doc (`technical-design-doc.md`). These are the source of truth; the code that exists is downstream of them. Read the TDD before touching the backend, prototype, or data pipeline.
- **`YelpData/`** — a Python pipeline that turns the Yelp Open Dataset into seed rows for the planned `restaurants` table.
- **`prototype/`** — a runnable, database-free proof of the core "retrieve → rank → render" recommendation pipeline.
- **`backend/`** — a FastAPI service. Implements the **list-management** capability (Want-to-Try / Visited / custom lists, list items, visits) and wraps the recommendation pipeline behind `POST /recommendations`. First real backend; uses SQLite for dev, models the Postgres schema.

Nothing here is shippable production code. The Yelp dataset is **academic-use only** (see `YelpData/docs/`) — it is fine for local dev but cannot be used in production; the planned production data source is Google Places or Yelp Fusion (undecided — PRD open question #1).

## The central architecture (read this first)

The whole product rests on one bet, described in TDD §4.1: **never ask the LLM to search the world.** Instead, a three-stage pipeline bounds cost and latency:

1. **Retrieve** — hard-filter a structured data source (location radius, price, cuisine, open-hours) down to a small candidate set, capped at **15–20 restaurants**. This cap is the primary cost/latency lever. Optionally pre-rank with pgvector similarity against the user's taste embedding.
2. **Rank** — send the LLM *only* the compact candidate records + the user's taste profile + the query, at low temperature, asking for **strict JSON only** (ranked picks with a stable `restaurant_id`, a 0–100 `match_score`, and short `reasons`). The LLM ranks and explains; it never invents restaurants.
3. **Render** — validate the JSON, **drop any `restaurant_id` not in the candidate set** (hallucination guard), retry once on malformed output, then fall back to the pre-ranking order so the user always gets results.

`prototype/recommend.py` implements all three stages end-to-end against the Philadelphia seed, with no database. Its function names map 1:1 to the TDD: `retrieve()` (§4.1 stage 1), `assemble_messages()` (§4.1.1 prompt assembly), `parse_picks()` + `_fallback()` (§4.1.2 robustness).

**The prototype is the single source of truth for LLM/pipeline logic — it is not reimplemented.** The backend imports `prototype/recommend.py` via `backend/app/_proto.py` (one place does the `sys.path` setup; both `recommender` and `taste` import `proto` from it). The backend uses the prototype for `compact_candidate` / `rank` / the hallucination guard (recommendations) and `summarize_taste_profile` (taste summaries). So `prototype/recommend.py` is live production logic, not throwaway — changing those stages means editing the prototype, and both the CLI demo and the backend pick it up.

**Stage 1 retrieval, however, was moved into SQL** (`recommender._sql_retrieve`) and no longer uses the prototype's `retrieve()`: price + a geo bounding box (indexed `latitude`/`longitude`) + cuisine (`categories_text`) + rating pre-rank run in the query; only the exact circular radius and open-hours refine in Python. The three columns are derived from `location`/`categories` at seed time. `_sql_retrieve` is verified to return the same candidate *set* as the prototype's `retrieve()` (order may differ only among exact rating+rating_count ties). On Postgres this becomes a `geography`/GIST radius query + GIN cuisine index + pgvector pre-rank (TDD §4.1 / §5.2).

The canonical data schema is the **`restaurants` table in TDD §5.1** (nine tables total). Both the data pipeline and the prototype are built to conform to it: `location` as a GeoJSON Point `[lng, lat]`, `categories` as a JSON array, `attributes` as `{features, hours}`, `embedding` still `null` (model/dimension not yet chosen), and `raw` retaining the full provider payload. Keep all three (docs, pipeline, prototype) in agreement when changing field shapes.

## Commands

### Backend (Lists API)
```bash
cd backend
pip install --user -r requirements.txt    # system Anaconda is read-only here; --user is required
python -m app.seed                          # load Philly seed into SQLite + create dev user
uvicorn app.main:app --reload               # docs at http://127.0.0.1:8000/docs
pytest                                       # 6 e2e tests against an isolated temp SQLite DB
```
SQLite (`backend/app.db`) is the dev default; set `DATABASE_URL` to a Postgres DSN to switch. Tables are created via `create_all` on startup — generate Alembic migrations from `app/models.py` before going to Postgres. Auth is a dev stub: the user comes from an `X-User-Id` header, defaulting to a fixed dev user (`services.DEV_USER_ID`). See `backend/README.md` for the endpoint table. **This environment is Python 3.9** — use `typing.Optional[...]`, not PEP 604 `X | None`, in any annotation SQLAlchemy or FastAPI resolves (both fail to evaluate `|` unions on 3.9).

### Recommendation prototype
```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...        # Windows PowerShell: $env:ANTHROPIC_API_KEY="..."
cd prototype

python recommend.py --demo date_night      # built-in scenarios: date_night | cheap_eats | group_dinner
python recommend.py --query "late-night noodles, casual, solo" \
                    --near chinatown --price-max 2 --cuisine Noodles Chinese
```
Without an API key it still runs Stage 1 and shows a rating-sorted fallback, so retrieval can be checked on its own. It reads `YelpData/output/restaurants_Philadelphia_schema.json` — run the data pipeline first if that file is missing. The prototype uses `claude-sonnet-4-6`; `PROMPT_VERSION` is set so prompt-quality changes stay attributable.

**Testing the LLM path without a key:** set `FAKE_LLM=1` and the prototype returns deterministic, schema-valid fake responses for ranking and taste summaries (offline, free) — `mode` becomes `llm`, scored picks render, `llm_model` is logged. Two variant values exercise the robustness branches (TDD §4.1.2): `FAKE_LLM=hallucinate` injects a bogus id the guard must drop (still `mode=llm`), and `FAKE_LLM=malformed` returns bad JSON on the first call so the one-shot repair retry runs (`mode=llm-repair`). Used by `backend/tests/test_llm_mode.py`. The fake lives in `prototype/recommend.py` (`_fake_*` helpers) and is inert unless `FAKE_LLM` is set, so it never affects production. For real Claude output, set `ANTHROPIC_API_KEY` (and `pip install anthropic`).

### Yelp data pipeline
Run in order from `YelpData/scripts/` (each `.bat` is a double-click runner that logs to `YelpData/logs/`; or run the `.py` directly):

```bash
# 1. Extract the tar, then filter to a city and map onto the restaurants schema
python extract_and_prepare_yelp.py --extract --summary --city "Philadelphia" --limit 1000
#    --summary prints city/state counts. NOTE: the Yelp dataset has NO New York City data,
#    even though NYC is the PRD launch market. Philadelphia is the stand-in seed.
#    Produces output/restaurants_seed_Philadelphia.{json,sql}

# 2. Normalize into strictly schema-conformant records (GeoJSON location, parsed attributes)
python normalize_to_schema.py
#    Produces output/restaurants_Philadelphia_schema.{json,ndjson}

# 3. Flatten to CSV (nested columns become JSON strings)
python convert_to_csv.py
#    Produces output/restaurants_Philadelphia_schema.csv
```

The pipeline is **standard-library only** (no pip installs). `extract_and_prepare_yelp.py` run with no arguments defaults to building all Philadelphia restaurants. `normalize_to_schema.py` asserts that every output record has exactly the schema columns — that assertion is the contract guarding schema drift.

## Things easy to get wrong

- **City mismatch is intentional.** The seed is Philadelphia; the launch market is NYC. The pipeline is city-agnostic (`--city`), but Yelp simply has no NYC data, so do not treat the Philadelphia data as production-shaped for the target market.
- **Yelp attribute values are Python-literal strings** (e.g. `"True"`, `"u'free'"`, `"{'garage': False}"`). `normalize_to_schema.py` uses `ast.literal_eval` to turn them into real JSON. Raw seed (`restaurants_seed_*.json`) is *not* clean; the `_schema.json` output is. The prototype reads the schema output, not the raw seed.
- **No embeddings exist yet.** `embedding` is `null` everywhere; Stage 1 pre-ranks by `rating` then `rating_count` as a stand-in for the pgvector step. Picking the embedding model and fixing the vector dimension `N` is an open question that blocks the real migrations.
- **The backend extends the TDD's draft schema.** `list_items.tags`, `list_items.source`, and `visits.sentiment` are required by PRD §4.1 but absent from the TDD §5.1 tables. They live in `backend/app/models.py`; fold them back into the TDD so docs and code stay in agreement. Recording a visit (`POST /visits`) is not just a log write — it reconciles the core lists (removes from Want-to-Try, adds to Visited).
- **Every recommendation is logged** to `recommendation_logs` (TDD §4.5), and `POST /recommendations/{id}/feedback` writes per-item actions back into its `user_feedback` — the feedback-loop substrate. `token_usage`/`cost_estimate` are intentionally null until the prototype surfaces LLM usage. When updating a JSON column in place (e.g. `user_feedback`), **reassign a new object** (`log.user_feedback = {...}`) — SQLAlchemy doesn't track in-place mutation of JSON columns, so appending to the existing dict/list won't persist.
- **The taste profile is persisted and aggregated, not derived per request.** `taste.refresh()` (in `app/taste.py`) recomputes the `taste_profiles` row from visits + feedback on each visit/feedback write; the pipeline reads it via `recommender.load_taste_profile`. Derived fields (cuisines, price) are recomputed from scratch each run (no double-count) and preserve explicit `dietary_restrictions`/`ambiance_prefs` set via `PUT /me/taste-profile`; cold-start seeds survive until real behavior exists. Aggregation drops generic Yelp umbrella categories (`Food`, `Restaurants`, …) via a category stopword list (`taste._CATEGORY_STOPWORDS`) so real cuisines surface. The `derived_summary` is LLM-generated (`proto.summarize_taste_profile`) with a deterministic template fallback when there's no API key; it's regenerated only when the derived signal changes (refresh runs on every visit/feedback, so unconditional LLM calls would be wasteful). The `embedding` column stays null pending the model/dimension decision.
