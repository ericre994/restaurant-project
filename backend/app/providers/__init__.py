"""External restaurant-data providers.

Each provider exposes a Stage-1 ``retrieve`` that returns the same *seed-dict*
shape the recommendation pipeline consumes (see ``recommender._to_seed_dict``),
so a provider is a drop-in alternative to the SQL/seed retrieval path. The
prototype's rank/render stages stay untouched regardless of source.
"""
