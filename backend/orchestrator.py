"""Copilot orchestrator: Query Agent -> analysis tools -> Explainer -> Verifier.

Every step is recorded in `trace`, which the UI shows as the "why" trail.
"""
from __future__ import annotations

import time

from .agents import explainer, query, verifier
from .service import Service, ServiceError, today_utc


def _step(trace, agent, action, detail, t0):
    trace.append({"agent": agent, "action": action, "detail": detail,
                  "ms": int((time.time() - t0) * 1000)})


def run_copilot(svc: Service, message: str, mode: str = "planner", today: str | None = None,
                transport=None) -> dict:
    trace: list[dict] = []
    today = today or today_utc()
    meta = svc.meta()

    # 1. Query Agent
    t0 = time.time()
    q = query.run(message, meta["sites"], today, transport)
    req, assumptions = q["request"], q["assumptions"]
    _step(trace, "Query Agent", f"parsed request ({q['path']})",
          {"sites": req["site_ids"], "start": req["start"], "end": req["end"],
           "duration_h": req["duration_h"], "objective": req["objective"],
           "battery_h": req["battery_h"], "height_m": req["height_m"]}, t0)

    # 2. Analysis tools (deterministic) for every site
    ranking, notes_edge = [], False
    for sid in req["site_ids"]:
        t0 = time.time()
        res = svc.windows(sid, req["start"], req["end"], req["duration_h"], req["objective"],
                          req["battery_h"], req["height_m"], 1.0, 3, True)
        notes_edge = notes_edge or res["data_notes"]["edge_limited"]
        _step(trace, "Window tool", f"searched windows at {svc.site(sid).name}",
              {"windows_found": len(res["windows"]), "samples": res["n_samples"]}, t0)
        if not res["windows"]:
            continue
        w = res["windows"][0]
        t0 = time.time()
        hs = svc.height(sid, req["start"], req["end"], None, w["start_index"], w["end_index"])
        both = [r["both_pct"] for r in hs["rows"]]
        jump = hs["biggest_jumps"]["both_pct"]
        _step(trace, "Height tool", f"mast sweep at {svc.site(sid).name}",
              {"heights_m": [r["height_m"] for r in hs["rows"]], "both_pct": [round(b, 1) for b in both]}, t0)
        u = w.get("uncertainty")
        ranking.append({
            "site_id": sid, "site_name": svc.site(sid).name,
            "start": w["start"][:10], "end": w["end"][:10],
            "start_iso": w["start"], "end_iso": w["end"],
            "start_index": w["start_index"], "end_index": w["end_index"],
            "score": round(w["score"], 4), "feasible": w["feasible"],
            "metrics": w["metrics"],
            "uncertainty": None if not u else {
                "both_p10": u["both_pct"]["p10"], "both_p50": u["both_pct"]["p50"],
                "both_p90": u["both_pct"]["p90"], "robustness": u["robustness"]},
            "mast": {"is_flip": jump["is_flip"], "from_height_m": jump["from_height_m"],
                     "to_height_m": jump["to_height_m"], "jump_pct": jump["jump_pct"],
                     "total_gain_pct": abs(both[-1] - both[0]),
                     "min_height_m": hs["rows"][0]["height_m"], "max_height_m": hs["rows"][-1]["height_m"]},
        })

    # 3. Ranker (deterministic): feasible first, then score
    t0 = time.time()
    ranking.sort(key=lambda r: (r["feasible"], r["score"]), reverse=True)
    for i, r in enumerate(ranking, 1):
        r["rank"] = i
    _step(trace, "Ranker", "ranked sites by best window", {"order": [r["site_name"] for r in ranking]}, t0)

    caveats = []
    if meta["synthetic"]:
        caveats.append("Note: terrain is synthetic demo data, not real lunar terrain.")
    if meta.get("ephemeris_backend") == "spice":
        caveats.append("Note: Sun and Earth positions use SPICE DE440.")
    else:
        caveats.append("Note: Sun and Earth positions use an analytical ephemeris, not SPICE.")
    if notes_edge:
        caveats.append("Note: the terrain model ends before 30 km at some sites, so distant ridges may be missing.")
    caveats.append("Note: uncertainty covers terrain-height error only.")

    facts = {
        "request": {"site_names": [svc.site(s).name for s in req["site_ids"]], "start": req["start"],
                    "end": req["end"], "duration_h": req["duration_h"],
                    "duration_days": req["duration_h"] / 24.0, "objective": req["objective"],
                    "battery_h": req["battery_h"], "height_m": req["height_m"]},
        "ranking": ranking, "uncertainty_percentiles": [10, 90], "caveats": caveats,
    }

    # 4. Explainer + 5. Verifier (LLM text is discarded unless it verifies)
    names = [s["name"] for s in meta["sites"]]
    t0 = time.time()
    ex = explainer.run(facts, mode, transport)
    ver = verifier.verify(ex["text"], facts, names)
    _step(trace, "Explainer", f"wrote explanation ({ex['source']})", {"chars": len(ex["text"])}, t0)
    llm_rejected = None
    if not ver["verified"] and ex["source"] == "llm":
        llm_rejected = {"issues": ver}
        ex = {"text": explainer.template(facts, mode), "source": "template"}
        ver = verifier.verify(ex["text"], facts, names)
    _step(trace, "Verifier", "checked explanation against data",
          {"verified": ver["verified"], "numbers_checked": ver["numbers_checked"],
           "dates_checked": ver["dates_checked"]}, time.time())

    return {
        "request": req, "assumptions": assumptions, "query_path": q["path"],
        "ranking": ranking, "explanation": ex, "verification": ver,
        "llm_rejected": llm_rejected, "caveats": caveats, "trace": trace,
        "view": {"site_ids": req["site_ids"], "start": req["start"], "end": req["end"],
                 "duration_h": req["duration_h"], "objective": req["objective"],
                 "battery_h": req["battery_h"], "height_m": req["height_m"]},
    }


__all__ = ["run_copilot", "ServiceError"]
