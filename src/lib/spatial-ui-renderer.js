/**
 * Spatial pin UI rendering utilities.
 *
 * Maintains explicit separation between:
 *   - Site-level extraction status (reported quantities or gaps)
 *   - Empirical survey baselines (ZimLAC/FNC provincial surveys)
 *   - Source attribution with clickable links
 */

/**
 * Render a spatial pin card with explicit separation of data boundaries.
 *
 * @param {Object} pin - Formatted pin from spatial_pin_formatter.py
 *   - pin.epistemic_badge: Classification badge (Measured/Proxy)
 *   - pin.location_name: Display location name
 *   - pin.period: Data collection period
 *   - pin.site_extraction_status: Reported quantity or "No numeric extraction..."
 *   - pin.survey_baseline: Survey context (ZimLAC/FNC baseline)
 *   - pin.source_title: Data source name
 *   - pin.source_url: Source URL
 * @param {string} containerId - HTML element ID for the card container
 * @returns {boolean} true if rendered successfully, false if container not found
 */
export function renderSelectedSpatialCard(pin, containerId = "spatial-selected-details") {
  const container = document.getElementById(containerId);
  if (!container || !pin) {
    return false;
  }

  const period = pin.period || "2025–2026";
  const extractionStatus = pin.site_extraction_status || "Data unavailable";
  const surveyBaseline = pin.survey_baseline || "Survey baseline not specified";
  const sourceTitle = pin.source_title || "Unknown Source";
  const sourceUrl = pin.source_url || "#";
  const badge = pin.epistemic_badge || "[Data Classification Unknown]";

  container.innerHTML = `
    <div class="spatial-badge">${badge}</div>
    <h4>${pin.location_name} (${period})</h4>
    <div class="spatial-fields">
      <div class="field">
        <strong>Site-Level Extraction:</strong>
        <span class="extraction-status">${extractionStatus}</span>
      </div>
      <div class="field">
        <strong>Empirical Survey Baseline:</strong>
        <span class="survey-baseline">${surveyBaseline}</span>
      </div>
      <div class="field source-field">
        <strong>Source:</strong>
        <a href="${sourceUrl}" target="_blank" rel="noopener" class="source-link">${sourceTitle}</a>
      </div>
    </div>
  `;

  return true;
}

/**
 * Render a collection of spatial pins as collapsible cards.
 *
 * @param {Array} pins - Array of formatted pin objects
 * @param {string} containerId - HTML element ID for the pins container
 * @param {Object} options - Rendering options
 *   - options.groupByLineage: boolean (default: true) - Group by Measured/Proxy
 *   - options.maxPinsVisible: number (default: 10) - Max pins to show initially
 * @returns {number} Number of pins rendered
 */
export function renderSpatialPinsGrid(pins, containerId = "spatial-pins-grid", options = {}) {
  const container = document.getElementById(containerId);
  if (!container || !Array.isArray(pins) || pins.length === 0) {
    return 0;
  }

  const { groupByLineage = true, maxPinsVisible = 10 } = options;

  // Group pins by lineage if requested
  let pinGroups = [{ label: "All Pins", pins }];
  if (groupByLineage) {
    const measured = pins.filter(p => p.lineage === "Measured Directly");
    const proxy = pins.filter(p => p.lineage !== "Measured Directly");
    pinGroups = [
      measured.length > 0 && { label: "Measured Directly", pins: measured },
      proxy.length > 0 && { label: "Proxy / Estimate", pins: proxy },
    ].filter(Boolean);
  }

  container.innerHTML = "";
  let totalRendered = 0;

  for (const group of pinGroups) {
    // Create group section
    const groupEl = document.createElement("div");
    groupEl.className = "spatial-pin-group";
    groupEl.setAttribute("data-lineage", group.label);

    // Group header
    const headerEl = document.createElement("div");
    headerEl.className = "group-header";
    headerEl.innerHTML = `
      <h5>${group.label}</h5>
      <span class="count">${group.pins.length}</span>
    `;
    groupEl.appendChild(headerEl);

    // Pins in group
    const pinsEl = document.createElement("div");
    pinsEl.className = "spatial-pins-list";

    const visiblePins = group.pins.slice(0, maxPinsVisible);
    for (const pin of visiblePins) {
      const pinCardEl = document.createElement("div");
      pinCardEl.className = "spatial-pin-card";
      pinCardEl.setAttribute("data-id", pin.id);
      pinCardEl.setAttribute("data-lineage", pin.lineage);

      const statusClass = pin.site_extraction_status.includes("No numeric")
        ? "status-missing"
        : "status-available";

      pinCardEl.innerHTML = `
        <div class="pin-header">
          <span class="badge">${pin.epistemic_badge}</span>
        </div>
        <div class="pin-content">
          <h6>${pin.location_name}</h6>
          <div class="pin-status ${statusClass}">
            ${pin.site_extraction_status}
          </div>
          <div class="pin-period">${pin.period || "2025–2026"}</div>
        </div>
      `;

      pinCardEl.addEventListener("click", () => {
        renderSelectedSpatialCard(pin, "spatial-selected-details");
        // Highlight selected card
        document.querySelectorAll(".spatial-pin-card").forEach(el => {
          el.classList.remove("selected");
        });
        pinCardEl.classList.add("selected");
      });

      pinsEl.appendChild(pinCardEl);
      totalRendered++;
    }

    // Show "more" indicator if truncated
    if (group.pins.length > maxPinsVisible) {
      const moreEl = document.createElement("div");
      moreEl.className = "pins-more";
      moreEl.textContent = `+${group.pins.length - maxPinsVisible} more pins`;
      pinsEl.appendChild(moreEl);
    }

    groupEl.appendChild(pinsEl);
    container.appendChild(groupEl);
  }

  return totalRendered;
}

/**
 * Update spatial card with new pin data.
 *
 * @param {Object} pin - Spatial pin object
 * @param {string} containerId - Container element ID
 * @returns {boolean} Success status
 */
export function updateSpatialCard(pin, containerId = "spatial-selected-details") {
  return renderSelectedSpatialCard(pin, containerId);
}

/**
 * Clear spatial card rendering.
 *
 * @param {string} containerId - Container element ID
 */
export function clearSpatialCard(containerId = "spatial-selected-details") {
  const container = document.getElementById(containerId);
  if (container) {
    container.innerHTML = "";
  }
}

/**
 * Export spatial pin data as JSON.
 *
 * @param {Object} pin - Spatial pin object
 * @returns {string} JSON representation
 */
export function exportSpatialPinJSON(pin) {
  return JSON.stringify(pin, null, 2);
}

/**
 * Export spatial pins collection as CSV.
 *
 * @param {Array} pins - Array of spatial pins
 * @returns {string} CSV format
 */
export function exportSpatialPinsCSV(pins) {
  if (!Array.isArray(pins) || pins.length === 0) {
    return "";
  }

  const headers = ["id", "location_name", "lineage", "site_extraction_status", "period", "source_title"];
  const rows = pins.map(pin =>
    headers.map(h => {
      const val = pin[h] || "";
      // Escape CSV: wrap in quotes if contains comma or quote
      return typeof val === "string" && (val.includes(",") || val.includes('"'))
        ? `"${val.replace(/"/g, '""')}"`
        : val;
    }).join(",")
  );

  return [headers.join(","), ...rows].join("\n");
}
