import type { MetadataRoute } from "next";

import { requestLocale } from "./lib/i18n/request";
import { translate } from "./lib/i18n/translate";

/**
 * What the browser needs before it will offer to install this.
 *
 * There was no manifest at all, which meant the dashboard could never be an
 * installed app on any platform — the "add to home screen" affordance is gated
 * on this file existing and naming icons.
 *
 * `display: "standalone"` rather than `fullscreen`: this is a reading tool whose
 * pages scroll, and taking the status bar away buys nothing while costing the
 * clock and the battery indicator.
 *
 * `background_color` is the light `--background` and `theme_color` matches it.
 * The manifest takes exactly one value for each, so it cannot follow the theme —
 * the per-scheme `themeColor` in the root layout's `viewport` export is what
 * handles the running app's chrome. This pair only paints the splash screen
 * during launch, before any CSS has been read.
 */
export default async function manifest(): Promise<MetadataRoute.Manifest> {
  const locale = await requestLocale();

  return {
    name: "Quantified Self Platform",
    short_name: "Quantified",
    description: translate(locale, "auth.tagline"),
    lang: locale,
    start_url: "/",
    // Everything under the origin, so the docs container Traefik serves at /docs
    // opens inside the installed app rather than kicking the reader out to a
    // browser — see the `standalone:` handling of that link.
    scope: "/",
    display: "standalone",
    orientation: "portrait-primary",
    background_color: "#f8fafc",
    theme_color: "#f8fafc",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/icon-maskable-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
