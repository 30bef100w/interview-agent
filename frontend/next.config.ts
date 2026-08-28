import type { NextConfig } from "next";

const backendProxy =
  process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendProxy}/api/:path*` }];
  },
};

export default nextConfig;
