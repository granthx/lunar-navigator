// Run: node tests/frontend.test.js   (no dependencies)
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const Lib = require("../frontend/lib.js");
globalThis.Lib = Lib;
const Draw = require("../frontend/draw.js");

const fx = (n) => JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", n), "utf8"));
let passed = 0;
const test = (name, fn) => { fn(); passed++; console.log("ok -", name); };

/* A canvas context that records calls and throws on any non-finite number argument. */
function strictCtx() {
  const calls = {};
  const grad = { addColorStop(o, c) { assert.ok(o >= 0 && o <= 1, "bad gradient stop " + o); assert.ok(typeof c === "string"); } };
  const target = { measureText: (t) => ({ width: String(t).length * 6 }) };
  return {
    calls,
    ctx: new Proxy(target, {
      get(t, p) {
        if (p in t) return t[p];
        if (p === "createLinearGradient" || p === "createRadialGradient") {
          return (...a) => { a.forEach((v) => assert.ok(Number.isFinite(v), `${String(p)} got ${v}`)); return grad; };
        }
        return (...a) => {
          calls[p] = (calls[p] || 0) + 1;
          a.forEach((v) => { if (typeof v === "number") assert.ok(Number.isFinite(v), `${String(p)}(${a}) has non-finite arg`); });
          if (p === "fillText") assert.ok(!/NaN|undefined/.test(String(a[0])), "bad text: " + a[0]);
        };
      },
      set(t, p, v) { t[p] = v; return true; },
    }),
  };
}

test("wrapDeg maps into [-180, 180)", () => {
  assert.strictEqual(Lib.wrapDeg(190), -170);
  assert.strictEqual(Lib.wrapDeg(-190), 170);
  assert.strictEqual(Lib.wrapDeg(0), 0);
  assert.strictEqual(Lib.wrapDeg(360), 0);
});

test("horizonAt interpolates periodically", () => {
  const az = Array.from({ length: 360 }, (_, i) => i);
  const el = az.map((a) => (a === 359 ? 4 : 0));
  assert.ok(Math.abs(Lib.horizonAt(az, el, 359.5) - 2) < 1e-9);
  assert.ok(Math.abs(Lib.horizonAt(az, el, 360)) < 1e-9);
  assert.ok(Math.abs(Lib.horizonAt(az, el, -0.5) - 2) < 1e-9);
  assert.ok(Math.abs(Lib.horizonAt(az, el, 719.5) - 2) < 1e-9);
});

test("pxFromAz centres the heading and wraps across north", () => {
  assert.strictEqual(Lib.pxFromAz(90, 90, 100, 1000), 500);
  assert.strictEqual(Lib.pxFromAz(100, 90, 100, 1000), 600);
  assert.strictEqual(Lib.pxFromAz(5, 355, 100, 1000), 600);
});

test("indexForTime finds nearest sample", () => {
  const times = ["2027-01-01T00:00", "2027-01-01T01:00", "2027-01-01T02:00", "2027-01-01T03:00"];
  assert.strictEqual(Lib.indexForTime(times, "2027-01-01T02:00"), 2);
  assert.strictEqual(Lib.indexForTime(times, "2027-01-01T02:20"), 2);
  assert.strictEqual(Lib.indexForTime(times, "2027-01-01T02:40"), 3);
  assert.strictEqual(Lib.indexForTime(times, "2026-12-01T00:00"), 0);
  assert.strictEqual(Lib.indexForTime(times, "2028-01-01T00:00"), 3);
});

test("buildCsv matches the data", () => {
  const s = fx("series.json").sites.demo_a;
  const lines = Lib.buildCsv(s).trim().split("\n");
  assert.strictEqual(lines.length, s.times.length + 1);
  const f = lines[1].split(",");
  assert.strictEqual(f[0], s.times[0]);
  assert.strictEqual(Number(f[2]), s.sun_el[0]);
  assert.strictEqual(f[5], Lib.CODE_NAMES[s.code[0]]);
});

test("fixture data is sane (guards against API shape changes)", () => {
  const d = fx("series.json");
  for (const id of ["demo_a", "demo_b", "demo_e"]) {
    const s = d.sites[id];
    const n = s.times.length;
    for (const k of ["code", "sun_az", "sun_el", "earth_az", "earth_el"]) assert.strictEqual(s[k].length, n, k);
    assert.strictEqual(s.horizon_az.length, 360);
    assert.ok(s.code.every((c) => c >= 0 && c <= 3));
  }
});

test("horizon plot draws for every site and every time index (no NaN)", () => {
  const d = fx("series.json");
  for (const id of Object.keys(d.sites)) {
    const s = d.sites[id];
    for (const t of [0, 100, s.times.length - 1]) {
      const { ctx, calls } = strictCtx();
      Draw.drawHorizon(ctx, 900, 320, s, t);
      assert.ok(calls.arc >= 2 && calls.fill >= 1 && calls.stroke >= 1);
    }
  }
});

test("timeline draws all rows, highlight and scrubber; click mapping is consistent", () => {
  const d = fx("series.json");
  const sites = Object.values(d.sites);
  const n = sites[0].times.length;
  const H = Draw.timelineHeight(sites.length);
  const { ctx, calls } = strictCtx();
  Draw.drawTimeline(ctx, 900, H, sites, 123, { siteId: "demo_a", start: 50, end: 200 });
  assert.ok(calls.fillRect >= sites.length * n);
  assert.ok(calls.strokeRect === 1);
  assert.strictEqual(Draw.timelineIndexFromX(0, 900, n), 0);
  assert.strictEqual(Draw.timelineIndexFromX(899, 900, n), n - 1);
  const mid = Draw.timelineIndexFromX(92 + (900 - 92 - 10) / 2, 900, n);
  assert.ok(Math.abs(mid - n / 2) <= 1);
});

test("band and height charts draw; flip annotation text comes from data", () => {
  const { ctx, calls } = strictCtx();
  Draw.drawBand(ctx, 700, 220, fx("prob.json"));
  assert.ok(calls.fill >= 1 && calls.stroke >= 3);
  const hs = fx("height.json");
  const texts = [];
  const c2 = strictCtx();
  const orig = c2.ctx.fillText;
  const wrapped = new Proxy(c2.ctx, { get: (t, p) => (p === "fillText" ? (...a) => { texts.push(a[0]); return orig(...a); } : t[p]) });
  Draw.drawHeight(wrapped, 700, 240, hs);
  const j = hs.biggest_jumps.both_pct;
  if (j.is_flip) assert.ok(texts.includes("+" + Math.round(j.jump_pct) + " points"), texts.join("|"));
  else assert.ok(!texts.some((t) => /points/.test(t)));
  assert.ok(texts.includes(hs.rows[0].height_m + " m"));
});

test("panorama draws across headings, zoom levels and stretch", () => {
  const s = fx("series.json").sites.demo_b;
  for (const heading of [0, 90, 180, 359])
    for (const fov of [20, 100, 180])
      for (const stretch of [1, 3, 5]) {
        const { ctx, calls } = strictCtx();
        Draw.drawPano(ctx, 900, 380, s, 300, { heading, fov, stretch, enlarge: stretch === 3 });
        assert.ok(calls.fill >= 1);
      }
});

test("empty state draws text", () => {
  const { ctx, calls } = strictCtx();
  Draw.drawEmpty(ctx, 400, 100, "Pick at least one site", true);
  assert.strictEqual(calls.fillText, 1);
});

console.log(`\n${passed} frontend tests passed`);
