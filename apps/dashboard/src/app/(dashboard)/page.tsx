"use client";

import DailyStory from "../components/DailyStory";
import { useShell } from "./shell";

/**
 * The landing page: today's story, not a grid of lifetime averages.
 *
 * What stood here fetched a whole-history metric summary and a thousand recent
 * points, then drew nine cards of "average, min, max over all data you have ever
 * had". Every number was true and none of them answered the question somebody
 * opens this page with, which is what happened — last night, yesterday, and how
 * much of today has arrived.
 *
 * The two queries are gone with it. A single `/api/v1/data/day` call per day
 * replaces them, bounded to that day and aggregated server-side, so the page no
 * longer transfers a thousand raw points to bucket them in the browser.
 */
export default function OverviewPage() {
  const { apiBase, refreshTrigger, onUnauthorized } = useShell();
  return (
    <DailyStory
      apiBase={apiBase}
      refreshTrigger={refreshTrigger}
      onUnauthorized={onUnauthorized}
    />
  );
}
