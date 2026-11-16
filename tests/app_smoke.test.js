// Headless smoke test: real index.html structure + real app.js + live API, with a fake DOM.
// Needs the server:  python3 -m uvicorn backend.api.server:app --port 8765
// Run: node tests/app_smoke.test.js
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const BASE = process.env.API_BASE || "http://127.0.0.1:8765";
const html = fs.readFileSync(path.join(__dirname, "../frontend/index.html"), "utf8");

/* strict canvas context (throws on non-finite numbers) */
function strictCtx() {
  const grad = { addColorStop() {} };
  const t = { measureText: (s) => ({ width: String(s).length * 6 }) };
  return new Proxy(t, {
    get(o, p) {
      if (p in o) return o[p];
      if (p === "createLinearGradient" || p === "createRadialGradient")
        return (...a) => { a.forEach((v) => assert.ok(Number.isFinite(v), p + " " + v)); return grad; };
      return (...a) => {
        o.__calls = (o.__calls || 0) + 1;
        a.forEach((v) => { if (typeof v === "number") assert.ok(Number.isFinite(v), `${String(p)}(${a})`); });
      };
    },
    set(o, p, v) { o[p] = v; return true; },
  });
}

/* ---- minimal fake DOM ---- */
class Node_ { constructor(t) { this.nodeType = 3; this.text = t; } }
class El {
  constructor(tag, attrs = {}) {
    this.nodeType = 1; this.tag = tag; this.attrs = { ...attrs }; this.children = []; this._text = "";
    this.listeners = {}; this.dataset = {}; this.style = {}; this.hidden = "hidden" in attrs;
    this.value = attrs.value ?? ""; this.checked = "checked" in attrs; this.disabled = false;
    this.className = attrs.class || ""; this.clientWidth = 900; this.clientHeight = Number(attrs.h) || 300;
    this.tabIndex = 0; this.min = attrs.min; this.max = attrs.max; this.id = attrs.id; this.name = attrs.name;
    this.classList = { add: () => {}, remove: () => {} };
    this._ctx = null;
  }
  get textContent() { return this._text + this.children.map((c) => (c.nodeType === 3 ? c.text : c.textContent)).join(""); }
  set textContent(v) { this._text = String(v); this.children = []; }
  append(...kids) {
    for (const k of kids) {
      if (typeof k === "string") this.children.push(new Node_(k));
      else this.children.push(k);
    }
  }
  replaceChildren(...kids) { this.children = []; this._text = ""; this.append(...kids); }
  setAttribute(k, v) { this.attrs[k] = v; if (k === "class") this.className = v; if (k === "value") this.value = v; if (k === "checked") this.checked = true; }
  getAttribute(k) { return this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  dispatch(t, ev = {}) {
    for (const f of this.listeners[t] || []) f({ target: this, preventDefault() {}, pointerId: 1, clientX: 300, deltaY: 40, ...ev });
  }
  click() { this.dispatch("click"); }
  focus() {}
  getContext() { return (this._ctx ||= strictCtx()); }
  getBoundingClientRect() { return { left: 0, top: 0, width: 900, height: 300 }; }
  setPointerCapture() {} hasPointerCapture() { return true; } releasePointerCapture() {}
  toBlob(cb) { cb(null); }
  remove() {}
  walk(fn) { fn(this); for (const c of this.children) if (c.nodeType === 1) c.walk(fn); }
}

const byId = {}, roleTabs = [], modeRadios = [];
const all = [];
// build elements from index.html: every element with an id, plus radios named "mode", plus role=tab
for (const m of html.matchAll(/<([a-z0-9]+)([^>]*)>/g)) {
  const attrs = {};
  for (const a of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[a[1]] = a[2] ?? "";
  if (attrs.id || attrs.name === "mode") {
    const el = new El(m[1], attrs);
    if (attrs.id) byId[attrs.id] = el;
    if (attrs.role === "tab") { roleTabs.push(el); el.dataset.tab = attrs["data-tab"]; }
    if (attrs.name === "mode") modeRadios.push(el);
    all.push(el);
  }
}
const body = new El("body"); body.dataset.mode = "planner";
const docListeners = {};
globalThis.document = {
  body,
  addEventListener: (t, f) => { docListeners[t] = f; },
  createElement: (t) => new El(t),
  createTextNode: (t) => new Node_(String(t)),
  querySelector(sel) {
    if (sel.startsWith("#") && !sel.includes(" ")) { const e = byId[sel.slice(1)]; assert.ok(e, "no element " + sel); return e; }
    if (sel === "#siteChips input:checked") { let r = null; byId.siteChips.walk((e) => { if (!r && e.tag === "input" && e.checked) r = e; }); return r; }
    throw new Error("unsupported selector " + sel);
  },
  querySelectorAll(sel) {
    if (sel === "[role=tab]") return roleTabs;
    if (sel === "input[name=mode]") return modeRadios;
    if (sel === "#siteChips input:checked") { const r = []; byId.siteChips.walk((e) => { if (e.tag === "input" && e.checked) r.push(e); }); return r; }
    if (sel === "#siteChips input") { const r = []; byId.siteChips.walk((e) => { if (e.tag === "input") r.push(e); }); return r; }
    throw new Error("unsupported selector " + sel);
  },
};
for (const id of ["siteChips", "examples", "cards", "winList", "banner", "answer", "assumed", "trace", "focus"]) assert.ok(byId[id], id);
byId.objective.value = "balanced";   // a real <select> reports its first/selected option
byId.stretch.value = "3";
globalThis.window = globalThis;
globalThis.devicePixelRatio = 1;
globalThis.addEventListener = () => {};
globalThis.requestAnimationFrame = (f) => setTimeout(f, 0);
globalThis.cancelAnimationFrame = clearTimeout;
const realFetch = globalThis.fetch;
globalThis.fetch = (u, i) => realFetch(u.startsWith("/") ? BASE + u : u, i);

globalThis.Lib = require("../frontend/lib.js");
globalThis.Draw = require("../frontend/draw.js");
require("../frontend/app.js");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function until(fn, label, ms = 40000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return; await sleep(100); }
  throw new Error("timeout waiting for: " + label + " | toast: " + byId.toast.textContent);
}
const settled = () => !byId.go.disabled && byId.go.textContent === "Compare sites";
let passed = 0;
const ok = (n) => { passed++; console.log("ok -", n); };

(async () => {
  docListeners.DOMContentLoaded();
  await until(() => byId.winList.textContent.includes("Show") === false && byId.bandNote.textContent.length > 20 && byId.mastNote.textContent.length > 10 && settled(), "initial load");
  assert.ok(byId.toast.hidden, "unexpected error: " + byId.toast.textContent);
  ok("init: loads meta, runs comparison, selects best window, fills detail panels");

  assert.strictEqual(byId.siteChips.children.length, 5);
  assert.ok(byId.banner.children.length >= 2 && /SYNTHETIC/.test(byId.banner.textContent), "synthetic warning must be visible");
  assert.strictEqual(byId.cards.children.length, 5);
  assert.ok(/Power \+ comms/.test(byId.cards.textContent));
  assert.strictEqual(byId.legend.children.length, 4);
  assert.ok(/power only/.test(byId.legend.textContent) && /comms only/.test(byId.legend.textContent) &&
    /power \+ comms/.test(byId.legend.textContent));
  const swatches = byId.legend.children.map((li) => li.children.find((c) => c.tag === "i").attrs.style);
  assert.deepStrictEqual(swatches, ["background:#23262f", "background:#d9a441",
    "background:#3a6ea5", "background:#8fe3b0"]);
  assert.strictEqual(String(byId.mast.max), "15");
  ok("banner warns about synthetic data; one card per site; legend matches timeline colours");

  assert.ok(/Sun:/.test(byId.readout.textContent) && !/NaN|undefined/.test(byId.readout.textContent));
  assert.ok(/window is (robust|moderate|fragile)/.test(byId.bandNote.textContent));
  assert.ok(/percentage points/.test(byId.mastNote.textContent));
  ok("readout and detail text are well-formed");

  // windows table is built from API data
  let rows = 0; byId.winList.walk((e) => { if (e.tag === "tr") rows++; });
  assert.ok(rows >= 2, "table rows " + rows);
  ok("windows table rendered");

  // select another window via its button
  let pick = null; byId.winList.walk((e) => { if (e.tag === "button" && e.className === "pick") pick = pick || []; if (pick && e.tag === "button" && e.className === "pick") pick.push(e); });
  pick[Math.min(1, pick.length - 1)].click();
  await sleep(1500);
  assert.ok(byId.bandNote.textContent.length > 20 && byId.toast.hidden);
  ok("selecting a window updates detail without errors");

  // tabs
  for (const t of roleTabs) { t.click(); await sleep(50); }
  assert.strictEqual(byId["tab-moon"].hidden, false);
  assert.strictEqual(byId["tab-windows"].hidden, true);
  assert.ok(byId.pano.getContext().__calls > 0, "panorama drew");
  byId.pano.dispatch("pointerdown", { clientX: 100 }); byId.pano.dispatch("pointermove", { clientX: 250 }); byId.pano.dispatch("pointerup");
  byId.pano.dispatch("wheel", { deltaY: -200 });
  byId.stretch.value = "5"; byId.stretch.dispatch("input");
  byId.fov.value = "40"; byId.fov.dispatch("input");
  roleTabs[1].click();
  assert.ok(byId.heightChart.getContext().__calls > 0, "height chart drew");
  ok("tabs, panorama drag/zoom/stretch, height chart");

  // scrubbing, timeline click, play
  byId.scrub.value = "50"; byId.scrub.dispatch("input"); await sleep(50);
  byId.timeline.dispatch("pointerdown", { clientX: 500 }); byId.timeline.dispatch("pointermove", { clientX: 600 });
  byId.play.click(); await sleep(300); assert.strictEqual(byId.play.textContent, "Pause"); byId.play.click();
  assert.strictEqual(byId.play.textContent, "Play time-lapse");
  ok("scrubber, timeline drag, play and pause");

  // audience mode
  modeRadios[1].value = "public"; modeRadios[1].dispatch("change", { target: { value: "public" } });
  assert.strictEqual(body.dataset.mode, "public");
  assert.ok(/Sunlight/.test(byId.cards.textContent) && !/Longest dark stretch/.test(byId.cards.textContent));
  assert.ok(/the lander (has|has both)/.test(byId.readout.textContent), byId.readout.textContent);
  modeRadios[0].dispatch("change", { target: { value: "planner" } });
  ok("public mode changes wording, planner mode restores it");

  // form validation errors are explained, not silent
  byId.end.value = byId.start.value; byId.controls.dispatch("submit");
  await sleep(100);
  assert.ok(!byId.toast.hidden && /end date must be after/.test(byId.toast.textContent));
  byId.end.value = "2027-03-01"; byId.start.value = "2027-01-01";
  ok("invalid dates give a clear message");

  // objective switch shows battery field
  byId.objective.value = "survive"; byId.objective.dispatch("change", { target: byId.objective });
  assert.strictEqual(byId.batteryRow.hidden, false);
  byId.battery.value = "40";
  byId.durDays.value = "5";
  byId.controls.dispatch("submit");
  await until(() => settled() && byId.toast.hidden && /survive|battery|Exceeds/.test(byId.winList.textContent + "x") || settled(), "survive refresh");
  await sleep(1500);
  assert.ok(byId.toast.hidden, byId.toast.textContent);
  ok("battery objective runs end to end");

  // copilot
  byId.ask.value = "compare sites a and b for 10 days, power first";
  byId.askForm.dispatch("submit");
  await until(() => !byId.answer.hidden && !byId.askGo.disabled && settled(), "copilot answer");
  await sleep(1500);
  assert.ok(byId.answerText.textContent.length > 30);
  assert.ok(/ok/.test(byId.verify.className) && /Checked against the data/.test(byId.verify.textContent) &&
    /value-presence check/.test(byId.verify.textContent) && !/all supported/.test(byId.verify.textContent),
    byId.verify.textContent);
  assert.ok(byId.trace.children.length === 2);
  assert.strictEqual(byId.start.value.length, 10);
  assert.ok(selected().join() === "demo_a,demo_b", selected().join());

  // A request above the product limit is capped and reported, not applied inconsistently.
  byId.ask.value = "use a 30 m mast for 7 days at site a";
  byId.askForm.dispatch("submit");
  await until(() => !byId.askGo.disabled && settled() && /15 m/.test(byId.assumed.textContent), "mast clamp");
  await sleep(800);
  assert.strictEqual(String(byId.mast.value), "15");
  assert.ok(byId.toast.hidden, byId.toast.textContent);
  ok("copilot answers, verifies, applies the request to the controls and charts");

  // an empty question is rejected clearly
  byId.ask.value = "   "; byId.askForm.dispatch("submit");
  assert.ok(/Type a question first/.test(byId.toast.textContent));
  ok("empty question gives a clear message");

  console.log(`\n${passed} app smoke tests passed`);
  process.exit(0);
})().catch((e) => { console.error("FAIL:", e && e.stack || e); process.exit(1); });

function selected() { const r = []; byId.siteChips.walk((e) => { if (e.tag === "input" && e.checked) r.push(e.value); }); return r; }
