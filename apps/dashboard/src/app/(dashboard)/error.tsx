"use client";

import CrashScreen from "../components/CrashScreen";

/**
 * The boundary around every dashboard screen.
 *
 * Deliberately inside the `(dashboard)` group rather than at the app root: this
 * layout renders the sidebar, the tab bar and the session, and Next keeps a layout
 * mounted when the boundary *below* it catches. So a screen that throws costs that
 * screen and nothing else — the navigation is still there, and the reader can walk
 * to a working tab instead of being handed a dead page.
 */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <CrashScreen error={error} reset={reset} />;
}
