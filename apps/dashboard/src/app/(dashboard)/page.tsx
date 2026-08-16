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
 * The two queries are gone with it, and so is the third: the story is a stored
 * report now, so opening this page reads one row. Aggregating a day of points on
 * every visit was the same mistake in a smaller frame — better than shipping a
 * thousand raw points to the browser, still work repeated for an answer that
 * cannot change until an import does.
 */
export default function OverviewPage() {
  const { apiBase } = useShell();
  return <DailyStory apiBase={apiBase} />;
}
