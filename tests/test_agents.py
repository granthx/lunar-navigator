import json

import pytest

from backend.agents import explainer, llm, query, verifier
from backend.dem import synthetic_dem
from backend.orchestrator import run_copilot
from backend.service import Service, ServiceError
from backend.sites import make_demo_sites

SITES = [{"id": f"demo_{c}", "name": f"Demo Site {c.upper()}"} for c in "abcde"]
TODAY = "2026-11-04"


@pytest.fixture(scope="module")
def svc():
    dem = synthetic_dem(size_px=500, px_m=200.0)
    return Service(dem, make_demo_sites(dem))


# ----------------------------------------------------------------- Query Agent
def test_query_durations_not_confused_by_the_word_and():
    r, _ = query.rule_parse("compare site a and site b for a 14-day mission, battery lasts 36 hours", SITES, TODAY)
    assert r["duration_h"] == 336 and r["battery_h"] == 36 and r["objective"] == "survive"
    assert r["site_ids"] == ["demo_a", "demo_b"]
    r, _ = query.rule_parse("best comms between 2027-02-01 and 2027-05-01 for 7 days", SITES, TODAY)
    assert r["duration_h"] == 168 and r["objective"] == "comms"
    assert (r["start"], r["end"]) == ("2027-02-01", "2027-05-01")


def test_query_defaults_are_reported_as_assumptions():
    r, a = query.rule_parse("which site is best?", SITES, TODAY)
    text = " ".join(a)
    assert "all sites" in text and "14 days" in text and "mast height" in text and "365 days" in text
    assert r["duration_h"] == 14 * 24 and r["height_m"] == 0.0


def test_query_antenna_height_is_not_a_comms_priority():
    r, _ = query.rule_parse("two week mission, power matters, antenna at 3 meters", SITES, TODAY)
    assert r["objective"] == "power" and r["height_m"] == 3.0
    capped = query.run("use a 30 m mast for 7 days at site a", SITES, TODAY)
    assert capped["request"]["height_m"] == 15.0
    assert any("15 m" in n and "maximum" in n for n in capped["assumptions"]), capped["assumptions"]


def test_query_month_and_battery_default():
    r, a = query.rule_parse("can we survive a 10 day mission in march?", SITES, TODAY)
    assert r["battery_h"] == 48.0 and r["start"] == "2027-03-01"
    assert any("battery" in x for x in a) and any("March" in x for x in a)


def test_normalize_rejects_unknown_sites_and_bad_dates():
    ids = [s["id"] for s in SITES]
    out = query.normalize_request({"site_ids": ["nope"], "start": "2027-01-01", "end": "2027-02-01",
                                   "objective": "weird"}, ids)
    assert out["site_ids"] == ids and out["objective"] == "balanced"
    notes = []
    out = query.normalize_request({"site_ids": ["demo_a"], "start": "2027-01-01",
                                   "end": "2027-02-01", "height_m": 30}, ids, notes)
    assert out["height_m"] == 15.0 and any("15 m" in n for n in notes)
    with pytest.raises(ValueError):
        query.normalize_request({"site_ids": [], "start": "garbage", "end": "2027-02-01"}, ids)


