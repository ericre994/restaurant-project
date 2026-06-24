# Recommendation pipeline prototype

A runnable, no-database prototype of the **retrieve → rank → render** pipeline
that the technical design doc calls the central technical bet. Its only job is
to answer one question cheaply: *do the AI recommendations actually feel like
"a friend who knows you"?* If yes, the rest is engineering (Postgres, auth,
jobs). If no, you learned it in an afternoon.

It runs against the Philadelphia seed (`../YelpData/output/restaurants_Philadelphia_schema.json`)
— the same records, same schema you'll load into the `restaurants` table.

## Quickstart

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...      # Windows: set ANTHROPIC_API_KEY=...
cd prototype

python recommend.py --demo date_night
python recommend.py --demo cheap_eats
python recommend.py --demo group_dinner

# free-form, with hard filters
python recommend.py --query "late-night noodles, casual, solo" \
                    --near chinatown --price-max 2 --cuisine Noodles Chinese
```

No API key? It still runs and shows Stage 1 retrieval with a rating-sorted
fallback, so you can sanity-check the candidate filtering on its own.

Want to see the Stage 2 **ranking** path (scored picks, JSON render) without a
key or network? Set `FAKE_LLM=1` for deterministic, schema-valid fake responses:

```bash
FAKE_LLM=1 python recommend.py --demo cheap_eats   # renders "ranking: llm"
```

## What it does (maps 1:1 to the design doc)

| Stage | Design doc §  | In this prototype |
|-------|---------------|-------------------|
| 1. Retrieve | 4.1 / 4.2 | Hard-filters seed by location radius (haversine), price band, cuisine, open-hours; pre-ranks by rating; **caps at 18** candidates. |
| 2. Rank | 4.1.1 | Assembles the exact system/user prompt from the doc, sends **only compact candidate records**, temperature 0, strict-JSON ask. |
| 3. Render | 4.1.2 | Validates JSON, **drops any id not in the candidate set** (hallucination guard), one **repair retry**, then **falls back** to rating order. Prints result cards. |

`TasteProfile` and `Constraints` stand in for the `taste_profiles` row and
request context; `PROMPT_VERSION` is logged-in-spirit so quality changes stay
attributable.

## Output shape (illustrative — actual names come from your seed)

```
Loaded 5xxx restaurants from seed.
Stage 1: 18 candidates after hard filters (cap 18).

================================================================
  Recommendations  (ranking: llm)
================================================================

1. <Restaurant from your seed>   [92/100]
   $$$ · Italian, Wine Bars
   4.5★ (612)  ·  <address from seed>
   → Intimate, wine-forward room matches your date-night, quiet preference
   → $$$ sits right in your stated price comfort zone
...
```

(The one real seed row I can confirm by eye is *St Honore Pastries*, a $ bakery
in Chinatown — it surfaces for the `cheap_eats` demo.)

## How to judge the result

This prototype is a measurement tool. After a few queries, ask:

- Do the **reasons** reference *this* diner's profile, or are they generic?
- Does changing the taste profile actually change the ranking?
- Are the **hard filters** doing real work (right neighborhood, price, open)?
- Does the **fallback** path produce something tolerable when the LLM is off?

## Important caveats (from the project docs)

- **Data is dev-only.** The Yelp Open Dataset is academic-use-only (see
  `YelpData/docs/`). Fine for this prototype; you cannot ship on it.
- **City mismatch.** This seed is *Philadelphia*; the PRD launch market is
  *NYC*. The pipeline is city-agnostic — only the seed changes — but production
  needs the Google Places vs. Yelp Fusion decision (PRD open question #1).
- **No embeddings yet.** Stage 1 pre-ranks by rating as a stand-in for the
  pgvector step; `embedding` is still `null` in the seed.

## Suggested next steps after this

1. Run the demos; tune the prompt / candidate fields until reasons feel sharp.
2. Port `retrieve()` to a SQL query against the real `restaurants` table.
3. Generate seed embeddings; swap the rating pre-rank for pgvector similarity.
4. Wrap `rank()` behind the `POST /recommendations` endpoint.
