import type { NextConfig } from "next";

const parseAllowedOrigins = (): string[] => {
  const origins = new Set<string>(["localhost", "127.0.0.1", "quantified-self.example.com"]);
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

const nextConfig: NextConfig = {
  allowedDevOrigins: allowedOriginsList,
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
            "img-src 'self' data: blob:",
          ].join("; "),
        },
      ],
    },
  ],
};

export default nextConfig;