def test_query_llm_path_with_fake_transport(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    payload = {"site_ids": ["demo_b"], "start": "2027-01-01", "end": "2027-03-01", "duration_h": 100,
               "objective": "power", "battery_h": None, "height_m": 2, "assumptions": ["assumed X"]}

    def transport(url, headers, body):
        assert headers["x-api-key"] == "test-key"
        return json.dumps({"content": [{"type": "text", "text": "```json\n" + json.dumps(payload) + "\n```"}]}).encode()

    out = query.run("anything", SITES, TODAY, transport)
    assert out["path"] == "llm" and out["request"]["site_ids"] == ["demo_b"]
    assert out["assumptions"] == ["assumed X"]


def test_query_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(url, headers, body):
        raise OSError("network down")

    out = query.run("compare site a and b for 5 days", SITES, TODAY, boom)
    assert out["path"] == "rules" and out["request"]["site_ids"] == ["demo_a", "demo_b"]


def test_llm_disabled_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert llm.complete("s", "u") is None and not llm.llm_available()


# ------------------------------------------------------------------- Verifier
FACTS = {
    "request": {"duration_h": 240, "duration_days": 10},
    "ranking": [{"site_name": "Demo Site A", "start": "2027-03-12", "start_iso": "2027-03-12T00:00",
                 "metrics": {"both_pct": 72.4, "power_pct": 100.0},
                 "uncertainty": {"robustness": "fragile", "both_p10": 16.0}}],
    "caveats": ["Note: the terrain model ends before 30 km at some sites."],
}
NAMES = ["Demo Site A", "Demo Site B"]


def test_verifier_accepts_backed_text():
    t = "Demo Site A on 2027-03-12 gives both 72% (72.4 exactly), power 100%, a fragile window; 10 days."
    v = verifier.verify(t, FACTS, NAMES)
    assert v["verified"] and v["scope"] == "value_presence", v


def test_verifier_rejects_invented_number():
    v = verifier.verify("Demo Site A gives both 85% of the time.", FACTS, NAMES)
    assert not v["verified"] and "85" in v["unmatched_numbers"]


def test_verifier_rejects_wrong_date_site_and_label():
    v = verifier.verify("Demo Site A on 2027-04-01 is robust.", FACTS, NAMES)
    assert "2027-04-01" in v["unbacked_dates"] and "robust" in v["unbacked_labels"]
    v = verifier.verify("Demo Site B is best.", FACTS, NAMES)
    assert "Demo Site B" in v["unknown_sites"]


def test_verifier_allows_numbers_quoted_from_caveat_text():
    assert verifier.verify("Terrain model ends before 30 km.", FACTS, NAMES)["verified"]


# ---------------------------------------------------------------- Orchestrator
def test_copilot_template_path_is_verified(svc, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = run_copilot(svc, "which site is best for a 10 day mission in march? power matters", "planner", TODAY)
    assert r["explanation"]["source"] == "template" and r["verification"]["verified"]
    assert r["ranking"] and r["ranking"][0]["rank"] == 1
    assert [t["agent"] for t in r["trace"]][0] == "Query Agent" and r["trace"][-1]["agent"] == "Verifier"
    r2 = run_copilot(svc, "explain for the public: best site for 7 days, comms", "public", TODAY)
    assert r2["verification"]["verified"] and "radio line" in r2["explanation"]["text"] or "link" in r2["explanation"]["text"]


def test_copilot_discards_hallucinating_llm(svc, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    calls = {"n": 0}

    def transport(url, headers, body):
        calls["n"] += 1
        sysmsg = json.loads(body)["system"]
        if "convert a mission planner" in sysmsg:     # Query Agent: valid JSON
            p = {"site_ids": ["demo_a", "demo_b"], "start": "2027-01-01", "end": "2027-04-01",
                 "duration_h": 168, "objective": "balanced", "battery_h": None, "height_m": 0,
                 "assumptions": []}
            return json.dumps({"content": [{"type": "text", "text": json.dumps(p)}]}).encode()
        return json.dumps({"content": [{"type": "text",
                                        "text": "Demo Site A will get 99.9% power with a 777 hour margin."}]}).encode()

    r = run_copilot(svc, "compare a and b", "planner", TODAY, transport)
    assert r["query_path"] == "llm"
    assert r["llm_rejected"] is not None                      # hallucination caught
    assert r["explanation"]["source"] == "template" and r["verification"]["verified"]
    assert "999" not in r["explanation"]["text"]


def test_service_input_errors_are_clear(svc):
    assert svc.meta()["max_height_m"] == 15.0
    with pytest.raises(ServiceError):
        svc.windows("demo_a", "2027-03-01", "2027-03-05", 24 * 20)
    with pytest.raises(ServiceError):
        svc.site("nope")
    with pytest.raises(ServiceError):
        svc.series("demo_a", "2027-01-01", "2029-01-01")
    with pytest.raises(ServiceError):
        svc.series("demo_a", "2027-01-01", "2027-01-02", step_h=48)
    with pytest.raises(ServiceError):
        svc.horizon("demo_a", 30)
    with pytest.raises(ServiceError):
        svc.height("demo_a", "2027-01-01", "2027-01-03", heights=(0, 30))
    one = svc.height("demo_a", "2027-01-01", "2027-01-03", heights=(5,))
    assert len(one["rows"]) == 1 and one["rows"][0]["height_m"] == 5.0
    with pytest.raises(ServiceError):
        svc.windows("demo_a", "2027-03-01", "2027-04-01", 48, objective="survive")
