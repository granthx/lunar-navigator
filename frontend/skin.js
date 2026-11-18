/* ================================================================
   frontend/skin.js — Decorative Flight-Operations Presentation Layer
   ================================================================
   Passive presenter: read-only DOM inspection of #winList to project
   optimal mission telemetry into the hero KPI strip (#heroKpi).
   - Zero network requests.
   - Zero state mutation or interference with app.js / lib.js.
   - Writes exclusively into #heroKpi.
   ================================================================ */
(function () {
  "use strict";

  function getTarget() {
    return document.getElementById("heroKpi");
  }

  function renderStandby(kpi) {
    kpi.innerHTML =
      '<div class="kpi-panel standby">' +
        '<div class="kpi-station">' +
          '<span class="kpi-tag"><span class="kpi-live-dot pulse"></span>FLIGHT TELEMETRY STATUS</span>' +
          '<span class="kpi-val-text">AWAITING MISSION CALCULATION & CANDIDATE REGION RANKING</span>' +
        '</div>' +
      '</div>';
  }

  function updateKpi() {
    const kpi = getTarget();
    if (!kpi) return;

    const selectedRow = document.querySelector("#winList tbody tr.sel");
    const activeRow = selectedRow || document.querySelector("#winList tbody tr");
    if (!activeRow) {
      renderStandby(kpi);
      return;
    }

    const cells = activeRow.children;
    if (!cells || cells.length < 4) {
      renderStandby(kpi);
      return;
    }

    const siteName = cells[0].textContent.trim();
    const isPlanner = cells.length >= 8;
    const stationLabel = selectedRow ? "SELECTED WINDOW" : "OPTIMAL REGION (RANK #1)";

    // Read provenance dynamically from existing #banner without hardcoding
    const bannerFirst = document.querySelector("#banner p");
    let provTag = "";
    if (bannerFirst) {
      const bText = bannerFirst.textContent.trim();
      if (bText.includes("SYNTHETIC")) {
        provTag = " • DEMO TERRAIN";
      } else if (bText.includes("representative points")) {
        provTag = " • CANDIDATE REGION";
      }
    }

    let dateRange = "";
    let pwr = "--";
    let com = "--";
    let both = "--";

    if (isPlanner) {
      const dStart = (cells[1].textContent.trim().split(" ")[0] || "").slice(5);
      const dEnd = (cells[2].textContent.trim().split(" ")[0] || "").slice(5);
      dateRange = dStart + " → " + dEnd;
      pwr = cells[3].textContent.trim();
      com = cells[4].textContent.trim();
      both = cells[5].textContent.trim();
    } else {
      dateRange = cells[1].textContent.trim();
      both = cells[2].textContent.trim();
    }

    const chipEl = activeRow.querySelector(".chip");
    const chipText = chipEl ? chipEl.textContent.trim() : "ACTIVE";
    const chipClass = chipEl ? chipEl.className : "chip robust";

    kpi.innerHTML =
      '<div class="kpi-panel">' +
        '<div class="kpi-station kpi-target">' +
          '<div class="kpi-label"><span class="kpi-live-dot"></span>' + escapeHtml(stationLabel) + '</div>' +
          '<div class="kpi-val-headline">' + escapeHtml(siteName) + '</div>' +
          '<div class="kpi-sub">' + escapeHtml(dateRange + provTag) + '</div>' +
        '</div>' +
        '<div class="kpi-station">' +
          '<div class="kpi-label">SOLAR POWER</div>' +
          '<div class="kpi-num pwr">' + escapeHtml(pwr) + '</div>' +
          '<div class="kpi-sub">PHOTOVOLTAIC</div>' +
        '</div>' +
        '<div class="kpi-station">' +
          '<div class="kpi-label">DTE LINK</div>' +
          '<div class="kpi-num com">' + escapeHtml(com) + '</div>' +
          '<div class="kpi-sub">COMMUNICATION</div>' +
        '</div>' +
        '<div class="kpi-station kpi-highlight">' +
          '<div class="kpi-label">DUAL CONSTRAINT</div>' +
          '<div class="kpi-num both">' + escapeHtml(both) + '</div>' +
          '<div class="kpi-sub">POWER + COMMS</div>' +
        '</div>' +
        '<div class="kpi-station kpi-status-station">' +
          '<div class="kpi-label">CONFIDENCE</div>' +
          '<div class="kpi-badge-wrap"><span class="' + escapeHtml(chipClass) + '">' + escapeHtml(chipText) + '</span></div>' +
          '<div class="kpi-sub">TERRAIN MC EVAL</div>' +
        '</div>' +
      '</div>';
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function init() {
    const kpi = getTarget();
    if (!kpi) return;

    updateKpi();

    const winList = document.getElementById("winList");
    if (winList && typeof MutationObserver !== "undefined") {
      const observer = new MutationObserver(function () {
        updateKpi();
      });
      observer.observe(winList, { childList: true, subtree: true });
    }

    const modeRadios = document.querySelectorAll("input[name=mode]");
    for (let i = 0; i < modeRadios.length; i++) {
      modeRadios[i].addEventListener("change", function () {
        setTimeout(updateKpi, 50);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

