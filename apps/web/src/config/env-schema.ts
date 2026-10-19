import { z } from "zod";

export const DEFAULT_API_URL = "http://localhost:8000";

export const PROVIDERS_MODES = ["fake", "live"] as const;

export type ProvidersMode = (typeof PROVIDERS_MODES)[number];

const LOOPBACK_HOSTNAMES = new Set(["localhost", "127.0.0.1", "[::1]"]);

const stripTrailingSlashes = (value: string): string => value.replace(/\/+$/, "");

const emptyToUndefined = (value: unknown): unknown => (value === "" ? undefined : value);

export const httpUrlSchema = z.url({ protocol: /^https?$/ }).transform(stripTrailingSlashes);

export const isLoopbackUrl = (url: string): boolean => {
  if (!URL.canParse(url)) {
    return false;
  }
  const hostname = new URL(url).hostname;
  return LOOPBACK_HOSTNAMES.has(hostname) || hostname.endsWith(".localhost");
};

export const publicEnvSchema = z
  .object({
    NEXT_PUBLIC_SITE_URL: httpUrlSchema,
    NEXT_PUBLIC_API_URL: z.preprocess(emptyToUndefined, httpUrlSchema.default(DEFAULT_API_URL)),
    NEXT_PUBLIC_TURNSTILE_SITE_KEY: z.preprocess(emptyToUndefined, z.string().min(1).optional()),
    NEXT_PUBLIC_JWKS_URL: z.preprocess(emptyToUndefined, httpUrlSchema.optional()),
    NEXT_PUBLIC_CDN_URL: z.preprocess(emptyToUndefined, httpUrlSchema.optional()),
    NEXT_PUBLIC_PROVIDERS_MODE: z.preprocess(
      emptyToUndefined,
      z.enum(PROVIDERS_MODES).default("live"),
    ),
  })
  .check((context) => {
    const { NEXT_PUBLIC_SITE_URL: siteUrl, NEXT_PUBLIC_PROVIDERS_MODE: mode } = context.value;
    if (mode === "fake" && !isLoopbackUrl(siteUrl)) {
      context.issues.push({
        code: "custom",
        message: "fake providers are only allowed when NEXT_PUBLIC_SITE_URL is a local address",
        path: ["NEXT_PUBLIC_PROVIDERS_MODE"],
        input: mode,
      });
    }
  });

export type PublicEnv = z.infer<typeof publicEnvSchema>;

export const parsePublicEnv = (source: Record<string, string | undefined>): PublicEnv => {
  const result = publicEnvSchema.safeParse(source);
  if (!result.success) {
    throw new Error(`Invalid public environment variables:\n${z.prettifyError(result.error)}`);
  }
  return result.data;
};

export const readPublicEnv = (): PublicEnv =>
  parsePublicEnv({
    NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_CDN_URL: process.env.NEXT_PUBLIC_CDN_URL,
    NEXT_PUBLIC_TURNSTILE_SITE_KEY: process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
    NEXT_PUBLIC_JWKS_URL: process.env.NEXT_PUBLIC_JWKS_URL,
    NEXT_PUBLIC_PROVIDERS_MODE: process.env.NEXT_PUBLIC_PROVIDERS_MODE,
  });

export const serverEnvSchema = z.object({
  API_INTERNAL_URL: z.preprocess(emptyToUndefined, httpUrlSchema.optional()),
  CATALOG_REVALIDATION_SECRET: z.preprocess(emptyToUndefined, z.string().min(32).optional()),
});

export interface ServerEnv {
  apiBaseUrl: string;
  catalogRevalidationSecret?: string;
}

export const parseServerEnv = (
  source: Record<string, string | undefined>,
  publicEnv: PublicEnv,
): ServerEnv => {
  const result = serverEnvSchema.safeParse(source);
  if (!result.success) {
    throw new Error(`Invalid server environment variables:\n${z.prettifyError(result.error)}`);
  }
  return {
    apiBaseUrl: result.data.API_INTERNAL_URL ?? publicEnv.NEXT_PUBLIC_API_URL,
    ...(result.data.CATALOG_REVALIDATION_SECRET === undefined
      ? {}
      : { catalogRevalidationSecret: result.data.CATALOG_REVALIDATION_SECRET }),
  };
};
