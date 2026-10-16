import { z } from "zod";

export const DEFAULT_API_URL = "http://localhost:8000";

const stripTrailingSlashes = (value: string): string => value.replace(/\/+$/, "");

const emptyToUndefined = (value: unknown): unknown => (value === "" ? undefined : value);

export const httpUrlSchema = z.url({ protocol: /^https?$/ }).transform(stripTrailingSlashes);

export const publicEnvSchema = z.object({
  NEXT_PUBLIC_SITE_URL: httpUrlSchema,
  NEXT_PUBLIC_API_URL: z.preprocess(emptyToUndefined, httpUrlSchema.default(DEFAULT_API_URL)),
  NEXT_PUBLIC_TURNSTILE_SITE_KEY: z.preprocess(emptyToUndefined, z.string().min(1).optional()),
  NEXT_PUBLIC_JWKS_URL: z.preprocess(emptyToUndefined, httpUrlSchema.optional()),
  NEXT_PUBLIC_CDN_URL: z.preprocess(emptyToUndefined, httpUrlSchema.optional()),
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
