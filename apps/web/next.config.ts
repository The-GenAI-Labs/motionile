import { fileURLToPath } from "node:url";

import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD } from "next/constants";

import { readPublicEnv } from "./src/config/env-schema";
import { buildSecurityHeaders } from "./src/config/security-headers";

const PHASES_REQUIRING_ENV = new Set([PHASE_DEVELOPMENT_SERVER, PHASE_PRODUCTION_BUILD]);

const createSecurityHeaders = (phase: string) => {
  const publicEnv = readPublicEnv();
  return buildSecurityHeaders({
    isDevelopment: phase === PHASE_DEVELOPMENT_SERVER,
    siteUrl: publicEnv.NEXT_PUBLIC_SITE_URL,
    apiUrl: publicEnv.NEXT_PUBLIC_API_URL,
    cdnUrl: publicEnv.NEXT_PUBLIC_CDN_URL,
  });
};

const buildNextConfig = (phase: string): NextConfig => ({
  output: "standalone",
  reactCompiler: true,
  poweredByHeader: false,
  reactStrictMode: true,
  typedRoutes: true,
  experimental: {
    authInterrupts: true,
  },
  outputFileTracingRoot: fileURLToPath(new URL("../../", import.meta.url)),
  headers() {
    return Promise.resolve([{ source: "/:path*", headers: createSecurityHeaders(phase) }]);
  },
});

export default function createNextConfig(phase: string): NextConfig {
  if (PHASES_REQUIRING_ENV.has(phase)) {
    readPublicEnv();
  }
  return buildNextConfig(phase);
}
