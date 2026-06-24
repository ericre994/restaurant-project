# Product Requirements Document

## Restaurant Discovery & Management App

**Version:** 0.1 (Draft)
**Author:** Eric
**Last updated:** June 12, 2026
**Status:** In review

---

## 1. Overview

### 1.1 Summary

A mobile-first app that helps food-curious diners track restaurants they want to try, get genuinely personalized AI-powered recommendations, and act on those recommendations through reservation availability alerts and booking links.

### 1.2 Problem statement

Diners today scatter restaurant intent across screenshots, notes apps, Google Maps stars, and group chats. When it's time to actually pick a place, they face two failure modes:

1. **Retrieval failure:** "I know I saved a place for this exact occasion, but I can't find it."
2. **Generic recommendations:** Discovery platforms optimize for popularity and ads, not for the individual's taste, occasion, party size, or context. Recommendations feel interchangeable.

There is no single product that closes the loop from *intent* (want to try) → *decision* (personalized recommendation) → *action* (reservation).

### 1.3 Product vision

Be the system of record for a user's dining life: a place where saved intent compounds into a taste profile, and that taste profile powers recommendations that feel like they came from a friend who knows you, then gets you a table.

---

## 2. Goals & Non-Goals

### 2.1 Goals (MVP)

- Let users capture and organize restaurant intent with near-zero friction
- Deliver AI recommendations that demonstrably use the user's taste profile and current context (occasion, party size, time)
- Notify users when reservations open up at saved restaurants
- Establish the data foundation (taste profiles, visit history) that improves recommendation quality over time

### 2.2 Non-goals (MVP)

- Direct in-app booking (deep-link to Resy/OpenTable instead; native booking via API partnership is a post-MVP goal)
- Social features beyond basic list sharing (full social/engagement layer is Phase 2)
- Restaurant-side tools (owner dashboards, promoted placement)
- Reviews/ratings as a public content product (visit notes are private in MVP)
- International coverage (launch market: NYC)

---

## 3. Target Users


| Persona                     | Description                                                                        | Primary jobs-to-be-done                                           |
| --------------------------- | ---------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| **The List Keeper**         | Saves restaurants constantly from Instagram, TikTok, friends. Has 40+ screenshots. | "Get my saved places out of chaos and into something searchable." |
| **The Occasion Planner**    | Books for dates, birthdays, visiting parents. Decision anxiety is high.            | "Find the *right* place for this specific situation, fast."       |
| **The Hard-to-Book Hunter** | Chases reservations at buzzy spots. Checks Resy at 9am for drops.                  | "Tell me the moment a table opens at places I care about."        |


These overlap heavily; the same user is often all three in different moments.

---

## 4. Core Features (MVP)

### 4.1 List Management: Want-to-Try vs. Visited

The foundational data model distinguishes two states:

