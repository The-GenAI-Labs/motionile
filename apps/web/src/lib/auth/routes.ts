export const AUTH_ROUTES = {
  login: "/login",
  register: "/register",
  verify: "/verify",
  refresh: "/refresh",
  forgotPassword: "/forgot-password",
  resetPassword: "/reset-password",
  dashboard: "/dashboard",
  forbidden: "/forbidden",
} as const;

const authPaths = new Set<string>([
  AUTH_ROUTES.login,
  AUTH_ROUTES.register,
  AUTH_ROUTES.verify,
  AUTH_ROUTES.refresh,
  AUTH_ROUTES.forgotPassword,
  AUTH_ROUTES.resetPassword,
]);

export const isAuthPath = (pathname: string): boolean =>
  authPaths.has(pathname.replace(/\/+$/, ""));

const hasControlCharacters = (value: string): boolean => {
  for (const character of value) {
    if (character.charCodeAt(0) <= 32 || character.charCodeAt(0) === 127) return true;
  }
  return false;
};

export const safeNextPath = (input: string | null | undefined): string => {
  if (!input || !input.startsWith("/") || input.includes("\\") || hasControlCharacters(input)) {
    return AUTH_ROUTES.dashboard;
  }
  try {
    const decoded = decodeURIComponent(input);
    if (decoded.includes("//") || /[\\%:]/.test(decoded) || hasControlCharacters(decoded)) {
      return AUTH_ROUTES.dashboard;
    }
    const parsed = new URL(decoded, "https://motionile.invalid");
    if (parsed.origin !== "https://motionile.invalid" || isAuthPath(parsed.pathname)) {
      return AUTH_ROUTES.dashboard;
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return AUTH_ROUTES.dashboard;
  }
};
