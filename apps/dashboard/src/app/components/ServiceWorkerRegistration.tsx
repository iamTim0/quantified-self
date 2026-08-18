"use client";

import { useEffect } from "react";

/**
 * Registers `public/sw.js`, and only where it can do no harm.
 *
 * Production only. A service worker in development serves the previous build's
 * assets from cache and turns "my change did not appear" into a half-hour of
 * confusion; `next dev` already has its own reload machinery.
 *
 * Renders nothing. The worker's own file documents what it deliberately refuses
 * to cache and why — in short, no API response and no rendered page ever.
 */
export default function ServiceWorkerRegistration() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;

    // After `load`, so registration never competes with the first paint for
    // bandwidth on the visit that matters most.
    const register = () => {
      navigator.serviceWorker.register("/sw.js").catch((error) => {
        // A failed registration costs the install prompt and the offline page,
        // nothing else — so it is reported and not escalated.
        console.error("Service worker registration failed:", error);
      });
    };

    if (document.readyState === "complete") {
      register();
      return;
    }
    window.addEventListener("load", register);
    return () => window.removeEventListener("load", register);
  }, []);

  return null;
}
