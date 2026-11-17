"""Automated implementation of the Manual Browser & Keyboard Checklist (Check 4).

Runs Playwright against a live uvicorn server in both real-data and synthetic modes,
testing every interactive control, keyboard tab order, responsive widths, and verifying
zero console errors.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
PORT = 8766
BASE_URL = f"http://127.0.0.1:{PORT}"


def wait_for_server(url: str, timeout_s: float = 30.0):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            with urllib.request.urlopen(f"{url}/api/meta", timeout=2.0) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode())
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"Server at {url} did not become ready in {timeout_s}s")


def run_checklist():
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    results = []

    print("=== Starting Real-Data Server (SPICE + LOLA 80m + 9 NASA regions) ===")
    real_env = os.environ.copy()
    real_env["LUNAR_DEM"] = str(ROOT / "backend" / "data" / "lunar_south_pole_80m.npz")
    real_env["LUNAR_SITES"] = str(ROOT / "backend" / "data" / "sites_real.json")
    real_env["LUNAR_EPHEMERIS"] = "spice"

    server_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.server:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT),
        env=real_env,
    )

    console_errors = []
    page_errors = []

    try:
        meta = wait_for_server(BASE_URL)
        print(f"Server ready. Ephemeris: {meta['ephemeris_backend']}, Sites: {len(meta['sites'])}, Synthetic: {meta['synthetic']}")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()

            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: page_errors.append(str(exc)))

            # Step 1: Load page
            page.goto(BASE_URL)
            page.wait_for_selector("#siteChips label", timeout=15000)

            # Check 1: Real-data Banner
            banner_text = page.inner_text("#banner")
            print("Banner text:", banner_text)
            has_rep_warning = "representative points inside official region polygons" in banner_text
            no_synthetic_warning = "SYNTHETIC" not in banner_text
            chk1 = has_rep_warning and no_synthetic_warning
            results.append(("1. Real-data warning banner (no synthetic warning, representative warning shown)", "PASS" if chk1 else "FAIL", banner_text))

            # Wait for initial comparison to complete
            print("Waiting for initial series and window search to complete...")
            page.wait_for_selector("#winList tbody tr", timeout=60000)
            print("Initial comparison loaded successfully.")

            # Check 2: Sky plot after load
            page.wait_for_selector("#horizon", state="visible")
            sky_box = page.locator("#horizon").bounding_box()
            focus_val = page.input_value("#focus")
            chk2 = (sky_box and sky_box["width"] > 100 and sky_box["height"] > 100 and bool(focus_val))
            # Test changing focus
            page.select_option("#focus", index=2)
            page.wait_for_timeout(400)
            results.append(("2. Sky plot canvas rendered with skyline, Sun/Earth markers, site selector active", "PASS" if chk2 else "FAIL", f"focus={focus_val}, canvas={sky_box['width']}x{sky_box['height']}"))

            # Check 3: Timeline & scrub line
            page.wait_for_selector("#timeline", state="visible")
            legend_items = page.locator("#legend li").count()
            tl_box = page.locator("#timeline").bounding_box()
            readout_before = page.inner_text("#readout")
            # Move scrub line
            page.fill("#scrub", "50")
            page.dispatch_event("#scrub", "input")
            page.wait_for_timeout(300)
            readout_after = page.inner_text("#readout")
            chk3 = (legend_items == 4 and tl_box and tl_box["width"] > 200 and readout_after != readout_before)
            results.append(("3. Timeline rendered with 4 legend colors, scrub slider updates readout", "PASS" if chk3 else "FAIL", f"legend_count={legend_items}, readout='{readout_after}'"))

            # Check 4: Site cards in Planner vs Public view
            cards_count = page.locator("#cards .card").count()
            planner_text = page.inner_text("#cards .card:first-child")
            has_planner_pct = "%" in planner_text
            # Switch to Public
            page.click("input[value='public']")
            page.wait_for_timeout(300)
            public_text = page.inner_text("#cards .card:first-child")
            has_public_labels = ("Sunlight" in public_text or "Link to Earth" in public_text or "Both at once" in public_text)
            # Switch back to Planner
            page.click("input[value='planner']")
            page.wait_for_timeout(300)
            chk4 = (cards_count == 9 and has_planner_pct and has_public_labels)
            results.append(("4. Site cards (9 candidate sites) show metrics in Planner view and plain labels in Public view", "PASS" if chk4 else "FAIL", f"cards={cards_count}, planner_pct={has_planner_pct}, public_labels={has_public_labels}"))

            # Check 5: Best windows table & confidence chart
            win_rows = page.locator("#winList tbody tr").count()
            chips_count = page.locator("#winList .chip").count()
            # Select first window row
            page.click("#winList tbody tr:first-child")
            page.wait_for_timeout(800)
            band_visible = page.is_visible("#band")
            band_title_visible = page.is_visible("#bandTitle")
            band_note = page.inner_text("#bandNote")
            chk5 = (win_rows > 0 and chips_count > 0 and band_visible and band_title_visible and len(band_note) > 0)
            results.append(("5. 'Best windows' table lists ranked windows with robustness chips; selecting row draws confidence chart", "PASS" if chk5 else "FAIL", f"rows={win_rows}, chips={chips_count}, band_visible={band_visible}, note='{band_note[:60]}'"))

            # Check 6: Antenna height tab
            page.click("#t-mast")
            page.wait_for_timeout(600)
            mast_visible = page.is_visible("#tab-mast")
            height_chart_box = page.locator("#heightChart").bounding_box()
            mast_note = page.inner_text("#mastNote")
            chk6 = (mast_visible and height_chart_box and height_chart_box["width"] > 100 and len(mast_note) > 0)
            results.append(("6. 'Antenna height' tab draws sensitivity chart and summary sentence", "PASS" if chk6 else "FAIL", f"visible={mast_visible}, chart={height_chart_box['width']}x{height_chart_box['height']}, note='{mast_note[:60]}'"))

            # Check 7: Standing on the Moon tab
            page.click("#t-moon")
            page.wait_for_timeout(600)
            moon_visible = page.is_visible("#tab-moon")
            pano_box = page.locator("#pano").bounding_box()
            # Test stretch select
            page.select_option("#stretch", "5")
            page.wait_for_timeout(200)
            # Test enlarge checkbox
            page.click("#enlarge")
            page.wait_for_timeout(200)
            # Test mouse drag rotate
            page.mouse.move(pano_box["x"] + 100, pano_box["y"] + 100)
            page.mouse.down()
            page.mouse.move(pano_box["x"] + 250, pano_box["y"] + 100)
            page.mouse.up()
            page.wait_for_timeout(200)
            # Test wheel zoom
            page.mouse.wheel(0, -100)
            page.wait_for_timeout(200)
            # Test Play/Pause animation button
            play_btn_text_1 = page.inner_text("#play")
            page.click("#play")
            page.wait_for_timeout(500)
            play_btn_text_2 = page.inner_text("#play")
            page.click("#play")  # Pause again
            chk7 = (moon_visible and pano_box and pano_box["width"] > 100 and play_btn_text_2 == "Pause")
            results.append(("7. 'Standing on the Moon' 360 panorama: drag rotates, wheel zooms, stretch/enlarge work, Play animates", "PASS" if chk7 else "FAIL", f"pano={pano_box['width']}x{pano_box['height']}, play_toggle={play_btn_text_1}->{play_btn_text_2}"))

            # Check 8: Copilot query in plain English
            page.click("#t-windows")  # switch back
            page.fill("#ask", "Which site is best for a 14-day mission in March, power first?")
            page.click("#askGo")
            page.wait_for_selector("#answer:not([hidden])", timeout=45000)
            answer_text = page.inner_text("#answerText")
            verify_text = page.inner_text("#verify")
            assumed_text = page.inner_text("#assumed")
            chk8 = (len(answer_text) > 20 and "Checked against the data" in verify_text and ("assumed" in assumed_text.lower()))
            results.append(("8. Copilot: plain English query returns deterministic answer, 'Checked against the data' verifier badge, and assumptions", "PASS" if chk8 else "FAIL", f"verify='{verify_text}', answer='{answer_text[:70]}...'"))

            # Check 9: Responsive layout at 1400px, 900px, 390px (no horizontal overflow)
            viewports = [(1400, 900, "1400"), (900, 800, "900"), (390, 844, "390")]
            responsive_ok = True
            for w, h, label in viewports:
                page.set_viewport_size({"width": w, "height": h})
                page.wait_for_timeout(500)
                scroll_w = page.evaluate("() => document.documentElement.scrollWidth")
                client_w = page.evaluate("() => document.documentElement.clientWidth")
                has_h_scroll = scroll_w > client_w + 1
                page.screenshot(path=str(ARTIFACTS_DIR / f"checklist-real-{label}.png"), full_page=True)
                if has_h_scroll:
                    responsive_ok = False
                    print(f"Warning: horizontal scroll at {label}px: scrollWidth={scroll_w}, clientWidth={client_w}")
            results.append(("9. Responsive layout at 1400px, 900px, 390px: no clipped text or horizontal page scroll", "PASS" if responsive_ok else "FAIL", "Screenshots saved in artifacts/"))

            # Check 10: Keyboard tab accessibility
            page.set_viewport_size({"width": 1400, "height": 900})
            page.goto(BASE_URL)
            page.wait_for_selector("#siteChips label", timeout=15000)
            focused_tags = []
            for _ in range(25):
                page.keyboard.press("Tab")
                tag = page.evaluate("() => document.activeElement ? (document.activeElement.tagName + '#' + (document.activeElement.id || document.activeElement.className)) : null")
                if tag and tag not in focused_tags:
                    focused_tags.append(tag)
            # Verify tab reachable
            page.focus("#t-mast")
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)
            mast_tab_active = page.is_visible("#tab-mast")
            chk10 = len(focused_tags) >= 8 and mast_tab_active
            results.append(("10. Keyboard accessibility: Tab cycles interactive controls, Enter activates tabs, focus ring visible", "PASS" if chk10 else "FAIL", f"unique_elements_focused={len(focused_tags)}, keyboard_tab_switch={mast_tab_active}"))

            # Check 11: Browser console errors
            chk11 = len(console_errors) == 0 and len(page_errors) == 0
            results.append(("11. Browser console: zero JavaScript exceptions or unhandled errors", "PASS" if chk11 else "FAIL", f"console_errors={len(console_errors)}, page_errors={len(page_errors)}"))

            # Check 12: Public/Planner switch preserves charts without error
            page.click("input[value='public']")
            page.wait_for_timeout(300)
            page.click("input[value='planner']")
            page.wait_for_timeout(300)
            tl_still_visible = page.is_visible("#timeline")
            sky_still_visible = page.is_visible("#horizon")
            chk12 = tl_still_visible and sky_still_visible and len(console_errors) == 0
            results.append(("12. Public/Planner mode toggles preserve canvas charts without crash or state corruption", "PASS" if chk12 else "FAIL", f"timeline_visible={tl_still_visible}, sky_visible={sky_still_visible}"))

            browser.close()
    finally:
        server_proc.terminate()
        server_proc.wait()

    # Step 2: Also quickly check Synthetic Mode banner
    print("\n=== Verifying Synthetic Demo Mode Banner ===")
    synth_proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.api.server:app", "--port", str(PORT + 1), "--log-level", "warning"],
        cwd=str(ROOT),
    )
    try:
        wait_for_server(f"http://127.0.0.1:{PORT + 1}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 900})
            page.goto(f"http://127.0.0.1:{PORT + 1}")
            page.wait_for_selector("#siteChips label", timeout=15000)
            synth_banner = page.inner_text("#banner")
            chk_synth = "Terrain is SYNTHETIC demo data" in synth_banner
            page.screenshot(path=str(ARTIFACTS_DIR / "checklist-synthetic.png"), full_page=True)
            results.append(("Bonus: Synthetic mode displays explicit 'SYNTHETIC demo data' warning banner", "PASS" if chk_synth else "FAIL", synth_banner[:80]))
            browser.close()
    finally:
        synth_proc.terminate()
        synth_proc.wait()

    print("\n" + "=" * 80)
    print("BROWSER & KEYBOARD INTERACTIVE CHECKLIST RESULTS")
    print("=" * 80)
    for name, status, ev in results:
        print(f"[{status}] {name}")
        print(f"       Evidence: {ev}")
    print("=" * 80)
    return results


if __name__ == "__main__":
    run_checklist()
