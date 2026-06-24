"""Exercises the mode='llm' path using the prototype's local fake LLM (FAKE_LLM=1).

No API key, no network — deterministic, schema-valid LLM responses. This covers
the branches the fallback-mode tests can't: JSON parse, scored picks, llm_model
logging, and LLM taste summaries.
"""
import pytest

from app._proto import proto


@pytest.fixture
def fake_llm(monkeypatch):
    # Reads via os.getenv at call time, so setting it here is enough; monkeypatch
    # reverts it after each test so other test files stay in fallback mode.
    monkeypatch.setenv("FAKE_LLM", "1")


def test_recommendation_runs_in_llm_mode(client, fake_llm):
    body = client.post("/recommendations", json={"query": "tasty"}).json()
    assert body["mode"] == "llm"
    assert body["picks"]
    # The fake returns integer match scores in descending order.
    scores = [p["match_score"] for p in body["picks"]]
    assert all(isinstance(s, int) for s in scores)
    assert scores == sorted(scores, reverse=True)


def test_llm_mode_records_model_in_log(client, fake_llm):
    rec = client.post("/recommendations", json={"query": "tasty"}).json()
    log = client.get(f"/recommendations/{rec['recommendation_id']}").json()
    # llm_model is populated only when the LLM path actually ran.
    assert log["llm_model"] == proto.MODEL


def test_hallucination_guard_holds_in_llm_mode(client, fake_llm):
    body = client.post("/recommendations", json={"query": "tasty"}).json()
    shown = {p["restaurant_id"] for p in body["picks"]}
    assert shown <= {"r1", "r2", "r3"}  # only ever real candidates


def test_taste_summary_uses_llm(client, fake_llm):
    h = {"X-User-Id": "llm-taste-user"}
    client.post("/visits", headers=h, json={"restaurant_id": "r1", "sentiment": "loved"})
    profile = client.get("/me/taste-profile", headers=h).json()
    assert profile["derived_summary"].startswith("fake-llm:")


def test_hallucinated_id_is_dropped(client, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "hallucinate")
    body = client.post("/recommendations", json={"query": "tasty"}).json()
    # The bogus id is dropped by the guard; valid picks still come through.
    assert body["mode"] == "llm"
    ids = {p["restaurant_id"] for p in body["picks"]}
    assert proto._FAKE_HALLUCINATED_ID not in ids
    assert ids and ids <= {"r1", "r2", "r3"}


def test_malformed_json_triggers_repair(client, monkeypatch):
    monkeypatch.setenv("FAKE_LLM", "malformed")
    body = client.post("/recommendations", json={"query": "tasty"}).json()
    # First call returns bad JSON; the one-shot repair retry recovers it.
    assert body["mode"] == "llm-repair"
    assert body["picks"]
