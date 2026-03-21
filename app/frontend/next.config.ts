import type { NextConfig } from "next";

const apiBase = process.env.API_BASE_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",

  // Prevent stale chunk caching — unique build ID per deploy
  generateBuildId: async () => {
    return `build-${Date.now()}`;
  },

  // Disable powered-by header
  poweredByHeader: false,


  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiBase}/api/:path*`,
      },
      {
        source: "/files/:path*",
        destination: `${apiBase}/files/:path*`,
      },
      {
        source: "/ws",
        destination: `${apiBase}/ws`,
      },
    ];
  },

  async headers() {
    return [
      {
        // Hashed static assets — safe to cache forever
        source: "/_next/static/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
      {
        // HTML pages — NEVER cache (critical for iOS PWA)
        source: "/:path*",
        headers: [
          {
            key: "Cache-Control",
            value: "no-cache, no-store, must-revalidate",
          },
          {
            key: "Pragma",
            value: "no-cache",
          },
          {
            key: "Expires",
            value: "0",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
