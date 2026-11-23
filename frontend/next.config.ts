import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Only output standalone when building for Docker (via BUILD_STANDALONE=true)
  // so standard local execution (`next start` / `npm run start`) runs seamlessly.
  ...(process.env.BUILD_STANDALONE === "true" ? { output: "standalone" } : {}),

  outputFileTracingRoot: path.resolve(__dirname),

  turbopack: {
    root: path.resolve(__dirname),
  },

  // Experimental package optimizations for faster builds & rendering
  experimental: {
    optimizePackageImports: ["lucide-react", "date-fns", "chart.js"],
  },

  // Headers for WASM and SharedArrayBuffer (credentialless prevents blocking external iframes/media)
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Embedder-Policy", value: "credentialless" },
        ],
      },
    ];
  },

  // Allow external image sources (Supabase Storage)
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**.supabase.co",
      },
    ],
  },

  // Webpack: handle worker imports
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        fs: false,
        path: false,
      };
    }
    return config;
  },
};

export default nextConfig;
