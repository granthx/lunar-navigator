/* Lunar Landing Site Navigator: page logic. All dynamic text goes through textContent. */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const L = window.Lib, D = window.Draw;

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k === "checked") el.checked = true;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const S = {
    meta: null, data: {}, order: [], windows: {}, focus: null, n: 0, tIdx: 0,
    sel: null, highlight: null, prob: null, height: null, token: 0,
    last: null, timer: null, heading: 0, tab: "windows", raf: 0, last3dSite: null,
  };

  /* ------------------------------------------------------------------ plumbing */
  async function api(path, body) {
    const init = body === undefined ? {} : {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
    };
    let res;
    try { res = await fetch(path, init); }
    catch (e) { throw new Error("Could not reach the analysis server. Check that it is running and try again."); }
    const data = await res.json().catch(() => ({ error: "The server sent an unreadable response." }));
    if (!res.ok) throw new Error(data.error || "The request failed (" + res.status + ").");
    return data;
  }

  function toast(msg) {
    const t = $("#toast");
    if (!msg) { t.hidden = true; return; }
    t.textContent = msg; t.hidden = false;
  }

  function busy(on) {
    const b = $("#go");
    b.disabled = on;
    b.textContent = on ? "Working…" : "Compare sites";
  }

  function sizedCtx(canvas, cssH) {
    const dpr = window.devicePixelRatio || 1;
    const W = Math.floor(canvas.clientWidth);
    if (W < 40) return null;
    const H = cssH || Math.floor(canvas.clientHeight);
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, W, H };
  }

  const mode = () => document.body.dataset.mode;
  const maxMast = () => Number(S.meta && S.meta.max_height_m) || 15;
  const focusSite = () => S.data[S.focus];
  const selectedIds = () => $$("#siteChips input:checked").map((i) => i.value);

  /* -------------------------------------------------------------------- render */
  function renderHorizon() {
    const c = $("#horizon"), s = focusSite();
    const z = sizedCtx(c);
    if (!z) return;
    if (!s) { D.drawEmpty(z.ctx, z.W, z.H, "Choose sites and press Compare sites", true); return; }
    D.drawHorizon(z.ctx, z.W, z.H, s, S.tIdx);
    c.setAttribute("aria-label", "Horizon plot for " + s.site.name + ". " + L.describeSite(s));
    renderScene3D();
  }

  function renderLegend() {
    $("#legend").replaceChildren(...L.CODE_NAMES.map((name, code) =>
      h("li", {}, h("i", { style: "background:" + L.CODE_COLORS[code] }), name)));
  }

  function renderTimeline() {
    const c = $("#timeline");
    const sites = S.order.map((id) => S.data[id]).filter(Boolean);
    const cssH = D.timelineHeight(Math.max(1, sites.length));
    c.style.height = cssH + "px";
    const z = sizedCtx(c, cssH);
    if (!z) return;
    if (!sites.length) { D.drawEmpty(z.ctx, z.W, z.H, "No data yet", false); return; }
    D.drawTimeline(z.ctx, z.W, z.H, sites, S.tIdx, S.highlight);
    c.setAttribute("aria-label", "Timeline per site. " + sites.map(L.describeSite).join(". "));
  }

  let scene3dInited = false;
  function renderScene3D() {
    const s = focusSite();
    if (!s) return;
    if (typeof window !== "undefined" && window.Scene3D && typeof window.Scene3D.init === "function") {
      if (!scene3dInited) {
        scene3dInited = window.Scene3D.init("scene3dWrap");
      }
      if (scene3dInited) {
        if (S.last3dSite !== s.site.id) {
          window.Scene3D.setSite(s);
          S.last3dSite = s.site.id;
        }
        window.Scene3D.update(s, S.tIdx);
      }
    }
  }

  function renderPano() {
    if (S.tab !== "moon") return;
    const c = $("#pano"), s = focusSite();
    const z = sizedCtx(c);
    if (!z) return;
    if (!s) { D.drawEmpty(z.ctx, z.W, z.H, "Choose sites and press Compare sites", true); return; }
    D.drawPano(z.ctx, z.W, z.H, s, S.tIdx, {
      heading: S.heading, fov: Number($("#fov").value), stretch: Number($("#stretch").value),
      enlarge: $("#enlarge").checked,
    });
  }

  function renderReadout() {
    const s = focusSite(), el = $("#readout");
    if (!s) { el.textContent = ""; return; }
    const i = S.tIdx;
    const hz = (az) => L.horizonAt(s.horizon_az, s.horizon_el, az);
    const sunH = hz(s.sun_az[i]), earthH = hz(s.earth_az[i]);
    const sunUp = s.sun_el[i] > sunH, earthUp = s.earth_el[i] > earthH;
    const code = s.code[i];
    if (mode() === "public") {
      const verdict = ["has neither power nor a link to Earth", "has power but no link to Earth",
        "has a link to Earth but no power", "has both power and a link to Earth"][code];
      el.textContent = "At " + L.fmtTime(s.times[i]) + " at " + s.site.name + ": the Sun is " +
        (sunUp ? "visible" : "hidden behind terrain") + " and Earth is " +
        (earthUp ? "visible" : "hidden behind terrain") + ", so the lander " + verdict + ".";
    } else {
      el.textContent = L.fmtTime(s.times[i]) + " at " + s.site.name + ". Sun: " + s.sun_el[i].toFixed(1) +
        "° elevation, skyline " + sunH.toFixed(1) + "° at that bearing, " + (sunUp ? "visible" : "blocked") +
        ". Earth: " + s.earth_el[i].toFixed(1) + "° elevation, skyline " + earthH.toFixed(1) + "°, " +
        (earthUp ? "visible" : "blocked") + ". Status: " + L.CODE_NAMES[code] + ".";
    }
  }

  function renderCards() {
    const box = $("#cards");
    box.replaceChildren();
    for (const id of S.order) {
      const s = S.data[id]; if (!s) continue;
      const m = s.metrics;
      const rows = mode() === "public"
        ? [["Sunlight", L.fmtPct(m.power_pct)], ["Link to Earth", L.fmtPct(m.comms_pct)], ["Both at once", L.fmtPct(m.both_pct)]]
        : [["Power", L.fmtPct(m.power_pct)], ["Comms", L.fmtPct(m.comms_pct)], ["Power + comms", L.fmtPct(m.both_pct)],
          ["Longest dark stretch", L.fmtHours(m.longest_dark_h)], ["Longest comms gap", L.fmtHours(m.longest_comms_gap_h)]];
      box.append(h("article", { class: "card" + (id === S.focus ? " focus" : "") },
        h("h3", { text: s.site.name }),
        h("dl", {}, rows.map(([k, v]) => [h("dt", { text: k }), h("dd", { text: v })])),
        s.data_notes.edge_limited ? h("p", { class: "caption", text: "The terrain model ends near this site, so distant ridges may be missing." }) : null,
        h("button", { type: "button", onclick: () => { S.focus = id; $("#focus").value = id; renderAll(); } }, "Show in sky plot")));
    }
  }

  function allWindows() {
    const out = [];
    for (const [siteId, res] of Object.entries(S.windows)) {
      res.windows.forEach((w, rank) => out.push({ siteId, rank, w }));
    }
    out.sort((a, b) => (b.w.feasible - a.w.feasible) || (b.w.score - a.w.score));
    return out;
  }

  const CONF = { robust: "Reliable", moderate: "Somewhat uncertain", fragile: "Uncertain" };

  function renderWindows() {
    const box = $("#winList");
    box.replaceChildren();
    const list = allWindows().slice(0, 9);
    if (!list.length) { box.append(h("p", { class: "caption", text: "No windows yet. Press Compare sites." })); return; }
    const pub = mode() === "public";
    const head = pub ? ["Site", "Dates", "Power and link together", "How sure"]
      : ["Site", "Starts", "Ends", "Power", "Comms", "Both", "Longest dark", "Terrain-error range (both)", "Robustness"];
    const body = list.map(({ siteId, rank, w }) => {
      const u = w.uncertainty, m = w.metrics;
      const sel = S.sel && S.sel.siteId === siteId && S.sel.rank === rank;
      const name = S.data[siteId] ? S.data[siteId].site.name : siteId;
      const pick = h("button", { class: "pick", type: "button", onclick: () => selectWindow(siteId, rank) }, name);
      const tag = !w.feasible ? h("span", { class: "chip infeasible", text: "Exceeds battery" })
        : u ? h("span", { class: "chip " + u.robustness, text: pub ? CONF[u.robustness] : u.robustness }) : "";
      const cells = pub
        ? [h("td", {}, pick), h("td", { text: L.fmtDate(w.start) + " to " + L.fmtDate(w.end) }),
          h("td", { class: "num", text: L.fmtPct(m.both_pct) }), h("td", {}, tag)]
        : [h("td", {}, pick), h("td", { text: L.fmtTime(w.start) }), h("td", { text: L.fmtTime(w.end) }),
          h("td", { class: "num", text: L.fmtPct(m.power_pct) }), h("td", { class: "num", text: L.fmtPct(m.comms_pct) }),
          h("td", { class: "num", text: L.fmtPct(m.both_pct) }), h("td", { class: "num", text: L.fmtHours(m.longest_dark_h) }),
          h("td", { class: "num", text: u ? L.fmtPct(u.both_pct.p10) + " to " + L.fmtPct(u.both_pct.p90) : "" }), h("td", {}, tag)];
      return h("tr", { class: sel ? "sel" : "" }, cells);
    });
    box.append(h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, head.map((t, i) => h("th", { class: !pub && i >= 3 && i <= 7 && i !== 7 ? "num" : "", text: t })))),
      h("tbody", {}, body))));
  }

  function renderDetail() {
    const w = S.sel && S.sel.w;
    const band = $("#band"), title = $("#bandTitle"), note = $("#bandNote");
    if (!w || !S.prob) { band.hidden = true; title.hidden = true; note.textContent = ""; return; }
    band.hidden = false; title.hidden = false;
    if (S.tab === "windows") {
      const z = sizedCtx(band, 230);
      if (z) D.drawBand(z.ctx, z.W, z.H, S.prob);
    }
    const u = w.uncertainty;
    if (u) {
      const a = u.assumptions;
      note.textContent = "Power and link together hold for " + L.fmtPct(w.metrics.both_pct) + " of this window; allowing for terrain error of about " +
        a.vertical_sigma_m + " m the range is " + L.fmtPct(u.both_pct.p10) + " to " + L.fmtPct(u.both_pct.p90) +
        ", so the window is " + u.robustness + ". Hours near the window's edges change most between terrain variations. " +
        "This covers terrain-height error only, not errors in Sun or Earth positions.";
    }
    renderMast();
  }

  function renderMast() {
    const hs = S.height, note = $("#mastNote");
    if (!hs) { note.textContent = ""; return; }
    if (S.tab === "mast") {
      const z = sizedCtx($("#heightChart"), 230);
      if (z) D.drawHeight(z.ctx, z.W, z.H, hs);
    }
    const j = hs.biggest_jumps.both_pct, rows = hs.rows;
    const total = Math.abs(rows[rows.length - 1].both_pct - rows[0].both_pct);
    const site = S.sel ? S.data[S.sel.siteId].site.name : "this site";
    note.textContent = j.is_flip
      ? "Raising the antenna and panels from " + j.from_height_m + " m to " + j.to_height_m + " m adds " +
        Math.round(j.jump_pct) + " percentage points of power-and-link time at " + site + " during this window."
      : "Between " + rows[0].height_m + " m and " + rows[rows.length - 1].height_m + " m, power-and-link time at " +
        site + " changes by only " + Math.round(total) + " percentage points during this window.";
  }

  function renderFocusOptions() {
    const sel = $("#focus");
    sel.replaceChildren(...S.order.map((id) => h("option", { value: id, text: S.data[id].site.name })));
    sel.value = S.focus;
  }

  function renderAll() {
    renderHorizon(); renderTimeline(); renderPano(); renderReadout(); renderCards(); renderWindows(); renderDetail();
    $("#scrub").value = S.tIdx;
  }

  function redrawLive() {
    if (S.raf) return;
    S.raf = requestAnimationFrame(() => {
      S.raf = 0;
      $("#scrub").value = S.tIdx;
      renderHorizon(); renderTimeline(); renderPano(); renderReadout();
    });
  }

  /* ------------------------------------------------------------------- actions */
  function readForm() {
    const objective = $("#objective").value;
    return {
      ids: selectedIds(), start: $("#start").value, end: $("#end").value,
      durH: Number($("#durDays").value) * 24, objective,
      batteryH: objective === "survive" ? Number($("#battery").value) : null,
      heightM: Number($("#mast").value),
    };
  }

  function stopPlay() {
    if (S.timer) { clearInterval(S.timer); S.timer = null; }
    $("#play").textContent = "Play time-lapse";
  }

  async function refresh(prefer) {
    toast("");
    const f = readForm();
    if (!f.ids.length) { toast("Choose at least one site to compare."); return; }
    if (!f.start || !f.end) { toast("Pick a start and end date."); return; }
    if (f.end <= f.start) { toast("The end date must be after the start date."); return; }
    if (!(f.durH > 0)) { toast("Enter a mission length greater than zero."); return; }
    stopPlay(); busy(true);
    try {
      const days = (Date.parse(f.end) - Date.parse(f.start)) / 864e5;
      const stepH = days <= 120 ? 1 : days <= 240 ? 2 : 3;
      const series = await api("/api/series", { site_ids: f.ids, start: f.start, end: f.end, step_h: stepH, height_m: f.heightM });
      S.data = series.sites; S.order = f.ids; S.last = f;
      S.n = S.data[f.ids[0]].times.length;
      S.tIdx = Math.min(S.tIdx, S.n - 1);
      $("#scrub").max = S.n - 1;
      if (!f.ids.includes(S.focus)) S.focus = f.ids[0];
      S.sel = null; S.highlight = null; S.prob = null; S.height = null;
      renderFocusOptions();

      const results = await Promise.allSettled(f.ids.map((id) => api("/api/windows", {
        site_id: id, start: f.start, end: f.end, duration_h: f.durH, objective: f.objective,
        battery_h: f.batteryH, height_m: f.heightM, top_n: 3,
      })));
      S.windows = {};
      let firstErr = null;
      results.forEach((r, i) => { if (r.status === "fulfilled") S.windows[f.ids[i]] = r.value; else firstErr = firstErr || r.reason; });
      if (firstErr && !Object.keys(S.windows).length) toast(firstErr.message);
      else if (firstErr) toast("Some sites could not be searched: " + firstErr.message);
      renderAll();

      let pick = null;
      if (prefer) {
        const res = S.windows[prefer.siteId];
        const rank = res ? res.windows.findIndex((w) => w.start === prefer.start) : -1;
        if (rank >= 0) pick = { siteId: prefer.siteId, rank };
      }
      if (!pick) { const b = allWindows()[0]; if (b) pick = { siteId: b.siteId, rank: b.rank }; }
      if (pick) await selectWindow(pick.siteId, pick.rank);
    } catch (e) {
      toast(e.message);
    } finally {
      busy(false);
    }
  }

  async function selectWindow(siteId, rank) {
    const res = S.windows[siteId], site = S.data[siteId];
    if (!res || !site) return;
    const w = res.windows[rank], f = S.last;
    S.sel = { siteId, rank, w };
    S.focus = siteId; $("#focus").value = siteId;
    const a = L.indexForTime(site.times, w.start), b = L.indexForTime(site.times, w.end);
    S.highlight = { siteId, start: a, end: Math.max(b, a + 1) };
    S.tIdx = a; S.heading = Math.round(site.sun_az[a]);
    S.prob = null; S.height = null;
    renderAll();
    const token = ++S.token;
    try {
      const common = { site_id: siteId, start: f.start, end: f.end };
      const [prob, hs] = await Promise.all([
        api("/api/window_probability", { ...common, duration_h: f.durH, rank, objective: f.objective, battery_h: f.batteryH, height_m: f.heightM }),
        api("/api/height", { ...common, window_start: w.start_index, window_end: w.end_index }),
      ]);
      if (token !== S.token) return;
      S.prob = prob; S.height = hs;
      renderDetail();
    } catch (e) {
      if (token === S.token) toast(e.message);
    }
  }

  function showTab(name) {
    S.tab = name;
    for (const b of $$("[role=tab]")) {
      const on = b.dataset.tab === name;
      b.setAttribute("aria-selected", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
      $("#tab-" + b.dataset.tab).hidden = !on;
    }
    renderDetail(); renderMast(); renderPano();
  }

  /* --------------------------------------------------------------- copilot */
  const EXAMPLES = [
    "Which site is best for a 14-day mission in March, power first?",
    "Can we survive a 10-day mission with a 60-hour battery?",
    "Compare sites a and b with a 5 m mast for 7 days",
  ];

  async function ask(message) {
    const btn = $("#askGo");
    btn.disabled = true; btn.textContent = "Thinking…"; toast("");
    try {
      const r = await api("/api/copilot", { message, mode: mode() });
      renderAnswer(r);
      await applyView(r);
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false; btn.textContent = "Ask";
    }
  }

  function renderAnswer(r) {
    $("#answer").hidden = false;
    $("#answerText").textContent = r.explanation.text;
    const v = r.verification, ver = $("#verify");
    ver.className = "verify " + (v.verified ? "ok" : "bad");
    ver.textContent = v.verified
      ? "Checked against the data: " + v.numbers_checked + " numbers and " + v.dates_checked +
        " dates all appear in the computed results. This is a value-presence check, not a semantic fact-check. " +
        (r.explanation.source === "llm" ? "Written by a language model, then checked for matching values."
          : "Written from a template, then checked for matching values.")
      : "Not fully verified: " + [...v.unmatched_numbers, ...v.unbacked_dates, ...v.unknown_sites, ...v.unbacked_labels].join(", ");
    const as = $("#assumed");
    as.replaceChildren();
    if (r.assumptions.length) {
      as.append(h("p", { text: "What I assumed:" }), h("ul", {}, r.assumptions.map((a) => h("li", { text: a }))));
    }
    const tr = $("#trace");
    tr.replaceChildren(h("summary", { text: "How this answer was produced (" + r.trace.length + " steps)" }),
      h("ol", {}, r.trace.map((t) => h("li", {}, h("strong", { text: t.agent }), " " + t.action + " in " + t.ms + " ms ",
        h("code", { text: JSON.stringify(t.detail) })))));
  }

  function applyView(r) {
    const v = r.view;
    for (const box of $$("#siteChips input")) box.checked = v.site_ids.includes(box.value);
    $("#start").value = v.start; $("#end").value = v.end;
    $("#durDays").value = +(v.duration_h / 24).toFixed(2);
    $("#objective").value = v.objective;
    $("#batteryRow").hidden = v.objective !== "survive";
    if (v.battery_h != null) $("#battery").value = v.battery_h;
    $("#mast").max = String(maxMast());
    $("#mast").value = Math.min(maxMast(), Math.round(v.height_m));
    $("#mastOut").textContent = $("#mast").value + " m";
    const top = r.ranking[0];
    return refresh(top ? { siteId: top.site_id, start: top.start_iso } : null);
  }

  /* ----------------------------------------------------------------- wiring */
  function download(name, blob) {
    const a = h("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  function wire() {
    $("#controls").addEventListener("submit", (e) => { e.preventDefault(); refresh(); });
    $("#objective").addEventListener("change", (e) => { $("#batteryRow").hidden = e.target.value !== "survive"; });
    $("#mast").addEventListener("input", (e) => { $("#mastOut").textContent = e.target.value + " m"; });
    $("#focus").addEventListener("change", (e) => { S.focus = e.target.value; renderAll(); });
    $("#scrub").addEventListener("input", (e) => { S.tIdx = Number(e.target.value); redrawLive(); });
    $("#play").addEventListener("click", () => {
      if (S.timer) { stopPlay(); return; }
      if (!S.n) return;
      $("#play").textContent = "Pause";
      const speed = Math.max(1, Math.round(S.n / 500));
      S.timer = setInterval(() => { S.tIdx = (S.tIdx + speed) % S.n; redrawLive(); }, 60);
    });
    for (const r of $$("input[name=mode]")) r.addEventListener("change", (e) => {
      document.body.dataset.mode = e.target.value; renderAll();
    });
    for (const b of $$("[role=tab]")) b.addEventListener("click", () => showTab(b.dataset.tab));

    const tl = $("#timeline");
    const scrubTo = (e) => {
      if (!S.n) return;
      const rect = tl.getBoundingClientRect();
      S.tIdx = D.timelineIndexFromX(e.clientX - rect.left, rect.width, S.n);
      redrawLive();
    };
    tl.addEventListener("pointerdown", (e) => { tl.setPointerCapture(e.pointerId); scrubTo(e); });
    tl.addEventListener("pointermove", (e) => { if (tl.hasPointerCapture(e.pointerId)) scrubTo(e); });

    const pano = $("#pano");
    let drag = null;
    pano.addEventListener("pointerdown", (e) => { pano.setPointerCapture(e.pointerId); drag = e.clientX; pano.classList.add("dragging"); });
    pano.addEventListener("pointermove", (e) => {
      if (drag == null) return;
      const rect = pano.getBoundingClientRect();
      S.heading = ((S.heading - ((e.clientX - drag) / rect.width) * Number($("#fov").value)) % 360 + 360) % 360;
      drag = e.clientX; renderPano();
    });
    const endDrag = () => { drag = null; pano.classList.remove("dragging"); };
    pano.addEventListener("pointerup", endDrag); pano.addEventListener("pointercancel", endDrag);
    pano.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = $("#fov");
      f.value = L.clamp(Number(f.value) + e.deltaY * 0.05, Number(f.min), Number(f.max));
      renderPano();
    }, { passive: false });
    for (const id of ["#fov", "#stretch", "#enlarge"]) $(id).addEventListener("input", renderPano);

    ["#camTactical", "#camPov", "#camPolar"].forEach((id) => {
      const el = $(id);
      if (el) {
        el.addEventListener("click", () => {
          ["#camTactical", "#camPov", "#camPolar"].forEach((i) => {
            const b = $(i);
            if (b && b.classList) b.classList.remove("active");
          });
          if (el.classList) el.classList.add("active");
          if (typeof window !== "undefined" && window.Scene3D && window.Scene3D.setCamera) {
            window.Scene3D.setCamera(el.dataset.cam || el.getAttribute("data-cam"));
          }
        });
      }
    });

    $("#askForm").addEventListener("submit", (e) => {
      e.preventDefault();
      const m = $("#ask").value.trim();
      if (!m) { toast("Type a question first, or pick one of the examples."); return; }
      ask(m);
    });
    $("#examples").append(...EXAMPLES.map((t) => h("button", { type: "button", onclick: () => { $("#ask").value = t; $("#ask").focus(); } }, t)));

    $("#csv").addEventListener("click", () => {
      const s = focusSite(); if (!s) return;
      download(s.site.id + "_hourly.csv", new Blob([L.buildCsv(s)], { type: "text/csv" }));
    });
    $("#png").addEventListener("click", () => {
      $("#horizon").toBlob((b) => b && download("sky_plot.png", b));
    });

    let resizeT = 0;
    window.addEventListener("resize", () => { clearTimeout(resizeT); resizeT = setTimeout(renderAll, 120); });
  }

  /* -------------------------------------------------------------------- init */
  async function init() {
    wire();
    try {
      S.meta = await api("/api/meta");
    } catch (e) { toast(e.message); return; }
    const banner = $("#banner");
    S.meta.warnings.forEach((w, i) => banner.append(h("p", { class: i === 0 && S.meta.synthetic ? "strong" : "", text: w })));
    $("#mast").max = String(maxMast());
    renderLegend();
    $("#siteChips").append(...S.meta.sites.map((s) => h("label", {
      title: s.representative
        ? "Representative interior point from the official region polygon; not a certified landing coordinate."
        : (s.note || ""),
    }, h("input", { type: "checkbox", value: s.id, checked: true }), s.name)));
    const today = new Date(), end = new Date(today.getTime() + 120 * 864e5);
    const iso = (d) => d.toISOString().slice(0, 10);
    $("#start").value = iso(today); $("#end").value = iso(end);
    $("#horizon").getContext("2d");
    S.focus = S.meta.sites[0].id;
    await refresh();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
