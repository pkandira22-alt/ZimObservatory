/**
 * Formats raw feed results into telemetry shape with explicit status values.
 * Maps feed connections to: offline (error/null), empty (no items), or online (has items).
 */
export function formatFeedTelemetry(rawFeeds) {
  return rawFeeds.map((f) => {
    if (f.error || f.items === null || f.items === undefined) {
      return {
        platform: f.platform,
        count: 0,
        status: "offline",
        reason: f.error || "Feed disconnected or rate-limited",
      };
    }
    return {
      platform: f.platform,
      count: f.items.length,
      status: f.items.length > 0 ? "online" : "empty",
      reason: f.items.length === 0 ? "No matching posts in window" : null,
    };
  });
}

/**
 * Filters feed telemetry to exclude offline feeds from rendering.
 * Returns only feeds with status "online" or "empty" (connected but no content).
 */
export function filterExcludedFeeds(feedTelemetry) {
  return feedTelemetry.filter((feed) => feed.status !== "offline");
}

/**
 * Marks feed status as excluded in HTML rendering context.
 * Sets CSS display class and aria-disabled for offline feeds.
 */
export function markOfflineFeedsExcluded(feedElements) {
  feedElements.forEach((el) => {
    const status = el.dataset?.feedStatus || el.getAttribute("data-feed-status");
    if (status === "offline") {
      el.classList.add("feed-excluded", "feed-offline");
      el.setAttribute("aria-disabled", "true");
      const reasonEl = el.querySelector("[data-feed-reason]");
      if (reasonEl) {
        reasonEl.textContent = `Excluded: ${reasonEl.textContent || "Feed offline"}`;
      }
    }
  });
}
