"""Unit tests for the data-derived neighborhood/ZIP resolver (prototype GeoIndex).

The seed has no neighborhood field, so we resolve a place name to a search
center from the coordinates of the restaurants in the relevant ZIP(s). These
tests build tiny indexes from synthetic points, then validate against the real
Philadelphia seed that the derived centroids reproduce the old hardcoded
landmarks (within 1 km) — the regression guarding the whole method.
"""
import json
from pathlib import Path

import pytest

from app._proto import proto


def test_zip_of_parses_trailing_zip():
    assert proto.zip_of("935 Race St, Philadelphia, PA, 19107") == "19107"
    assert proto.zip_of("1 Main St, Town, PA, 19104-1234") == "19104"
    assert proto.zip_of(None) is None
    assert proto.zip_of("no zip in this string") is None


def test_zip_centroid_is_mean_of_points():
    pts = [("19107", 39.95, -75.15), ("19107", 39.97, -75.17),
           ("19104", 39.95, -75.19)]
    idx = proto.build_geo_index(pts)
    assert idx.resolve("19107") == pytest.approx((39.96, -75.16))
    assert idx.resolve("19104") == pytest.approx((39.95, -75.19))


def test_neighborhood_resolves_from_its_zips():
    pts = [("19107", 39.955, -75.155), ("19107", 39.957, -75.157)]
    idx = proto.build_geo_index(pts)  # chinatown -> ["19107"]
    assert "chinatown" in idx.place_names
    assert idx.resolve("chinatown") == pytest.approx((39.956, -75.156))


def test_alias_with_absent_zips_is_dropped():
    # manayunk -> 19127, absent from these points, so it must not resolve.
    idx = proto.build_geo_index([("19107", 39.955, -75.155)])
    assert "manayunk" not in idx.place_names
    assert idx.resolve("manayunk") is None


def test_fuzzy_matches_a_near_miss_name():
    idx = proto.build_geo_index([("19125", 39.97, -75.13)])  # fishtown
    assert idx.resolve("fishtwon") == idx.resolve("fishtown")


def test_unknown_and_empty_return_none():
    idx = proto.build_geo_index([("19107", 39.955, -75.155)])
    assert idx.resolve("atlantis") is None
    assert idx.resolve("") is None


_SEED = (Path(__file__).resolve().parents[2]
         / "YelpData" / "output" / "restaurants_Philadelphia_schema.json")


@pytest.mark.skipif(not _SEED.exists(), reason="Philadelphia seed not built")
def test_derived_centroids_reproduce_hardcoded_landmarks():
    seed = json.loads(_SEED.read_text(encoding="utf-8"))
    idx = proto.geo_index_from_seed(seed)
    # Each historical landmark still resolves, within 1 km of its old hand-picked
    # coordinate — the data-derived method matches the manual centroids.
    for name, old in proto.LANDMARKS.items():
        got = idx.resolve(name)
        assert got is not None, f"{name} did not resolve"
        drift = proto.haversine_km(old, got)
        assert drift <= 1.0, f"{name}: derived centroid {drift:.2f} km off"
    # A bare ZIP and a neighborhood the old table lacked both resolve now.
    assert idx.resolve("19107") is not None
    assert idx.resolve("northern liberties") is not None
