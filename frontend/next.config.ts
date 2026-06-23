import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    unoptimized: true,
  },
  // Disable API rewrites in production (handled by Netlify)
  // Keep them for local development
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001"}/api/:path*`,
      },
    ];
  },
  // Ensure trailing slash handling
  trailingSlash: false,
};

export default nextConfig;
