# Lunar Landing Site Navigator

*Autonomous lunar South Pole landing site evaluation, line-of-sight visibility analysis, and multi-agent mission planning.*

---

## 1. Overview

At the lunar South Pole, the Sun and Earth remain perpetually close to the horizon (typically within $1.5^\circ$ to $2.0^\circ$ of local elevation). Because of this low grazing angle, crater rims, ridges, and massifs cast long shadows and frequently sever direct-to-Earth (DTE) radio links.

Selecting a viable landing site and mission window requires balancing two often conflicting operational constraints:
1. **Solar Illumination** for photovoltaic power generation and thermal survival.
2. **Direct-to-Earth (DTE) Radio Visibility** for real-time telemetry, teleoperation, and crew communications.

**Lunar Landing Site Navigator** solves this multi-objective trade-off by combining a deterministic lunar physics core, spatially correlated terrain uncertainty quantification, a fact-checked multi-agent copilot, and an interactive 2D/3D Mission Control interface.

---

## 2. System Architecture

```
+-----------------------------------------------------------------------------------+
|                            ORBITAL & TERRAIN INPUTS                               |
|  - NASA LOLA 80 m South-Polar DEM (or Procedural FFT Synthetic Terrain)           |
|  - NASA NAIF SPICE DE440 Kernels (or Analytical Meeus + IAU 2015 Model)           |
|  - Artemis III Candidate Region Polygons (USGS / LROC QuickMap)                   |
+-----------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           DETERMINISTIC NUMERICAL CORE                            |
|  1. DEM & Stereographic Projection (backend/dem.py)                               |
|  2. 360-Azimuth Horizon Raymarching (backend/horizon.py)                          |
|  3. Topocentric Sun/Earth Ephemeris (backend/ephemeris.py)                        |
|  4. Hourly Visibility Classification (backend/visibility.py)                      |
|  5. Mission Window Optimization & Ranking (backend/windows.py)                    |
|  6. Mast-Height Trade-off Sweep (backend/height_sweep.py)                         |
|  7. Spatially Correlated Monte Carlo Uncertainty (backend/uncertainty.py)         |
+-----------------------------------------+-----------------------------------------+
                                          |
                   +----------------------+----------------------+
                   |                                             |
                   v                                             v
+--------------------------------------+   +----------------------------------------+
|       MULTI-AGENT COPILOT            |   |       MISSION CONTROL CLIENT           |
|  - Query Agent (agents/query.py)     |   |  - 3D Tactical Dome (scene3d.js)       |
|  - Orchestrator (orchestrator.py)    |   |  - 2D Skyline & 360 Panorama (draw.js) |
|  - Explainer (agents/explainer.py)   |   |  - Multi-Site Timeline & Scrubber      |
|  - Verifier (agents/verifier.py)     |   |  - Confidence & Mast Charts (app.js)   |
+--------------------------------------+   +----------------------------------------+
```

---

## 3. Core Modules & Physics

### 3.1 Digital Elevation Model (`backend/dem.py`)
The terrain engine uses south-polar stereographic projection ($R_{\mathrm{Moon}} = 1,737,400\text{ m}$):
- **Forward Projection**: Maps selenographic latitude $\phi$ and east-positive longitude $\lambda$ to planar $(x, y)$:
  $$\rho = 2 R_{\mathrm{Moon}} \tan\left(\frac{\pi}{4} + \frac{\phi}{2}\right), \quad x = \rho \cos(\lambda), \quad y = \rho \sin(\lambda)$$
- **Inverse Projection**: Maps planar $(x, y)$ back to $(\phi, \lambda)$:
  $$\rho = \sqrt{x^2 + y^2}, \quad \phi = 2 \arctan\left(\frac{\rho}{2 R_{\mathrm{Moon}}}\right) - \frac{\pi}{2}, \quad \lambda = \mathrm{atan2}(y, x) \pmod{2\pi}$$
- **Area-Aware Sub-Pixel Centering**: Re-samples even-dimensioned GeoTIFF rasters via bilinear interpolation (`scipy.ndimage.map_coordinates`) onto an odd-dimensioned grid centered on the South Pole.
- **Dual Modes**: Supports NASA LOLA $80\text{ m/pixel}$ data (`LDEM_80S_80MPP_ADJ.TIF`, $240\text{ km}$ crop radius) as well as a procedural 2D FFT fractal terrain (`synthetic_dem`) for offline operation.

