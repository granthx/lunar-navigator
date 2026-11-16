/* Pure helpers (no DOM). Loaded in the browser as window.Lib and in Node for tests. */
(function (root) {
  "use strict";

  const CODE_NAMES = ["neither", "power only", "comms only", "power + comms"];
  // Gold means power and blue means comms, matching the Horizon and height charts.
  const CODE_COLORS = ["#23262f", "#d9a441", "#3a6ea5", "#8fe3b0"];

  const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

  /** wrap an angle difference to [-180, 180) */
  function wrapDeg(d) {
    return ((((d + 180) % 360) + 360) % 360) - 180;
  }

  /** periodic linear interpolation of a horizon profile (azimuth grid in degrees) */
  function horizonAt(azs, els, az) {
    const n = azs.length;
    const a = ((az % 360) + 360) % 360;
    const step = azs.length > 1 ? azs[1] - azs[0] : 360;
    const f = a / step;
    const i0 = Math.floor(f) % n;
    const i1 = (i0 + 1) % n;
    const t = f - Math.floor(f);
    return els[i0] * (1 - t) + els[i1] * t;
  }

  /** index of the sample whose time is nearest to an ISO string (times sorted ascending) */
  function indexForTime(times, iso) {
    const target = Date.parse(iso + "Z");
    let lo = 0, hi = times.length - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Date.parse(times[mid] + "Z") < target) lo = mid + 1; else hi = mid;
    }
    if (lo > 0 && Math.abs(Date.parse(times[lo - 1] + "Z") - target) <= Math.abs(Date.parse(times[lo] + "Z") - target)) {
      return lo - 1;
    }
    return lo;
  }

  /** screen x of an azimuth for a view centred on `heading` with horizontal field of view `fov` */
  function pxFromAz(az, heading, fov, width) {
    return width / 2 + wrapDeg(az - heading) * (width / fov);
  }

  function fmtPct(x) { return Math.round(x) + "%"; }
  function fmtHours(h) { return Math.round(h) + " h"; }
  function fmtTime(iso) { return iso.replace("T", " ").slice(0, 16) + " UTC"; }
  function fmtDate(iso) { return iso.slice(0, 10); }

  /** CSV of one site's series (planner export) */
  function buildCsv(site) {
    const rows = ["time_utc,sun_az_deg,sun_el_deg,earth_az_deg,earth_el_deg,status"];
    for (let i = 0; i < site.times.length; i++) {
      rows.push([site.times[i], site.sun_az[i], site.sun_el[i], site.earth_az[i], site.earth_el[i],
        CODE_NAMES[site.code[i]]].join(","));
    }
    return rows.join("\n") + "\n";
  }

  /** deterministic pseudo-random stars so the panorama does not flicker between redraws */
  function starField(n, seed) {
    let s = seed >>> 0;
    const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    const out = [];
    for (let i = 0; i < n; i++) out.push({ x: rnd(), y: rnd(), r: 0.4 + rnd() * 0.9, a: 0.25 + rnd() * 0.6 });
    return out;
  }

  /** summary sentence for screen readers (numbers come straight from the data) */
  function describeSite(site, i) {
    let sunUp = 0, earthUp = 0;
    const n = site.times.length;
    for (let k = 0; k < n; k++) {
      if (site.code[k] === 1 || site.code[k] === 3) sunUp++;
      if (site.code[k] === 2 || site.code[k] === 3) earthUp++;
    }
    return `${site.site.name}: sunlight ${fmtPct(100 * sunUp / n)} of the time, link to Earth ${fmtPct(100 * earthUp / n)}`;
  }

  const Lib = { CODE_NAMES, CODE_COLORS, clamp, wrapDeg, horizonAt, indexForTime, pxFromAz,
    fmtPct, fmtHours, fmtTime, fmtDate, buildCsv, starField, describeSite };
  if (typeof module !== "undefined" && module.exports) module.exports = Lib; else root.Lib = Lib;
})(typeof window !== "undefined" ? window : globalThis);
