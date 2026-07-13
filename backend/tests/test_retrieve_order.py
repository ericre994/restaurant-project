"""Stage-1 retrieval pre-rank order is deterministic: rating, then review volume,
then id as a stable tiebreaker. This keeps results reproducible across runs and
makes the prototype's retrieve() match the backend's _sql_retrieve ORDER BY
exactly (not merely the same candidate set).
"""
from app._proto import proto


def _r(rid, rating, count):
    return {
        "id": rid, "name": rid, "rating": rating, "rating_count": count,
        "categories": [], "location": {"type": "Point", "coordinates": [0.0, 0.0]},
    }


def test_orders_by_rating_then_volume_then_id():
    seed = [_r("c", 4.5, 100), _r("a", 4.5, 100), _r("b", 4.5, 100),
            _r("z", 5.0, 10), _r("y", 4.5, 200)]
    out = proto.retrieve(seed, proto.Constraints())
    ids = [r["id"] for r in out]
    # 5.0 first; then 4.5/200 outranks 4.5/100; the 4.5/100 ties break by id asc.
    assert ids == ["z", "y", "a", "b", "c"]


def test_tie_order_is_independent_of_input_order():
    base = [_r("a", 4.0, 50), _r("b", 4.0, 50), _r("d", 4.0, 50)]
    forward = [r["id"] for r in proto.retrieve(list(base), proto.Constraints())]
    backward = [r["id"] for r in proto.retrieve(list(reversed(base)), proto.Constraints())]
    assert forward == backward == ["a", "b", "d"]
