import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["192.168.1.100"],
  experimental: {
    proxyClientMaxBodySize: "10mb"
  }
};

export default nextConfig;
