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
      item = item.replace(/^https?:\/\//i, "").split("/")[0].split(":")[0];
      if (item) {
        origins.add(item);
      }
    }
  }

  return Array.from(origins);
};

const allowedOriginsList = parseAllowedOrigins();
const connectSrcDomains = allowedOriginsList
  .flatMap((domain) => [`https://${domain}`, `http://${domain}`, `wss://${domain}`, `ws://${domain}`])
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
  process.env.MAP_TILE_HOSTS ??
  "https://tile.openstreetmap.org https://*.basemaps.cartocdn.com"
).trim();

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
          value: [
            "default-src 'self'",
            "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            `connect-src 'self' ${connectSrcDomains} http://127.0.0.1:8000 http://localhost:8000 http://localhost:* http://127.0.0.1:* ws: wss:`,
            `img-src 'self' data: blob: ${tileImageHosts}`,
          ].join("; "),
        },
      ],
    },
  ],
};

export default nextConfig;
