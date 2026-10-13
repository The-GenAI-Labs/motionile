import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";

import { readPublicEnv } from "./src/config/env-schema";

const PHASES_REQUIRING_ENV = new Set([PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD]);

const securityHeaders = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactCompiler: true,
  poweredByHeader: false,
  reactStrictMode: true,
  typedRoutes: true,
  outputFileTracingRoot: fileURLToPath(new URL("../../", import.meta.url)),
  headers() {
    return Promise.resolve([{ source: "/:path*", headers: securityHeaders }]);
  },
};

export default function createNextConfig(phase: string): NextConfig {
  if (PHASES_REQUIRING_ENV.has(phase)) {
    readPublicEnv();
  }
  return nextConfig;
}
