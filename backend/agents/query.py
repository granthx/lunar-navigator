"""Query Agent: plain English -> a structured, validated analysis request.

Two paths: an LLM path (if an API key is set) and a deterministic rule-based
parser used as the fallback. Whatever path is used, the result goes through the
same `normalize_request`, and every default the agent had to assume is returned
in `assumptions` so the UI can show it.
"""
from __future__ import annotations

import calendar
import json
import re
from datetime import date, timedelta

from . import llm

WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fourteen": 14}
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

DEFAULT_DURATION_H = 14 * 24
DEFAULT_BATTERY_H = 48.0


def _num(tok: str) -> float:
    tok = tok.lower()
    return float(WORD_NUM[tok]) if tok in WORD_NUM else float(tok)


_NUM = r"(?<![a-z0-9])(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twelve|fourteen)"
_UNIT_H = {"hour": 1, "hours": 1, "hr": 1, "hrs": 1, "h": 1, "day": 24, "days": 24, "d": 24,
           "week": 168, "weeks": 168, "wk": 168, "wks": 168}
_UNIT = r"(hours?|hrs?|h|days?|d|weeks?|wks?)"


def _valid(m, msg) -> bool:
    """Reject word-numbers glued to the next letters (e.g. 'an'+'d' inside 'and')."""
    tok = m.group(1)
    if tok[0].isdigit():
        return True
    return m.end(1) < len(msg) and msg[m.end(1)] in " -"


def _first(pattern: str, msg: str):
    for m in re.finditer(pattern, msg):
        if _valid(m, msg):
            return m
    return None


def _site_aliases(sites: list[dict]) -> dict:
    out = {}
    for s in sites:
        names = {s["id"].lower(), s["id"].lower().replace("_", " "),
                 re.sub(r"\(.*?\)", "", s["name"]).strip().lower()}
        last = re.sub(r"\(.*?\)", "", s["name"]).strip().lower().split()
        if last and len(last[-1]) == 1:
            names.add("site " + last[-1])
        out[s["id"]] = sorted((n for n in names if n), key=len, reverse=True)
    return out


