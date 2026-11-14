"""Verifier Agent: deterministic fact-check of an explanation against computed data.

No LLM is involved, so it cannot hallucinate. It checks that every number, date,
site name and robustness label in the text is backed by the `facts` the
analysis produced. Anything it cannot back is reported, and the pipeline then
falls back to the template explanation.
"""
from __future__ import annotations

import re

ROBUST_WORDS = ("robust", "moderate", "fragile")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
NUM_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def collect_numbers(obj, out=None) -> list[float]:
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, out)
    return out


def collect_strings(obj, out=None) -> list[str]:
    out = [] if out is None else out
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_strings(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_strings(v, out)
    return out


def _matches(token: str, values: list[float]) -> bool:
    x = float(token)
    decimals = len(token.split(".")[1]) if "." in token else 0
    tol = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(v - x) <= tol or abs(abs(v) - abs(x)) <= tol for v in values)


def verify(text: str, facts: dict, known_site_names: list[str]) -> dict:
    values = collect_numbers(facts)
    strings = collect_strings(facts)
    # numbers written inside fact strings (e.g. caveat text) are backed facts too
    for st in strings:
        values.extend(float(t) for t in NUM_RE.findall(DATE_RE.sub(" ", st)))
    fact_dates = {d for s in strings for d in DATE_RE.findall(s)}
    fact_labels = {s.lower() for s in strings}
    fact_site_names = {n for n in known_site_names if any(n in s for s in strings)}

    work = text
    # site names may contain digits/letters; verify them separately then strip
    unknown_sites = []
    for name in sorted(known_site_names, key=len, reverse=True):
        if name in work:
            if name not in fact_site_names:
                unknown_sites.append(name)
            work = work.replace(name, " ")

    dates = DATE_RE.findall(work)
    bad_dates = [d for d in dates if d not in fact_dates]
    work = DATE_RE.sub(" ", work)
    work = re.sub(r"(?m)^\s*\d+[.)]\s", " ", work)         # list numbering

    tokens = NUM_RE.findall(work)
    unmatched = [t for t in tokens if not _matches(t, values)]

    lowered = text.lower()
    bad_labels = [w for w in ROBUST_WORDS
                  if re.search(rf"\b{w}\b", lowered) and w not in fact_labels]

    ok = not (unmatched or bad_dates or unknown_sites or bad_labels)
    return {"verified": ok, "numbers_checked": len(tokens), "dates_checked": len(dates),
            "unmatched_numbers": unmatched, "unbacked_dates": bad_dates,
            "unknown_sites": unknown_sites, "unbacked_labels": bad_labels}