- **Want-to-Try:** captured intent. Supports tags (cuisine, neighborhood, occasion fit), source attribution ("saved from a friend," "saw on Instagram"), and free-text notes.
- **Visited:** completed experiences. On marking visited, a lightweight prompt captures a 1-tap sentiment (loved / liked / wouldn't return) and optional notes. This is the highest-signal input to the taste profile.

**Requirements**

- One-tap save from search results and recommendation cards
- Move between states in ≤2 taps
- Custom lists layered on top of the two core states (e.g., "Date Night," "Cheap Eats")
- Search and filter across all lists by cuisine, neighborhood, price, tags
- Restaurant records hydrated from the restaurant data API (hours, price level, photos, location)

### 4.2 AI-Powered Natural Language Recommendations

Users describe what they want in plain language ("cozy spot for a third date in the West Village, not too loud, under $$$") and get a ranked, reasoned short-list.

**Architecture (three-step pipeline)**

1. **Retrieval:** Query the restaurant data API (Google Places or Yelp Fusion, under evaluation) for candidate restaurants matching hard constraints (location, open hours, price band).
2. **Ranking & reasoning:** An LLM (Claude API) receives a static system prompt, the user's taste profile, contextual signals (occasion, party size, time of day), and the candidate set; it ranks candidates and generates a short "why this fits you" rationale per pick.
3. **Rendering:** The LLM returns a strict JSON schema that drives the recommendation card UI.

**Reliability requirements**

- Hallucination guard: the LLM may only rank/reason over candidates supplied in the prompt, and never invents restaurants. Output validated against the candidate ID list.
- JSON schema validation with retry-on-malformed-output; graceful fallback to a non-AI sorted list if the pipeline fails.
- Low temperature for ranking consistency.
- P95 end-to-end latency target: ≤6 seconds from query to rendered cards.

**Taste profile inputs (MVP)**

- Visited list + sentiment signals
- Want-to-try list composition (revealed preference)
- Explicit onboarding preferences (cuisines, dietary restrictions, price comfort zone)

### 4.3 Reservation Availability Alerts

Users flag any saved restaurant for alerts with desired party size, date range, and time window. The system polls availability and pushes a notification when a matching slot opens.

**Requirements**

- Alert setup in ≤3 taps from any restaurant detail page
- Notification deep-links directly to the booking page (Resy/OpenTable/restaurant site) with parameters pre-filled where the platform supports it
- Polling frequency tiered by demand (hot restaurants polled more often), with rate-limit compliance per platform
- Alert expiry and management UI ("you have 4 active alerts")

### 4.4 Reservation Deep-Linking

Every restaurant detail page surfaces a "Book" action that deep-links to the appropriate platform. Native booking via Resy/OpenTable API partnership is explicitly deferred to post-MVP (see Roadmap).

### 4.5 Weekly Recap and Newsletter

Generate a weekly round up / newsletter summarizing the user's interations with the app and any restaurants. In addition, provide a list of a few new reccomendations as well as events based on favorited restaurants.



---

## 5. Post-MVP Roadmap (directional) (TBD)

**Phase 2: Social & engagement layer**

- Shared lists and collaborative planning ("vote on Friday dinner")
- Friend taste-match ("you and Maya both loved...")
- Activity feed of friends' visits (opt-in)

**Phase 3: Native reservations & scale**

- Resy and/or OpenTable API partnership for in-app booking
- Vector embeddings for taste-profile matching at scale (replacing prompt-stuffed profiles)
- Pattern summarization of user history: periodically distill raw visit/save history into a compact preference summary to keep LLM context small and recommendations fast

---

## 6. Success Metrics


| Category               | Metric                                                       | MVP target (90 days post-launch) |
| ---------------------- | ------------------------------------------------------------ | -------------------------------- |
| Activation             | % of new users saving ≥3 restaurants in first week           | ≥50%                             |
| Core value             | % of recommendation sessions ending in a save or booking tap | ≥35%                             |
| Recommendation quality | Thumbs-up rate on recommendation cards                       | ≥60%                             |
| Alerts                 | Alert → booking-link tap conversion                          | ≥25%                             |
| Retention              | Week-4 retention                                             | ≥30%                             |
| Reliability            | AI pipeline error/fallback rate                              | <2% of sessions                  |


---

## 7. Technical Considerations

- **Restaurant data:** Google Places vs. Yelp Fusion under evaluation. Decision criteria: coverage in launch market, photo/hours data quality, pricing at projected query volume, ToS compatibility with caching restaurant records.
- **LLM layer:** Claude API for ranking/reasoning. Static system prompt + dynamic user message (taste profile, context, candidates) + enforced JSON output schema.
- **Cost control:** Cap candidate set size per query; cache recommendations for identical context windows; monitor per-recommendation cost as a first-class metric.
- **Privacy:** Taste profiles and visit history are personal data: encrypted at rest, never shared without explicit opt-in, exportable/deletable per GDPR/CCPA.
- **Availability polling:** Must respect platform rate limits and ToS; legal review of scraping vs. permitted endpoints required before launch.

---

## 8. Open Questions

1. Google Places vs. Yelp Fusion: which wins on launch-market coverage and unit economics?
2. What's the minimum viable taste profile at onboarding (cold-start problem): explicit quiz, import from Google Maps saves, or both?
3. Availability polling: is there a compliant data source for Resy/OpenTable availability pre-partnership, or does this feature require the partnership to ship?
4. Should "visited" auto-detect via location permissions (with consent), or stay fully manual in MVP?
5. Monetization direction (affects roadmap sequencing): subscription for alerts, booking referral fees, or defer entirely?

---

## 9. Risks & Mitigations


| Risk                                                               | Impact                                    | Mitigation                                                                                                           |
| ------------------------------------------------------------------ | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Availability data access blocked (no API, ToS-restricted scraping) | Kills the alerts feature                  | Validate data source compliance in week 1; have a fallback scope (alerts limited to platforms with permitted access) |
| Recommendations feel generic at cold start                         | Weak first impression of the core feature | Onboarding taste quiz + import flows; bias early recs toward explainability ("because you said you love Sichuan...") |
| LLM cost per recommendation too high at scale                      | Margin pressure                           | Candidate capping, caching, model-size tiering for simple queries                                                    |
| Restaurant data staleness (closures, hours)                        | Trust erosion                             | Refresh-on-view for detail pages; user-flagging mechanism                                                            |