### 3.2 Ephemeris Engine (`backend/ephemeris.py`)
Computes hourly topocentric Sun and Earth azimuth and elevation in the local East-North-Up (ENU) frame:
- **NASA NAIF SPICE Backend**: Uses `spiceypy` with DE440 planetary ephemerides, lunar physical libration (`MOON_ME` frame), and light-time + stellar aberration corrections (`LT+S`).
- **Analytical Backend**: Pure-NumPy implementation of Jean Meeus (*Astronomical Algorithms*) and the IAU 2015 lunar orientation model:
  $$\mathrm{Azimuth} = \mathrm{atan2}(v_{\mathrm{east}}, v_{\mathrm{north}}) \pmod{360^\circ}, \quad \mathrm{Elevation} = \arcsin\left(\frac{v_{\mathrm{up}}}{\|v\|}\right)$$
- **Explicit Backend Policy**: SPICE mode never silently falls back to analytical mode if kernels are missing.

### 3.3 Horizon Raymarching & Visibility (`backend/horizon.py`, `backend/visibility.py`)
- Projects 360 azimuthal rays out to $r_{\max} = 30\text{ km}$ with lunar spherical curvature correction $\Delta z = \frac{r^2}{2 R_{\mathrm{Moon}}}$ and observer mast-height offset $z_{\mathrm{obs}} = z_0 + h_{\mathrm{mast}}$.
- Tracks raster boundary truncation via `edge_limited` flags.
- Classifies each hour into one of four states: **Neither (0)**, **Power Only (1)**, **Comms Only (2)**, or **Both (3)**.

### 3.4 Window Optimization (`backend/windows.py`)
Evaluates contiguous windows of duration $L$ hours using $O(N)$ prefix sums across four mission objectives (with continuous dark stretch $T_{\mathrm{dark, max}}$):
- **Balanced**: $S_{\mathrm{balanced}} = 0.50\,P_{\mathrm{both}} + 0.25\,P_{\mathrm{power}} + 0.25\,P_{\mathrm{comms}} - 0.25\,\frac{T_{\mathrm{dark, max}}}{L}$
- **Power First**: $S_{\mathrm{power}} = P_{\mathrm{power}} + 0.30\,P_{\mathrm{both}} - 0.30\,\frac{T_{\mathrm{dark, max}}}{L}$
- **Comms First**: $S_{\mathrm{comms}} = P_{\mathrm{comms}} + 0.30\,P_{\mathrm{both}} - 0.30\,\frac{T_{\mathrm{comms, max}}}{L}$
- **Survival**: Enforces onboard battery limits, flagging windows infeasible when $T_{\mathrm{dark, max}} > T_{\mathrm{battery}}$.

### 3.5 Mast-Height Sweep & Uncertainty (`backend/height_sweep.py`, `backend/uncertainty.py`)
- **Mast Sweep**: Evaluates mast heights from $0\text{ m}$ to $15\text{ m}$ to detect non-linear obstacle-clearance jumps ("flips").
- **Monte Carlo Uncertainty**: Generates 30 spatially correlated 2D Gaussian terrain realizations ($\sigma = 8\text{ m}$, $500\text{ m}$ correlation length) to compute $P_{10}/P_{50}/P_{90}$ probability bands and robustness ratings.

---

## 4. Multi-Agent Copilot & Mission Control UI

- **Multi-Agent Copilot (`backend/agents/`, `backend/orchestrator.py`)**:
  - **Query Agent** parses natural-language requests into explicit site, date, mast-height, and objective parameters.
  - **Explainer Agent** synthesizes Planner or Public summaries via Gemini (`llm.py`) with deterministic template fallback.
  - **Verifier Agent** cross-checks every cited number against deterministic service outputs so unverified claims are never surfaced.
- **3D Tactical Dome (`frontend/scene3d.js`)**:
  - Built with locally vendored Three.js and OrbitControls (`frontend/vendor/`).
  - Renders an extruded LOLA terrain bowl, Sun with coronal flare, Earth with atmospheric glow, 3D orbital trajectory arcs, dynamic occlusion raycasts, and a lander status halo.
- **2D Flight-Operations Dashboard (`frontend/draw.js`, `frontend/app.js`, `frontend/skin.js`)**:
  - Interactive skyline plot, $360^\circ$ horizon panorama, multi-site timeline scrubber, Monte Carlo confidence band, mast-height chart, passive hero KPI strip, and CSV export.

---

## 5. Candidate Regions & Verification

- **Artemis III Candidate Sites (`backend/data/sites_real.json`)**: Nine South Pole candidate regions derived via projected shoelace centroids from official LROC QuickMap / USGS (`10.5066/P1MEQ6UK`) polygons (`scripts/prepare_sites.py`).
- **Automated Test Suite (`tests/`)**:
  - Physics, projection, window ranking, and uncertainty invariants (`tests/test_core.py`)
  - Ephemeris accuracy benchmarks (`tests/test_ephemeris.py`)
  - Multi-agent query, explainer, and verifier checks (`tests/test_agents.py`)
  - Strict `NaN`-free 2D canvas rendering tests (`tests/frontend.test.js`)
  - End-to-end API and UI smoke tests (`tests/app_smoke.test.js`)
