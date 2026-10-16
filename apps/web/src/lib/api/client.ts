import axios, { type AxiosInstance, isAxiosError } from "axios";

import { env } from "@/config/env";
import { ApiError } from "@/lib/api/api-error";
import { API_ACCEPT_HEADER, API_TIMEOUT_MS } from "@/lib/api/constants";
import { readCookie } from "@/lib/auth/cookies";
import { refreshSession, waitForRefresh } from "@/lib/auth/refresh";
import { expireSession } from "@/lib/auth/session-expiry";

declare module "axios" {
  interface AxiosRequestConfig {
    authenticated?: boolean;
    skipAuthRefresh?: boolean;
    retried?: boolean;
  }
}

const unsafeMethods = new Set(["post", "put", "patch", "delete"]);
const expiredCodes = new Set(["refresh_reused", "session_expired", "unauthenticated"]);

export const createApiClient = (baseURL: string = env.NEXT_PUBLIC_API_URL): AxiosInstance => {
  const instance = axios.create({
    baseURL,
    withCredentials: true,
    timeout: API_TIMEOUT_MS,
    headers: { Accept: API_ACCEPT_HEADER, "Content-Type": "application/json" },
    responseType: "json",
  });
  instance.interceptors.request.use((config) => {
    if (unsafeMethods.has(config.method ?? "get")) {
      const csrf = readCookie("mo_csrf");
      if (csrf) config.headers.set("X-CSRF-Token", csrf);
    }
    return config;
  });
  instance.interceptors.response.use(undefined, async (error: unknown) => {
    const normalized = ApiError.from(error);
    const config = isAxiosError(error) ? error.config : undefined;
    if (!config || config.skipAuthRefresh) throw normalized;
    if (config.authenticated && expiredCodes.has(normalized.code)) expireSession();
    if (config.retried) {
      if (config.authenticated && normalized.code === "token_expired") expireSession();
      throw normalized;
    }
    if (normalized.code === "token_expired" || normalized.code === "refresh_conflict") {
      config.retried = true;
      if (normalized.code === "token_expired") await refreshSession();
      else await waitForRefresh();
      return instance.request(config);
    }
    throw normalized;
  });
  return instance;
};

export const apiClient = createApiClient();
