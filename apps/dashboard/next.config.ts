import type { NextConfig } from "next";

const parseAllowedOrigins = (): string[] => {
  // Only loopback is hardcoded. A deployment's own hostname arrives through
  // the environment variables read below -- baking one in meant the operator's
  // personal domain lived in the source of a repository meant to be published.
  const origins = new Set<string>(["localhost", "127.0.0.1"]);
  const envVars = [
    process.env.ALLOWED_DEV_ORIGINS,
    process.env.ALLOWED_ORIGINS,
    process.env.PUBLIC_BASE_URL,
    process.env.NEXT_PUBLIC_API_URL,
  ];

  for (const envVal of envVars) {
    if (!envVal) continue;
    for (const rawItem of envVal.split(",")) {
      let item = rawItem.trim();
      if (!item) continue;
      item = item
        .replace(/^https?:\/\//i, "")
        .split("/")[0]
        .split(":")[0];
      if (item) {
        origins.add(item);
      }
    }
  }

  return Array.from(origins);
};

const allowedOriginsList = parseAllowedOrigins();
const connectSrcDomains = allowedOriginsList
  .flatMap((domain) => [
    `https://${domain}`,
    `http://${domain}`,
    `wss://${domain}`,
    `ws://${domain}`,
  ])
  .join(" ");

/**
 * Raster tile hosts, allowed in `img-src` only.
 *
 * The map is vector-first and fetches nothing until the user explicitly loads it,
 * but when they do, the browser needs to be able to render the tiles. Previously
 * `img-src 'self' data: blob:` silently blocked every tile, so the map was a grey
 * box in any environment where these headers applied.
 *
 * Deliberately scoped to images: Leaflet itself is bundled, so no third-party
 * script origin is permitted. Set MAP_TILE_HOSTS to restrict or extend the list.
 */
const tileImageHosts = (
  process.env.MAP_TILE_HOSTS ?? "https://tile.openstreetmap.org https://*.basemaps.cartocdn.com"
).trim();

/**
 * The policy, with the development allowances kept out of the built one.
 *
 * Three things used to be permitted here that are not needed and are not free:
 *
 * * **`'unsafe-eval'`** is a `next dev` requirement — the dev overlay and Fast
 *   Refresh evaluate code at runtime. A production build does not, so shipping
 *   it granted the one capability an injected script most wants.
 * * **Bare `ws:` and `wss:`** match every host on the internet. The dashboard
 *   opens no WebSocket at all; what those two schemes actually permitted was an
 *   exfiltration channel to anywhere, which is the specific thing `connect-src`
 *   exists to close.
 * * **`fonts.googleapis.com` and `fonts.gstatic.com`** are never contacted:
 *   `next/font` downloads the faces at build time and serves them from this
 *   origin. The allowance described an architecture this app moved away from.
 *
 * **`'unsafe-inline'` in `script-src` stays, and is the honest remaining gap.**
 * Next inlines its bootstrap and flight data, so removing it needs a nonce
 * threaded from middleware through the document — a real change with a real
 * risk of a blank page, and one worth doing on its own rather than folded in
 * here. Everything above was removable without touching how the app renders.
 *
 * Note that `'unsafe-inline'` in **`style-src`** is a different matter and stays
 * on its own merits: Tailwind and the chart components set inline styles, and
 * style injection is not script execution.
 */
function contentSecurityPolicy(): string {
  const isDev = process.env.NODE_ENV === "development";

  const scriptSrc = ["'self'", "'unsafe-inline'", isDev && "'unsafe-eval'"]
    .filter(Boolean)
    .join(" ");

  // Loopback belongs to a developer running the Gateway on their own machine.
  // In a build it is dead weight in a security header.
  const devConnect = isDev
    ? " http://127.0.0.1:8000 http://localhost:8000 http://localhost:* http://127.0.0.1:* ws: wss:"
    : "";

  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self'",
    `connect-src 'self' ${connectSrcDomains}${devConnect}`,
    `img-src 'self' data: blob: ${tileImageHosts}`,
    // Nothing in this application is framed, and nothing frames it. Stated
    // rather than left to X-Frame-Options alone, which CSP supersedes.
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
}

const nextConfig: NextConfig = {
  // What the published container runs. Next traces the modules the server
  // actually reaches and writes a self-contained bundle to `.next/standalone`:
  // 20 MB, `sharp` included, against 522 MB of installed node_modules. The image
  // used to ship the latter, and pruning it by hand is a losing game -- both libc
  // variants of the SWC binary arrive because a lockfile cannot know which one the
  // base image needs, and `@playwright/test` survives `--production` because Next
  // declares it as an optional peer, so it is a peer of a production dependency.
  //
  // Additive: `next start` keeps working against `.next` exactly as before, which
  // is what the browser tests in CI use.
  output: "standalone",
  allowedDevOrigins: allowedOriginsList,
  /**
   * `next dev` only: route this origin's `/api/*` to the Gateway.
   *
   * The UI has no configured API origin in development, so `getApiBase()` falls
   * back to `window.location.origin` — which is correct in production, where
   * Traefik owns the origin and routes `/api` to the Gateway, and was nothing at
   * all in development, where the origin is the dev server. Every call answered
   * 404 from Next: `/api/v1/auth/config`, `/api/v1/auth/me`, the OIDC provider
   * list. The login screen could not even find out whether sign-up was open.
   *
   * A rewrite rather than pointing the UI at `http://127.0.0.1:8000` with
   * NEXT_PUBLIC_API_URL, because that swaps the production code path for a
   * different one: an absolute cross-origin base needs CORS, and cookies set by
   * `127.0.0.1` are not sent from a page on `localhost` — SameSite treats them
   * as different sites. Same-origin here means development exercises what
   * production does.
   *
   * Never in a build: `next build` sets NODE_ENV=production, so the published
   * image contains no proxy and Traefik keeps doing this job.
   */
  rewrites: async () => {
    if (process.env.NODE_ENV !== "development") return [];
    const gateway = process.env.DEV_GATEWAY_URL ?? "http://127.0.0.1:8000";
    return [{ source: "/api/:path*", destination: `${gateway}/api/:path*` }];
  },
  // The legal texts moved to /legal/*. Keep the old path working for bookmarks and
  // any link already published.
  redirects: async () => [
    { source: "/privacy", destination: "/legal/datenschutz", permanent: true },
    { source: "/datenschutz", destination: "/legal/datenschutz", permanent: true },
    { source: "/impressum", destination: "/legal/impressum", permanent: true },
  ],
  // SECURITY L3: Add security headers
  headers: async () => [
    {
      source: "/(.*)",
      headers: [
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        {
          key: "Content-Security-Policy",
          value: contentSecurityPolicy(),
        },
      ],
    },
  ],
};

export default nextConfig;
