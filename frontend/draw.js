/* Canvas drawing (no DOM access). All sizes are CSS pixels; the caller scales the context for DPR. */
(function (root) {
  "use strict";
  const L = root.Lib || (typeof require !== "undefined" ? require("./lib.js") : null);

  const SUN = "#f0b93a", EARTH = "#6ea2e8";
  const INK = "#1d2024", MUTED = "#5d6169", PAPER = "#f3f1ec", RULE = "#cfcbc3";
  const LIGHT_LINES = { both: "#1f9d6b", power: "#b8821a", comms: "#2d5f96" };
  const FONT = "12px system-ui, -apple-system, 'Segoe UI', sans-serif";

  const maxOf = (a) => { let m = -Infinity; for (let i = 0; i < a.length; i++) if (a[i] > m) m = a[i]; return m; };
  const minOf = (a) => { let m = Infinity; for (let i = 0; i < a.length; i++) if (a[i] < m) m = a[i]; return m; };

  function drawEmpty(ctx, W, H, msg, dark) {
    ctx.fillStyle = dark ? "#0f1218" : PAPER;
    ctx.fillRect(0, 0, W, H);
    ctx.fillStyle = dark ? "#9aa3b2" : MUTED;
    ctx.font = FONT;
    ctx.textAlign = "center";
    ctx.fillText(msg, W / 2, H / 2);
    ctx.textAlign = "left";
  }

  function skyGradient(ctx, H) {
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, "#07090d");
    g.addColorStop(1, "#141a26");
    return g;
  }

  /* ---------------------------------------------------------------- horizon plot */
  function drawHorizon(ctx, W, H, site, tIdx) {
    const pad = { l: 46, r: 14, t: 14, b: 28 };
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const hor = site.horizon_el, azs = site.horizon_az;
    let hi = Math.max(8, maxOf(hor), maxOf(site.sun_el), maxOf(site.earth_el));
    let lo = Math.min(-3, minOf(hor), minOf(site.sun_el), minOf(site.earth_el));
    hi = Math.min(40, Math.ceil(hi / 2) * 2);
    lo = Math.max(-20, Math.floor(lo / 2) * 2);
    const x = (az) => pad.l + (az / 360) * pw;
    const y = (el) => pad.t + ((hi - el) / (hi - lo)) * ph;
    const pxPerDeg = ph / (hi - lo);

    ctx.fillStyle = skyGradient(ctx, H);
    ctx.fillRect(0, 0, W, H);

    ctx.font = FONT;
    ctx.lineWidth = 1;
    const stepEl = hi - lo > 24 ? 5 : 2;
    for (let e = Math.ceil(lo / stepEl) * stepEl; e <= hi; e += stepEl) {
      ctx.strokeStyle = e === 0 ? "rgba(255,255,255,0.35)" : "rgba(255,255,255,0.08)";
      ctx.setLineDash(e === 0 ? [5, 4] : []);
      ctx.beginPath(); ctx.moveTo(pad.l, y(e)); ctx.lineTo(W - pad.r, y(e)); ctx.stroke();
      ctx.fillStyle = "#9aa3b2";
      ctx.textAlign = "right";
      ctx.fillText(e + "°", pad.l - 6, y(e) + 4);
    }
    ctx.setLineDash([]);
    const dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"];
    ctx.textAlign = "center";
    for (let k = 0; k <= 8; k++) {
      ctx.strokeStyle = "rgba(255,255,255,0.08)";
      ctx.beginPath(); ctx.moveTo(x(k * 45), pad.t); ctx.lineTo(x(k * 45), pad.t + ph); ctx.stroke();
      ctx.fillStyle = "#9aa3b2";
      ctx.fillText(dirs[k], x(k * 45), H - 9);
    }

    // Sun and Earth tracks over the chosen dates
    const n = site.times.length;
    for (let i = 0; i < n; i++) {
      ctx.fillStyle = "rgba(240,185,58,0.32)";
      ctx.fillRect(x(site.sun_az[i]) - 1, y(site.sun_el[i]) - 1, 2, 2);
      ctx.fillStyle = "rgba(110,162,232,0.32)";
      ctx.fillRect(x(site.earth_az[i]) - 1, y(site.earth_el[i]) - 1, 2, 2);
    }

    // current positions (drawn before terrain so terrain hides a body that is blocked)
    const marks = [
      { az: site.sun_az[tIdx], el: site.sun_el[tIdx], c: SUN, r: Math.max(5, 0.27 * pxPerDeg), name: "Sun" },
      { az: site.earth_az[tIdx], el: site.earth_el[tIdx], c: EARTH, r: Math.max(7, 0.95 * pxPerDeg), name: "Earth" },
    ];

    // terrain silhouette
    ctx.beginPath();
    ctx.moveTo(x(0), y(hor[0]));
    for (let i = 1; i < azs.length; i++) ctx.lineTo(x(azs[i]), y(hor[i]));
    ctx.lineTo(x(360), y(hor[0]));
    ctx.lineTo(x(360), pad.t + ph);
    ctx.lineTo(x(0), pad.t + ph);
    ctx.closePath();
    const tg = ctx.createLinearGradient(0, y(maxOf(hor)), 0, pad.t + ph);
    tg.addColorStop(0, "#6d6b66");
    tg.addColorStop(1, "#2a2b2e");
    ctx.fillStyle = tg;
    ctx.fill();
    ctx.strokeStyle = "#cfcac0";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x(0), y(hor[0]));
    for (let i = 1; i < azs.length; i++) ctx.lineTo(x(azs[i]), y(hor[i]));
    ctx.lineTo(x(360), y(hor[0]));
    ctx.stroke();

    // markers on top, with a note when the terrain blocks them
    for (const m of marks) {
      const blocked = m.el <= L.horizonAt(azs, hor, m.az);
      ctx.lineWidth = 2;
      ctx.strokeStyle = m.c;
      ctx.fillStyle = blocked ? "rgba(0,0,0,0)" : m.c;
      ctx.setLineDash(blocked ? [3, 3] : []);
      ctx.beginPath();
      ctx.arc(x(m.az), y(m.el), m.r, 0, Math.PI * 2);
      if (!blocked) ctx.fill();
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#e8eaee";
      ctx.textAlign = "left";
      const lx = Math.min(x(m.az) + m.r + 4, W - 130);
      ctx.fillText(m.name + (blocked ? " (behind terrain)" : ""), lx, y(m.el) - m.r - 3);
    }
    ctx.textAlign = "left";
  }

  /* -------------------------------------------------------------------- timeline */
  const TL = { left: 92, right: 10, top: 20, rowH: 22, gap: 6 };
  const timelineHeight = (rows) => TL.top + rows * (TL.rowH + TL.gap) + 6;
  function timelineIndexFromX(px, W, n) {
    const pw = W - TL.left - TL.right;
    return L.clamp(Math.floor(((px - TL.left) / pw) * n), 0, n - 1);
  }

  function drawTimeline(ctx, W, H, sites, tIdx, highlight) {
    ctx.fillStyle = PAPER;
    ctx.fillRect(0, 0, W, H);
    if (!sites.length) return;
    const n = sites[0].times.length;
    const pw = W - TL.left - TL.right;
    ctx.font = FONT;

    // date ticks
    const ticks = Math.max(2, Math.floor(pw / 120));
    ctx.fillStyle = MUTED;
    ctx.textAlign = "left";
    for (let k = 0; k <= ticks; k++) {
      const i = Math.min(n - 1, Math.round((k / ticks) * (n - 1)));
      const px = TL.left + (i / n) * pw;
      ctx.strokeStyle = RULE;
      ctx.beginPath(); ctx.moveTo(px, TL.top - 4); ctx.lineTo(px, TL.top); ctx.stroke();
      ctx.textAlign = k === ticks ? "right" : "left";
      ctx.fillText(L.fmtDate(sites[0].times[i]), px, TL.top - 7);
    }

    sites.forEach((s, r) => {
      const y0 = TL.top + r * (TL.rowH + TL.gap);
      ctx.fillStyle = INK;
      ctx.textAlign = "left";
      const label = s.site.name.length > 12 ? s.site.name.slice(0, 11) + "…" : s.site.name;
      ctx.fillText(label, 6, y0 + TL.rowH / 2 + 4);
      const w = Math.max(1, pw / n + 0.6);
      for (let i = 0; i < n; i++) {
        ctx.fillStyle = L.CODE_COLORS[s.code[i]];
        ctx.fillRect(TL.left + (i / n) * pw, y0, w, TL.rowH);
      }
      if (highlight && highlight.siteId === s.site.id) {
        const a = TL.left + (highlight.start / n) * pw;
        const b = TL.left + (highlight.end / n) * pw;
        ctx.strokeStyle = INK;
        ctx.lineWidth = 2;
        ctx.strokeRect(a, y0 - 2, Math.max(2, b - a), TL.rowH + 4);
        ctx.lineWidth = 1;
      }
    });

    const sx = TL.left + ((tIdx + 0.5) / n) * pw;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(sx, TL.top); ctx.lineTo(sx, H - 4); ctx.stroke();
    ctx.strokeStyle = INK;
    ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(sx, TL.top); ctx.lineTo(sx, H - 4); ctx.stroke();
    ctx.textAlign = "left";
  }

  /* --------------------------------------------------------- light-panel chart frame */
  function frame(ctx, W, H, pad, yLabel) {
    ctx.fillStyle = PAPER;
    ctx.fillRect(0, 0, W, H);
    ctx.font = FONT;
    ctx.lineWidth = 1;
    for (const v of [0, 25, 50, 75, 100]) {
      const yy = pad.t + (1 - v / 100) * (H - pad.t - pad.b);
      ctx.strokeStyle = RULE;
      ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(W - pad.r, yy); ctx.stroke();
      ctx.fillStyle = MUTED;
      ctx.textAlign = "right";
      ctx.fillText(v + "%", pad.l - 6, yy + 4);
    }
    ctx.textAlign = "left";
    if (yLabel) { ctx.fillStyle = MUTED; ctx.fillText(yLabel, pad.l, 12); }
  }

  /* ------------------------------------------------- confidence band for one window */
  function drawBand(ctx, W, H, prob) {
    const pad = { l: 46, r: 12, t: 22, b: 24 };
    frame(ctx, W, H, pad, "Share of terrain variations in which it holds");
    const n = prob.p_both.length;
    if (!n) return;
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const x = (i) => pad.l + (i / Math.max(1, n - 1)) * pw;
    const y = (p) => pad.t + (1 - p) * ph;
    const line = (arr, color, wd) => {
      ctx.strokeStyle = color; ctx.lineWidth = wd; ctx.beginPath();
      arr.forEach((p, i) => (i ? ctx.lineTo(x(i), y(p)) : ctx.moveTo(x(i), y(p))));
      ctx.stroke();
    };
    ctx.beginPath();
    prob.p_both.forEach((p, i) => (i ? ctx.lineTo(x(i), y(p)) : ctx.moveTo(x(i), y(p))));
    ctx.lineTo(x(n - 1), y(0)); ctx.lineTo(x(0), y(0)); ctx.closePath();
    ctx.fillStyle = "rgba(31,157,107,0.22)";
    ctx.fill();
    line(prob.p_power, LIGHT_LINES.power, 1);
    line(prob.p_comms, LIGHT_LINES.comms, 1);
    line(prob.p_both, LIGHT_LINES.both, 2);
    ctx.fillStyle = MUTED;
    ctx.textAlign = "left";
    ctx.fillText(L.fmtDate(prob.times[0]), pad.l, H - 7);
    ctx.textAlign = "right";
    ctx.fillText(L.fmtDate(prob.times[n - 1]), W - pad.r, H - 7);
    ctx.textAlign = "left";
  }

  /* --------------------------------------------------------- mast height trade-off */
  function drawHeight(ctx, W, H, hs) {
    const pad = { l: 46, r: 60, t: 22, b: 30 };
    frame(ctx, W, H, pad, "Share of the window");
    const rows = hs.rows;
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const hmax = Math.max(1, rows[rows.length - 1].height_m);
    const x = (h) => pad.l + (h / hmax) * pw;
    const y = (p) => pad.t + (1 - p / 100) * ph;
    const series = [["both_pct", LIGHT_LINES.both, "both"], ["power_pct", LIGHT_LINES.power, "power"],
      ["comms_pct", LIGHT_LINES.comms, "comms"]];

    const j = hs.biggest_jumps.both_pct;
    if (j && j.is_flip) {
      ctx.fillStyle = "rgba(29,32,36,0.08)";
      ctx.fillRect(x(j.from_height_m), pad.t, x(j.to_height_m) - x(j.from_height_m), ph);
    }
    for (const [key, color, name] of series) {
      ctx.strokeStyle = color; ctx.lineWidth = key === "both_pct" ? 2.5 : 1.5;
      ctx.beginPath();
      rows.forEach((r, i) => (i ? ctx.lineTo(x(r.height_m), y(r[key])) : ctx.moveTo(x(r.height_m), y(r[key]))));
      ctx.stroke();
      ctx.fillStyle = color;
      rows.forEach((r) => { ctx.beginPath(); ctx.arc(x(r.height_m), y(r[key]), 3, 0, Math.PI * 2); ctx.fill(); });
      const last = rows[rows.length - 1];
      ctx.textAlign = "left";
      ctx.fillText(name, x(last.height_m) + 8, y(last[key]) + 4);
    }
    ctx.fillStyle = MUTED;
    ctx.textAlign = "center";
    for (const r of rows) ctx.fillText(r.height_m + " m", x(r.height_m), H - 10);
    if (j && j.is_flip) {
      ctx.fillStyle = INK;
      ctx.textAlign = "left";
      ctx.fillText("+" + Math.round(j.jump_pct) + " points", x(j.to_height_m) + 6, pad.t + 14);
    }
    ctx.textAlign = "left";
  }

  /* ----------------------------------------------------- first-person view */
  const STARS = L.starField(160, 7);

  function drawPano(ctx, W, H, site, tIdx, o) {
    const heading = o.heading, fov = o.fov, stretch = o.stretch || 1;
    const pxDeg = W / fov;
    const y0 = H * 0.74;
    const yOf = (el) => y0 - el * pxDeg * stretch;
    ctx.fillStyle = skyGradient(ctx, H);
    ctx.fillRect(0, 0, W, H);
    for (const s of STARS) {
      ctx.fillStyle = "rgba(255,255,255," + s.a + ")";
      ctx.fillRect(s.x * W, s.y * y0, s.r, s.r);
    }

    const bodies = [
      { az: site.earth_az[tIdx], el: site.earth_el[tIdx], rDeg: 0.95, kind: "earth" },
      { az: site.sun_az[tIdx], el: site.sun_el[tIdx], rDeg: 0.27, kind: "sun" },
    ];
    for (const b of bodies) {
      const bx = L.pxFromAz(b.az, heading, fov, W);
      const by = yOf(b.el);
      const r = Math.max(3, b.rDeg * pxDeg * (o.enlarge ? 3 : 1));
      if (bx < -r * 4 || bx > W + r * 4) continue;
      if (b.kind === "sun") {
        const g = ctx.createRadialGradient(bx, by, r * 0.4, bx, by, r * 4);
        g.addColorStop(0, "rgba(255,226,140,0.55)");
        g.addColorStop(1, "rgba(255,226,140,0)");
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(bx, by, r * 4, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = "#fff4cf";
      } else {
        const g = ctx.createRadialGradient(bx - r * 0.3, by - r * 0.3, r * 0.2, bx, by, r);
        g.addColorStop(0, "#d6e6ff");
        g.addColorStop(1, "#3f73c7");
        ctx.fillStyle = g;
      }
      ctx.beginPath(); ctx.arc(bx, by, r, 0, Math.PI * 2); ctx.fill();
    }

    // terrain silhouette across the view
    const azs = site.horizon_az, hor = site.horizon_el;
    const steps = Math.min(W, 720);
    ctx.beginPath();
    ctx.moveTo(0, H);
    for (let k = 0; k <= steps; k++) {
      const px = (k / steps) * W;
      const az = heading + (px - W / 2) / pxDeg;
      ctx.lineTo(px, yOf(L.horizonAt(azs, hor, az)));
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    const g = ctx.createLinearGradient(0, y0 - 40, 0, H);
    g.addColorStop(0, "#77746d");
    g.addColorStop(1, "#1f2023");
    ctx.fillStyle = g;
    ctx.fill();

    // compass along the bottom
    ctx.font = FONT;
    ctx.textAlign = "center";
    const names = { 0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW" };
    for (let a = 0; a < 360; a += 15) {
      const px = L.pxFromAz(a, heading, fov, W);
      if (px < 10 || px > W - 10) continue;
      ctx.strokeStyle = "rgba(255,255,255,0.35)";
      ctx.beginPath(); ctx.moveTo(px, H - 20); ctx.lineTo(px, H - (names[a] ? 12 : 16)); ctx.stroke();
      ctx.fillStyle = names[a] ? "#e8eaee" : "#9aa3b2";
      ctx.fillText(names[a] || a + "°", px, H - 3);
    }
    ctx.textAlign = "left";
  }

  const Draw = { drawEmpty, drawHorizon, drawTimeline, timelineHeight, timelineIndexFromX, drawBand,
    drawHeight, drawPano };
  if (typeof module !== "undefined" && module.exports) module.exports = Draw; else root.Draw = Draw;
})(typeof window !== "undefined" ? window : globalThis);
