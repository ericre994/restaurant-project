# Restaurant Discovery & Management App

![CI](https://github.com/ericre994/restaurant-project/actions/workflows/ci.yml/badge.svg)

Early-stage app for discovering, organizing, and booking restaurants, built around
AI-powered natural-language recommendations. The central bet: rather than asking an
LLM to search the world, pre-filter a small candidate set from structured data, then
use the LLM purely to rank, score, and explain. See [CLAUDE.md](CLAUDE.md) for the
architecture and a component-by-component guide.

## Layout

- `Design Docs/` — PRD and Technical Design Doc (the source of truth)
- `prototype/` — database-free retrieve → rank → render recommendation pipeline
- `backend/` — FastAPI service: lists, recommendations, feedback logs, taste profiles
- `YelpData/` — pipeline that turns the Yelp Open Dataset into `restaurants` seed data

> The Yelp Open Dataset is **academic-use-only** and is not committed — regenerate it
> locally via `YelpData/scripts/`. See [`YelpData/README.md`](YelpData/README.md).

## Quick start

```bash
cd backend
pip install -r requirements.txt
python -m app.seed              # loads the Yelp seed; see YelpData/README.md first
uvicorn app.main:app --reload   # API docs at http://127.0.0.1:8000/docs
```

Run the tests (no API key needed — the pipeline falls back gracefully):

```bash
cd backend
pytest                          # 29 tests against an isolated temp SQLite DB
FAKE_LLM=1 pytest               # also exercises the LLM path offline
```

See [`backend/README.md`](backend/README.md) for endpoints and the feedback loop.
