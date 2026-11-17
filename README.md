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
| Ephemeris | Analytical default; **SPICE DE440 integration is built and was used for the Phase 3 real-data run**. Selection is explicit (`LUNAR_EPHEMERIS=spice`); missing kernels fail loudly |
| Terrain | **Real LOLA 80 m south-polar DEM** (240 km crop) verified against an independent projection and IAU landmarks. The app still starts on synthetic terrain unless `LUNAR_DEM` is set |
| Sites | **NASA 2024 nine-region candidate list**. Each region is represented by one interior point derived from its official polygon; these are not certified landing coordinates |
| Frontend | Passes all 47 automated tests (42 Python + 11 drawing/helper + 12 full-app + 2 Node). Real Chrome screenshots verified at 1400, 900, and 390 px. The full interactive browser and keyboard checklist (13 checks) has been completed via Playwright (`scripts/verify_interactive_browser.py`) — all pass |
| LLM paths | Optional; Anthropic API (ANTHROPIC_API_KEY) or Gemini API (GEMINI_API_KEY / GOOGLE_API_KEY). Anthropic takes priority; Gemini is used automatically when only its key is set. Everything works without any API key |

The default run is still a clearly labelled synthetic demo. The Phase 3 real-data run is reproducible with the
environment variables below and is recorded in `docs/verification-log.md`. NASA Space Apps submission eligibility
for pre-event work is unresolved; this is a working project, not an official submission.

## Run it

Synthetic demo (no downloads, no API key):

```
pip install numpy scipy uvicorn          # pytest optional
python -m uvicorn backend.api.server:app --port 8000
# open http://127.0.0.1:8000
```

Real data (PowerShell; see `scripts/README_DATA.md` for how the inputs were produced):

```powershell
$env:LUNAR_DEM = "backend/data/lunar_south_pole_80m.npz"
$env:LUNAR_SITES = "backend/data/sites_real.json"
$env:LUNAR_EPHEMERIS = "spice"
python -m uvicorn backend.api.server:app --port 8000
```

The DEM, SPICE kernels and raw region GeoJSON are large/downloaded and are git-ignored. The small nine-site
registry is committed. Tests on Windows (PowerShell):

```powershell
python -m pytest tests -q          # 47 Python tests
node tests/frontend.test.js        # 11 drawing/helper tests
node tests/app_smoke.test.js       # 12 full-app smoke tests
python scripts/verify_interactive_browser.py  # interactive browser checklist (requires Playwright + Chromium)
```

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
backend/data/         sites_template.json, sites_real.json (generated data is git-ignored)
frontend/             index.html style.css lib.js draw.js app.js   (no build step)
scripts/              prepare_dem.py prepare_sites.py README_DATA.md
tests/                pytest + Node tests;  docs/demo-script.md
```

## Known limits

- The horizon is limited by the DEM extent (240 km radius) and a 30 km search distance; sites near the edge are
  flagged in the UI.
- The nine site points are representative interior points from official region polygons, not certified landing
  coordinates.
- Sun and Earth are treated as points at their centres (optional clearance margins exist in the API); real
  antenna beams and panel tilt will differ.
- The uncertainty model is only as good as its assumed terrain error; set it from the data product's documentation.
- The verifier is a value-presence check, not a semantic fact-check.
- The analytical ephemeris is accurate to a few hundredths of a degree, not SPICE-grade. The real-data run used SPICE;
  the two agree to 0.006° in azimuth and 0.002° in elevation at the nine regions.
- The real-data result has not been independently validated against an external illumination or communication model.
