import { ApiError } from "@/lib/api/api-error";

export const authErrorMessages: Readonly<Record<string, string>> = {
  turnstile_required: "Complete the security check to continue.",
  turnstile_failed: "The security check failed. Please try again.",
  turnstile_unavailable: "The security check is unavailable. Try again shortly.",
  unauthenticated: "Please sign in to continue.",
  token_expired: "Your session expired. Please sign in again.",
  invalid_credentials: "The identifier or password is incorrect.",
  invalid_challenge: "The code is invalid or expired. Request a new code.",
  refresh_conflict: "Your session is updating. Please try again.",
  refresh_reused: "Please sign in again to secure your account.",
  session_expired: "Your session expired. Please sign in again.",
  origin_forbidden: "This request could not be verified. Reload the page and try again.",
  origin_not_allowed: "This request could not be verified. Reload the page and try again.",
  csrf_failed: "This request could not be verified. Reload the page and try again.",
  verification_required: "Verify your contact to finish signing in.",
  account_suspended: "Sign-in is unavailable. Please contact support.",
  not_found: "This item is no longer available.",
  verification_conflict: "Verification could not be completed. Start again.",
  password_already_set: "A password already exists. Use Change password.",
  verified_contact_required: "Verify a contact before continuing.",
  last_sign_in_method: "Add another sign-in method before removing this account.",
  validation_failed: "Check your details and try again.",
  invalid_identifier: "Enter a valid email address or phone number.",
  password_policy: "Use a password between 10 and 128 characters.",
  password_breached: "This password has appeared in a data breach. Choose another.",
  invalid_redirect: "The destination is invalid. Return to the dashboard.",
  service_unavailable: "The service is temporarily unavailable. Please try again.",
  oauth_failed: "We could not complete provider sign-in. Please try again.",
};

export const authErrorMessage = (error: unknown): string => {
  const normalized = ApiError.from(error);
  if (normalized.code === "rate_limited" || normalized.code === "otp_cooldown")
    return `Please wait ${String(normalized.retryAfterSeconds ?? 60)} seconds before trying again.`;
  return (
    authErrorMessages[normalized.code] ??
    `Something went wrong. Please try again.${normalized.requestId ? ` Request ID: ${normalized.requestId}` : ""}`
  );
};
