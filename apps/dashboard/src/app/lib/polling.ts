"use client";

import { useEffect, useRef } from "react";

/**
 * Run `task` on an interval, but only while the tab is actually on screen.
 *
 * A `setInterval` keeps firing in a background tab, so several signed-in windows
 * left open on the connector page were querying run history every 2.5 seconds
 * each, indefinitely, for a view nobody was looking at. Skipping the tick while
 * `document.hidden` costs nothing and stops that: the shell already refreshes
 * everything when a tab comes back to the foreground, so the first visible tick
 * is not the thing catching the user up.
 *
 * Pass `null` as the interval to poll not at all — that is how a caller says
 * "not yet" (no tenant, dialog closed) without breaking the rules of hooks.
 *
 * `task` is read through a ref, so a caller may pass a fresh closure on every
 * render without restarting the timer.
 */
export function usePolling(task: () => void, intervalMs: number | null): void {
  const latest = useRef(task);

  useEffect(() => {
    latest.current = task;
  });

  useEffect(() => {
    if (intervalMs === null) return;
    const timer = setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      latest.current();
    }, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
}
