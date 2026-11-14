"""Explainer Agent: turns computed facts into a short explanation for an audience.

Template path: deterministic text built only from `facts` (always verifiable).
LLM path (optional): same facts, strict instructions. Its output must pass the
Verifier or the orchestrator discards it and uses the template.
"""
from __future__ import annotations

import json

from . import llm

SYSTEM = (
    "You explain lunar landing-site analysis results. Use ONLY the facts in the JSON provided. "
    "Do not introduce any number, date, site name or label that is not in the JSON. "
    "Write dates exactly as YYYY-MM-DD. Keep hours as hours and percents as percents; do not convert units. "
    "Mention the data caveats briefly. Max 140 words. No markdown headings."
)
AUDIENCE = {
    "planner": "Audience: a mission planner. Be concise and quantitative.",
    "public": "Audience: curious members of the public. Use plain language and no jargon; explain what "
              "'power + comms' means once.",
}


def _pct(x):
    return f"{x:.0f}%"


def _days(d):
    return f"{d:g} day" if abs(d - 1) < 1e-9 else f"{d:g} days"


def _h(x):
    return f"{x:.0f} h"


def template(facts: dict, mode: str = "planner") -> str:
    rank = facts["ranking"]
    if not rank:
        return "No windows could be computed for this request."
    best = rank[0]
    m = best["metrics"]
    u = best.get("uncertainty")
    lines = []
    if mode == "public":
        lines.append(
            f"The best match is {best['site_name']}, starting {best['start']} and lasting "
            f"{_days(facts['request']['duration_days'])}. In that time the lander would have sunlight "
            f"for {_pct(m['power_pct'])} of the hours and a direct radio line to Earth for "
            f"{_pct(m['comms_pct'])}. Hours with both at once ('power + comms') make up "
            f"{_pct(m['both_pct'])}.")
        lines.append(f"The longest stretch without sunlight is {_h(m['longest_dark_h'])}, "
                     f"and the longest stretch without a link to Earth is {_h(m['longest_comms_gap_h'])}.")
    else:
        lines.append(
            f"Best: {best['site_name']}, {best['start']} to {best['end']} "
            f"(objective {facts['request']['objective']}): power {_pct(m['power_pct'])}, "
            f"comms {_pct(m['comms_pct'])}, both {_pct(m['both_pct'])}; longest dark stretch "
            f"{_h(m['longest_dark_h'])}, longest comms gap {_h(m['longest_comms_gap_h'])}.")
    if u:
        lines.append(
            f"Allowing for terrain error, 'both' time ranges from {_pct(u['both_p10'])} to "
            f"{_pct(u['both_p90'])} (10th to 90th percentile), so this window is {u['robustness']}.")
    if not best.get("feasible", True):
        lines.append("No window satisfies the battery limit; this is the least-bad option.")
    if len(rank) > 1:
        others = "; ".join(
            f"{r['site_name']} {r['start']} (both {_pct(r['metrics']['both_pct'])})" for r in rank[1:4])
        lines.append(f"Next best: {others}.")
    hf = best.get("mast")
    if hf:
        if hf["is_flip"]:
            lines.append(f"Raising the mast from {hf['from_height_m']:g} m to {hf['to_height_m']:g} m adds "
                         f"{hf['jump_pct']:.0f} percentage points of 'both' time at this site.")
        else:
            lines.append(f"Mast height between 0 m and 15 m changes 'both' time by only "
                         f"{hf['total_gain_pct']:.0f} percentage points here.")
    for c in facts["caveats"][:3]:
        lines.append(c)
    return " ".join(lines)


def run(facts: dict, mode: str = "planner", transport=None) -> dict:
    """Returns {text, source}. `source` is 'llm' or 'template'."""
    if llm.llm_available():
        user = AUDIENCE.get(mode, AUDIENCE["planner"]) + "\nFACTS:\n" + json.dumps(facts, default=str)
        text = llm.complete(SYSTEM, user, 500, transport)
        if text:
            return {"text": text, "source": "llm"}
    return {"text": template(facts, mode), "source": "template"}
