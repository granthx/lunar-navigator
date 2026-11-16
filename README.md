# Lunar Landing Site Navigator

*Lunar landing decisions in 30 seconds, with proof.*

Built for the NASA Space Apps 2026 challenge "Lunar Landing Site Navigator": an intuitive tool for mission planners,
educators and the public to compare landing sites and dates, visualising the Sun and Earth against each site's
terrain horizon to judge power and direct-to-Earth communication windows.

Most tools show where the Sun and Earth are. This one **answers the planner's question**: when and where should we
land, and how sure are we?

## Status: read this first
| Part | State |
|---|---|
| Geometry (horizon, visibility, windows, mast sweep, uncertainty) | Built; 42 unit tests pass, including hand-computed cases |
| Ephemeris | Analytical (Meeus + IAU 2015 lunar orientation); checked against a textbook example and known libration limits. **Not SPICE** |
| Terrain | **Synthetic demo terrain.** Real LOLA data could not be downloaded in the build sandbox; see `scripts/README_DATA.md` |
| Sites | **Demo sites on synthetic terrain, not NASA candidate sites** |
| Frontend | Passes 23 headless tests (drawing code with strict numeric checks, plus the full app against the live API). Real Chrome screenshots checked at 1400 and 390 px; the full interactive checklist is still pending |
| LLM paths | Optional; tested only with a fake transport. Everything works without an API key |

Until real terrain and verified sites are loaded, the app shows a permanent warning and results demonstrate the
method, not real site performance.

## Run it
```
pip install numpy scipy uvicorn          # pytest optional
python3 -m uvicorn backend.api.server:app --port 8000
# open http://127.0.0.1:8000
```
Real data: `LUNAR_DEM=... LUNAR_SITES=... ANTHROPIC_API_KEY=...` (all optional). Tests: `./run_tests.sh`.

## What it does
1. **Landing-window finder**: scans every date in a range and ranks mission-length windows for power, comms,
   both, or "survive the dark on a battery of N hours".
2. **Antenna-height trade-off**: recomputes the horizon at 0-15 m and shows where a small height change flips the result.
3. **Honest uncertainty**: re-runs each window under 30 plausible terrain-height errors (default 8 m,
   correlation 500 m, *assumed values, not measured*) and labels it robust, moderate or fragile. It does not cover
   ephemeris, pointing or dust effects, and the UI says so.
4. **Standing on the Moon**: first-person skyline with the Sun and Earth moving over it.
5. **Copilot**: ask in plain English. Three agents:
   - *Query Agent* turns the question into a structured request and lists every assumption it had to make.
   - *Explainer Agent* writes the answer for planners or the public, from computed facts only.
   - *Verifier Agent* (deterministic code) rejects any explanation containing a number, date, site name or label
     the analysis did not produce, and falls back to a template. Its pass means the values are present in the
     computed data, not that every claim is semantically correct; the badge says so.

## Layout
```
backend/ephemeris.py  horizon.py  visibility.py  windows.py  height_sweep.py  uncertainty.py  dem.py  sites.py
backend/service.py    cached analysis used by both the API and the agents
backend/agents/       query.py  explainer.py  verifier.py  llm.py
backend/orchestrator.py   backend/api/server.py (plain ASGI, no framework)
frontend/             index.html style.css lib.js draw.js app.js   (no build step)
tests/                pytest + Node tests;  scripts/  data preparation;  docs/demo-script.md
```

## Known limits
- The horizon is limited by the DEM's extent; sites near its edge are flagged in the UI.
- Sun and Earth are treated as points at their centres (optional clearance margins exist in the API); real
  antenna beams and panel tilt will differ.
- The uncertainty model is only as good as its assumed terrain error; set it from the data product's documentation.
- The analytical ephemeris is accurate to a few hundredths of a degree, not SPICE-grade.
