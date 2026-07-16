# Session Summary — 2026-07-15 (session 6)

Focus: the carried-forward **Google Maps / Places API** task — research the cost model, set up
a Google Cloud account in the browser, and lay the code foundation. Ended with a **verified
Google Places retrieval provider scaffolded** (103 backend tests, up from 91) and the Cloud
project live. **Code is uncommitted** in the `master` working tree (no PR this session).

Working style: I drove the Google Cloud Console via the **Claude-in-Chrome** browser extension
(this session it was connected, unlike session 5's headless approach). The user made the key
security call (delete-and-recreate exposed keys). Cost facts were pulled from live web search +
Google's docs, not memory, because Places pricing changed materially in March 2025.

---

## Cost model (verified 2026-07, post-March-2025 pricing)

- The old **$200 pooled monthly credit is GONE** — replaced by **per-SKU free tiers**:
  Essentials 10k/mo, Pro 5k/mo, Enterprise 1k/mo.
- Key SKUs: **Text Search Enterprise ~$35/1k**, Place Details Enterprise ~$20/1k, Geocoding
  $5/1k (10k free), Place Photos $7/1k.
- **Billed at the highest-priced field in the field mask.** rating/priceLevel/openingHours →
  Enterprise; adding reviews/editorialSummary → Enterprise+Atmosphere ($40).
- **Design that falls out of this** (maps onto the retrieve→rank→render pipeline): **one**
  Text Search (New) call returns up to 20 candidates = 1 billable event; use an **Enterprise**
  mask (the ranker's fields) and never fan out to per-place Detail calls at retrieval time.
  Place Details fetched lazily only when a user opens a restaurant.
- **Caching ToS caveat** (feeds PRD open-question #1, Google vs Yelp): Google lets you store
  `place_id` indefinitely but restricts caching other Places content — in tension with the TDD's
  "restaurants table as cache". Treat it as a short-lived cache; real mark in the provider decision.

## Google Cloud setup (done, in the console)

- Project **"My First Project"** (`project-115f1bbe-3ecf-4118-91c`), acct ericre123456@gmail.com,
  **$300 free trial** active (~90 days).
- Enabled **exactly** Places API (New) + Geocoding — unchecked the wizard's "enable all 35 Maps
  APIs" default.
- API key **`restaurant-app-backend-dev`** restricted to those 2 APIs (App restrictions = None,
  a deliberate dev tradeoff; switch to IP on deploy).
- **Budget** "Maps API monthly budget" = $10/mo, email alerts at 50/90/100% ($5/$9/$10).
- **Quota hard-caps: BLOCKED on the free trial** — per-day quota limits require upgrading to a
  paid account (console tooltip confirmed). Deferred until upgrade; budget alert is the interim guard.

## Backend: `.env` support (new)

- `backend/app/__init__.py` now `load_dotenv(backend/.env)` on package import — **absolute path**
  (CWD-independent, same lesson as `db.py`'s absolute DB path), **`override=False`** (shell vars +
  the test harness's `DATABASE_URL` still win), and a **no-op if python-dotenv is missing**.
- Added `python-dotenv` to requirements; added **`.env` to `backend/.gitignore`** (it was NOT
  ignored before — a leak gap); committed `backend/.env.example`; created the gitignored `.env`.
- Verified: `.env` loads into `os.getenv`, a shell var overrides it, SQLite default intact (empty
  `DATABASE_URL` stays commented so it can't clobber the default), `.env` gitignored.

## Backend: Google Places provider (scaffolded, NOT wired in)

- `backend/app/providers/google_places.py` —
  `retrieve(query, constraints, *, api_key=None, client=None)` calls Text Search (New)
  `places:searchText`, maps results to the **exact seed-dict shape `recommender._to_seed_dict`
  produces** (drop-in for `_sql_retrieve`), refines the exact radius in Python (prototype
  `haversine_km`), and pre-ranks rating desc / count desc / id asc. Reuses `proto` via `_proto`.
  Enterprise `FIELD_MASK`; `GooglePlacesError` on missing key / API error. Smoke CLI:
  `python -m app.providers.google_places "..." --near-lat --near-lng --price-max`.
- `tests/test_google_places.py` — **12 offline tests** (httpx `MockTransport`, no key/network):
  request building, seed-dict mapping, radius refine, prerank tiebreakers, cap, field-mask/key
  headers (asserts `reviews` never in the mask), missing-key + HTTP-error paths.
- **Not wired into `recommender.recommend()`** — Google-vs-Yelp source selection and the
  caching-to-`restaurants`-table question are still open decisions.

## Browser-automation / ops notes

- **The console was flaky all session** — repeated "Failed to load" (Retry fixed each), and the
  key-edit toolbar's "Rotate key" button was clipped under the trial banner so automated clicks
  wouldn't land.
- **Key-exposure incident, handled:** the user pasted the auto-created key into chat, then a
  too-early screenshot captured the recreated key too. Policy applied (user chose): delete &
  recreate. Net: the final key **still needs the user to rotate it** and paste the new value —
  I deliberately never screenshot the reveal dialog (would re-log the secret); verified dialog
  state via tab title instead.

## State at session end

- Backend suite: **103 passed** (91 → 103; +12 provider tests). Full suite green.
- **Uncommitted** working-tree changes on `master`: `backend/app/__init__.py`,
  `backend/{.gitignore,requirements.txt}`, new `backend/.env.example`,
  `backend/app/providers/{__init__,google_places}.py`, `backend/tests/test_google_places.py`.
  (`.env` itself is gitignored/untracked.) No PR opened.
- Memory updated: [[google-maps-integration]], [[env-support-and-google-provider-scaffold]];
  old `todo-research-google-maps-api` marked done.

## Next up

1. **User action:** rotate the exposed key in the console, paste into `backend/.env`, run the
   smoke CLI to confirm a live Text Search returns Philadelphia candidates.
2. Commit/PR this session's scaffold (not yet done).
3. Decide **Google vs Yelp** as the live source and **wire the provider into `recommend()`**
   behind a source toggle (e.g. `RECS_PROVIDER=google|seed`).
4. Sync PRD/TDD/KNOWN_ISSUES with the provider decision + the caching-ToS constraint.
5. On paid-account upgrade: set the per-day quota hard-caps that the free trial blocked.