def rule_parse(message: str, sites: list[dict], today: str) -> tuple[dict, list[str]]:
    msg = message.lower()
    assumptions: list[str] = []
    req: dict = {}

    # sites
    aliases = _site_aliases(sites)
    found = [sid for sid, names in aliases.items()
             if any(re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", msg) for n in names)]
    # "site a and b", "sites a, b and c": bare letters after the word 'site'
    letter_ids = {}
    for st in sites:
        toks = re.sub(r"\(.*?\)", "", st["name"]).strip().lower().split()
        if toks and len(toks[-1]) == 1:
            letter_ids[toks[-1]] = st["id"]
    for m in re.finditer(r"\bsites?\s+([a-z])\b((?:\s*(?:,|and|&|or)\s*[a-z]\b)*)", msg):
        for letter in [m.group(1)] + re.findall(r"\b[a-z]\b", m.group(2)):
            sid = letter_ids.get(letter)
            if sid and sid not in found:
                found.append(sid)
    if re.search(r"\b(all|every|each)\b.*\bsites?\b|\ball sites\b", msg) or not found:
        if not found:
            assumptions.append("No site was named, so all sites are compared.")
        found = [s["id"] for s in sites] if (not found or "all" in msg) else found
    req["site_ids"] = found

    # battery (before duration, so its number is not mistaken for the mission length)
    battery = None
    m = _first(r"battery[^.\d]{0,50}?" + _NUM + r"\s*[- ]?\s*" + _UNIT + r"\b", msg) or \
        _first(_NUM + r"\s*[- ]?\s*" + _UNIT + r"\s*(?:of\s*)?(?:battery|backup)", msg)
    span = None
    if m:
        battery = _num(m.group(1)) * _UNIT_H[m.group(2)]
        span = m.span()

    # duration
    duration = None
    for m in re.finditer(_NUM + r"\s*[- ]?\s*" + _UNIT + r"\b", msg):
        if not _valid(m, msg):
            continue
        if span and span[0] <= m.start() < span[1]:
            continue
        duration = _num(m.group(1)) * _UNIT_H[m.group(2)]
        break
    if duration is None:
        duration = DEFAULT_DURATION_H
        assumptions.append("No mission length was given, so 14 days is assumed.")
    req["duration_h"] = duration

    # objective
    wants_survive = bool(re.search(r"survive|surviv|battery|dark|night|eclipse", msg))
    power_kw = bool(re.search(r"power|solar|sunlight|energy|sun\b", msg))
    comms_kw = bool(re.search(r"comm|radio|link|direct.to.earth|earth contact|contact with earth", msg))
    if wants_survive:
        req["objective"] = "survive"
        if battery is None:
            battery = DEFAULT_BATTERY_H
            assumptions.append("No battery size was given, so 48 hours of battery is assumed.")
    elif power_kw and not comms_kw:
        req["objective"] = "power"
    elif comms_kw and not power_kw:
        req["objective"] = "comms"
    else:
        req["objective"] = "balanced"
    req["battery_h"] = battery

    # mast height
    height = 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter|metre)s?\s*(?:mast|tall|high|height|tower)", msg) or \
        re.search(r"(?:mast|height|antenna|tower)[^.\d]{0,25}?(\d+(?:\.\d+)?)\s*(?:m\b|meter|metre)", msg)
    if m:
        height = float(m.group(1))
    else:
        assumptions.append("No mast height was given, so ground level (0 m) is assumed.")
    req["height_m"] = height

    # dates
    t = date.fromisoformat(today)
    iso = re.findall(r"(\d{4}-\d{2}-\d{2})", msg)
    if len(iso) >= 2:
        req["start"], req["end"] = sorted(iso)[:2]
    elif len(iso) == 1:
        req["start"] = iso[0]
        req["end"] = (date.fromisoformat(iso[0]) + timedelta(days=int(duration / 24) + 60)).isoformat()
        assumptions.append("Only a start date was given, so the search covers it plus 60 days beyond the mission length.")
    else:
        mo = re.search(r"\b(?:in|during|for)\s+(january|february|march|april|may|june|july|august|"
                       r"september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b", msg)
        if mo:
            mi = MONTHS[mo.group(1)[:3] if mo.group(1) not in MONTHS else mo.group(1)]
            yr = t.year if (mi, 1) >= (t.month, 1) else t.year + 1
            start = date(yr, mi, 1)
            req["start"] = start.isoformat()
            req["end"] = (start + timedelta(days=31 + int(duration / 24) + 1)).isoformat()
            assumptions.append(f"'{mo.group(1).title()}' was read as {start.strftime('%B %Y')}; "
                               "the search covers that month plus the mission length.")
        else:
            req["start"] = t.isoformat()
            req["end"] = (t + timedelta(days=365)).isoformat()
            assumptions.append("No dates were given, so the next 365 days are searched.")
    return req, assumptions


SYSTEM = (
    "You convert a mission planner's request about lunar south-pole landing sites into JSON. "
    "Return ONLY a JSON object with keys: site_ids (list of ids from the provided list, or [] for all), "
    "start (YYYY-MM-DD), end (YYYY-MM-DD), duration_h (number), objective (one of balanced, power, comms, survive), "
    "battery_h (number or null), height_m (number), assumptions (list of short strings describing any value you "
    "had to assume because the user did not say). Never invent site ids. Never include any other text."
)


def llm_parse(message: str, sites: list[dict], today: str, transport=None):
    user = json.dumps({"today": today, "sites": [{"id": s["id"], "name": s["name"]} for s in sites],
                       "request": message})
    text = llm.complete(SYSTEM, user, 500, transport)
    if not text:
        return None
    try:
        text = text[text.index("{"): text.rindex("}") + 1]
        data = json.loads(text)
        assumptions = [str(a) for a in data.pop("assumptions", [])]
        return data, assumptions
    except Exception:  # noqa: BLE001
        return None


def normalize_request(req: dict, site_ids_known: list[str]) -> dict:
    out = dict(req)
    ids = [s for s in out.get("site_ids") or [] if s in site_ids_known]
    out["site_ids"] = ids or list(site_ids_known)
    out["objective"] = out.get("objective") if out.get("objective") in (
        "balanced", "power", "comms", "survive") else "balanced"
    out["duration_h"] = max(6.0, float(out.get("duration_h") or DEFAULT_DURATION_H))
    out["height_m"] = max(0.0, min(50.0, float(out.get("height_m") or 0.0)))
    bh = out.get("battery_h")
    out["battery_h"] = float(bh) if bh not in (None, "") else None
    if out["objective"] == "survive" and out["battery_h"] is None:
        out["battery_h"] = DEFAULT_BATTERY_H
    for k in ("start", "end"):
        date.fromisoformat(str(out[k])[:10])  # raises ValueError if bad
        out[k] = str(out[k])[:10]
    return out


def run(message: str, sites: list[dict], today: str, transport=None) -> dict:
    """Returns {request, assumptions, path}."""
    ids = [s["id"] for s in sites]
    parsed = llm_parse(message, sites, today, transport) if llm.llm_available() else None
    path = "llm"
    if parsed is not None:
        try:
            req, assumptions = parsed
            return {"request": normalize_request(req, ids), "assumptions": assumptions, "path": path}
        except Exception:  # noqa: BLE001 - invalid LLM output -> rules
            pass
    req, assumptions = rule_parse(message, sites, today)
    return {"request": normalize_request(req, ids), "assumptions": assumptions, "path": "rules"}
