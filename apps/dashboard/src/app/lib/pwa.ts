"use client";

import { useEffect, useState } from "react";

/**
 * Whether this is running as an installed app rather than in a browser tab.
 *
 * Most of what standalone mode changes is presentational and belongs in CSS —
 * `globals.css` declares a `standalone:` variant for exactly that. This hook is
 * for the rest: things a media query cannot reach, such as whether a link should
 * carry `target="_blank"`.
 *
 * That one matters more than it sounds. In a browser tab, opening the docs in a
 * new tab is the polite thing to do. In an installed app there are no tabs — the
 * link launches the *browser*, and the reader is thrown out of the app they
 * installed, with no obvious way back. Same markup, opposite outcome.
 *
 * Starts `false` and corrects after mount: `window.matchMedia` does not exist on
 * the server, and guessing would mean rendering one thing and then the other.
 */
export function useIsStandalone(): boolean {
  const [standalone, setStandalone] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(display-mode: standalone)");
    const update = () =>
      setStandalone(
        query.matches ||
          // iOS predates `display-mode` and still reports through this
          // non-standard property, which is why it is worth the cast.
          (window.navigator as Navigator & { standalone?: boolean }).standalone === true,
      );

    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return standalone;
}
