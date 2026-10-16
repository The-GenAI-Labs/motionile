"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import * as api from "@/features/auth/api/auth.api";
import { authKeys } from "@/features/auth/query-keys";
import type { AuthUser } from "@/features/auth/types/auth.types";
import { broadcastAuth } from "@/lib/auth/broadcast";

const useSignIn = () => {
  const client = useQueryClient();
  return (user: AuthUser) => {
    client.clear();
    client.setQueryData(authKeys.me(), user);
    broadcastAuth("signed-in");
  };
};
export const useRegister = () =>
  useMutation({
    mutationFn: ({ input, token }: { input: Parameters<typeof api.register>[0]; token: string }) =>
      api.register(input, token),
  });
export const useLogin = () =>
  useMutation({
    mutationFn: ({ input, token }: { input: Parameters<typeof api.login>[0]; token: string }) =>
      api.login(input, token),
    onSuccess: useSignIn(),
  });
export const useVerify = () => useMutation({ mutationFn: api.verify, onSuccess: useSignIn() });
export const useVerifyOtp = () =>
  useMutation({ mutationFn: api.verifyOtp, onSuccess: useSignIn() });
export const useRequestOtp = () =>
  useMutation({
    mutationFn: ({
      input,
      token,
    }: {
      input: Parameters<typeof api.requestOtp>[0];
      token: string;
    }) => api.requestOtp(input, token),
  });
export const useResendCode = () => useMutation({ mutationFn: api.resendCode });
export const useForgotPassword = () =>
  useMutation({
    mutationFn: ({
      input,
      token,
    }: {
      input: Parameters<typeof api.forgotPassword>[0];
      token: string;
    }) => api.forgotPassword(input, token),
  });
export const useResetPassword = () => useMutation({ mutationFn: api.resetPassword });
export const useRequestSetPassword = () => useMutation({ mutationFn: api.requestSetPassword });
export const useChangePassword = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.changePassword,
    onSuccess: () => client.invalidateQueries({ queryKey: authKeys.sessions() }),
  });
};
export const useSetPassword = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.setPassword,
    onSuccess: () => client.invalidateQueries({ queryKey: authKeys.all }),
  });
};
const useSignOut = () => {
  const client = useQueryClient();
  return () => {
    client.clear();
    broadcastAuth("signed-out");
    window.location.replace("/login");
  };
};
export const useLogout = () => useMutation({ mutationFn: api.logout, onSuccess: useSignOut() });
export const useLogoutAll = () =>
  useMutation({ mutationFn: api.logoutAll, onSuccess: useSignOut() });
export const useRevokeSession = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.revokeSession,
    onSuccess: () => client.invalidateQueries({ queryKey: authKeys.sessions() }),
  });
};
export const useUnlinkProvider = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.unlinkProvider,
    onSuccess: () => client.invalidateQueries({ queryKey: authKeys.me() }),
  });
};
export const useLinkProvider = () =>
  useMutation({
    mutationFn: api.startOAuthLink,
    onSuccess: ({ url }) => {
      window.location.assign(url);
    },
  });
