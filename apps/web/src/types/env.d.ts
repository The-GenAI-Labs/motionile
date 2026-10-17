declare namespace NodeJS {
  interface ProcessEnv {
    readonly NEXT_PUBLIC_SITE_URL?: string;
    readonly NEXT_PUBLIC_API_URL?: string;
    readonly NEXT_PUBLIC_CDN_URL?: string;
    readonly NEXT_PUBLIC_TURNSTILE_SITE_KEY?: string;
    readonly NEXT_PUBLIC_JWKS_URL?: string;
    readonly AUTH_JWT_ISSUER?: string;
    readonly AUTH_JWT_AUDIENCE?: string;
    readonly CATALOG_REVALIDATION_SECRET?: string;
    readonly API_INTERNAL_URL?: string;
  }
}
