declare namespace NodeJS {
  interface ProcessEnv {
    readonly NEXT_PUBLIC_SITE_URL?: string;
    readonly NEXT_PUBLIC_API_URL?: string;
    readonly NEXT_PUBLIC_CDN_URL?: string;
    readonly API_INTERNAL_URL?: string;
  }
}
