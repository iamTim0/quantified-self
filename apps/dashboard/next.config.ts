import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
            "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000 http://localhost:* http://127.0.0.1:* ws: wss:",
            "img-src 'self' data: blob:",
          ].join("; "),
        },
      ],
    },
  ],
};

export default nextConfig;
