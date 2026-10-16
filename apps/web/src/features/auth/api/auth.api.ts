import * as contract from "@motionile/api-contract";
import { z } from "zod";

import { apiClient } from "@/lib/api/client";
import { safeNextPath } from "@/lib/auth/routes";

const post = async <I extends z.ZodType, O extends z.ZodType>(
  path: string,
  input: z.input<I>,
  inputSchema: I,
  outputSchema: O,
  token?: string,
  authenticated = false,
): Promise<z.output<O>> => {
  const response = await apiClient.post<unknown>(`/v1/auth/${path}`, inputSchema.parse(input), {
    authenticated,
    headers: token ? { "X-Turnstile-Token": token } : {},
  });
  return outputSchema.parse(response.status === 204 ? undefined : response.data);
};
export const register = (input: z.input<typeof contract.zAuthRegisterBody>, token: string) =>
  post("register", input, contract.zAuthRegisterBody, contract.zAuthRegisterResponse, token);
export const login = (input: z.input<typeof contract.zAuthLoginBody>, token: string) =>
  post("login", input, contract.zAuthLoginBody, contract.zAuthLoginResponse, token);
export const verify = (input: z.input<typeof contract.zAuthVerifyBody>) =>
  post("verify", input, contract.zAuthVerifyBody, contract.zAuthVerifyResponse);
export const requestOtp = (input: z.input<typeof contract.zAuthRequestOtpBody>, token: string) =>
  post("otp/request", input, contract.zAuthRequestOtpBody, contract.zAuthRequestOtpResponse, token);
export const verifyOtp = (input: z.input<typeof contract.zAuthVerifyOtpBody>) =>
  post("otp/verify", input, contract.zAuthVerifyOtpBody, contract.zAuthVerifyOtpResponse);
export const resendCode = () =>
  post("otp/resend", undefined, z.undefined(), contract.zAuthResendOtpResponse);
export const forgotPassword = (
  input: z.input<typeof contract.zAuthForgotPasswordBody>,
  token: string,
) =>
  post(
    "password/forgot",
    input,
    contract.zAuthForgotPasswordBody,
    contract.zAuthForgotPasswordResponse,
    token,
  );
export const resetPassword = (input: z.input<typeof contract.zAuthResetPasswordBody>) =>
  post(
    "password/reset",
    input,
    contract.zAuthResetPasswordBody,
    contract.zAuthResetPasswordResponse,
  );
export const changePassword = (input: z.input<typeof contract.zAuthChangePasswordBody>) =>
  post(
    "password/change",
    input,
    contract.zAuthChangePasswordBody,
    contract.zAuthChangePasswordResponse,
    undefined,
    true,
  );
export const requestSetPassword = () =>
  post(
    "password/set/request",
    undefined,
    z.undefined(),
    contract.zAuthRequestPasswordResponse,
    undefined,
    true,
  );
export const setPassword = (input: z.input<typeof contract.zAuthSetPasswordBody>) =>
  post(
    "password/set",
    input,
    contract.zAuthSetPasswordBody,
    contract.zAuthSetPasswordResponse,
    undefined,
    true,
  );
export const logout = () =>
  post("logout", undefined, z.undefined(), contract.zAuthLogoutResponse, undefined, true);
export const logoutAll = () =>
  post("logout-all", undefined, z.undefined(), contract.zAuthLogoutAllResponse, undefined, true);
export const currentUser = async () =>
  contract.zAuthMeResponse.parse(
    (await apiClient.get<unknown>("/v1/auth/me", { authenticated: true })).data,
  );
export const sessions = async (cursor?: string) =>
  contract.zAuthSessionsResponse.parse(
    (
      await apiClient.get<unknown>("/v1/auth/sessions", {
        authenticated: true,
        params: contract.zAuthSessionsQuery.parse({ cursor }),
      })
    ).data,
  );
export const revokeSession = async (sessionId: string) => {
  const path = contract.zAuthRevokeSessionPath.parse({ sessionId });
  await apiClient.delete(`/v1/auth/sessions/${path.sessionId}`, { authenticated: true });
  contract.zAuthRevokeSessionResponse.parse(undefined);
};
export const unlinkProvider = async (
  provider: z.infer<typeof contract.zAuthUnlinkOauthPath>["provider"],
) => {
  const path = contract.zAuthUnlinkOauthPath.parse({ provider });
  await apiClient.delete(`/v1/auth/oauth/${path.provider}`, { authenticated: true });
  contract.zAuthUnlinkOauthResponse.parse(undefined);
};
export const startOAuthLink = async (
  provider: z.infer<typeof contract.zAuthOauthStartPath>["provider"],
) => {
  const path = contract.zAuthOauthStartPath.parse({ provider });
  const response = await apiClient.post<unknown>(
    `/v1/auth/oauth/${path.provider}/start`,
    contract.zAuthOauthStartQuery.parse({
      next: safeNextPath("/settings/security"),
      intent: "link",
    }),
    { authenticated: true },
  );
  return contract.zOAuthStartResponse.parse(response.data);
};
