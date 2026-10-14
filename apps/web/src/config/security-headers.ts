export const TURNSTILE_ORIGIN = "https://challenges.cloudflare.com";
export const RAZORPAY_CHECKOUT_ORIGIN = "https://checkout.razorpay.com";
export const RAZORPAY_API_ORIGIN = "https://api.razorpay.com";

export interface SecurityHeaderOptions {
  isDevelopment: boolean;
  siteUrl: string;
  apiUrl: string;
  cdnUrl?: string | undefined;
}

export interface SecurityHeader {
  key: string;
  value: string;
}

type CspDirectives = Record<string, readonly string[]>;

const originOf = (url: string): string => new URL(url).origin;

const unique = (values: readonly string[]): string[] => [...new Set(values)];

const optionalOrigin = (url: string | undefined): string[] => (url ? [originOf(url)] : []);

const shouldUpgradeInsecureRequests = (options: SecurityHeaderOptions): boolean =>
  !options.isDevelopment && new URL(options.siteUrl).protocol === "https:";

export const buildCspDirectives = (options: SecurityHeaderOptions): CspDirectives => {
  const cdnOrigins = optionalOrigin(options.cdnUrl);
  const developmentScriptSources = options.isDevelopment ? ["'unsafe-eval'"] : [];
  const directives: CspDirectives = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      "'unsafe-inline'",
      ...developmentScriptSources,
      TURNSTILE_ORIGIN,
      RAZORPAY_CHECKOUT_ORIGIN,
    ],
    "style-src": ["'self'", "'unsafe-inline'"],
    "img-src": ["'self'", "data:", ...cdnOrigins],
    "media-src": ["'self'", ...cdnOrigins],
    "font-src": ["'self'"],
    "connect-src": unique(["'self'", originOf(options.apiUrl), RAZORPAY_API_ORIGIN]),
    "frame-src": [TURNSTILE_ORIGIN, RAZORPAY_API_ORIGIN, RAZORPAY_CHECKOUT_ORIGIN],
    "frame-ancestors": ["'none'"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
  };
  if (shouldUpgradeInsecureRequests(options)) {
    return { ...directives, "upgrade-insecure-requests": [] };
  }
  return directives;
};

export const serializeCsp = (directives: CspDirectives): string =>
  Object.entries(directives)
    .map(([name, sources]) => [name, ...sources].join(" "))
    .join("; ");

export const buildContentSecurityPolicy = (options: SecurityHeaderOptions): string =>
  serializeCsp(buildCspDirectives(options));

export const PERMISSIONS_POLICY = [
  "accelerometer=()",
  "camera=()",
  "geolocation=()",
  "gyroscope=()",
  "magnetometer=()",
  "microphone=(self)",
  `payment=(self "${RAZORPAY_CHECKOUT_ORIGIN}" "${RAZORPAY_API_ORIGIN}")`,
  "usb=()",
  "browsing-topics=()",
].join(", ");

export const STRICT_TRANSPORT_SECURITY = "max-age=63072000; includeSubDomains; preload";

export const buildSecurityHeaders = (options: SecurityHeaderOptions): SecurityHeader[] => {
  const headers: SecurityHeader[] = [
    { key: "Content-Security-Policy", value: buildContentSecurityPolicy(options) },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "Permissions-Policy", value: PERMISSIONS_POLICY },
  ];
  if (options.isDevelopment) {
    return headers;
  }
  return [...headers, { key: "Strict-Transport-Security", value: STRICT_TRANSPORT_SECURITY }];
};
