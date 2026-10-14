import axios, { type AxiosInstance } from "axios";

import { env } from "@/config/env";
import { ApiError } from "@/lib/api/api-error";
import { API_ACCEPT_HEADER, API_TIMEOUT_MS } from "@/lib/api/constants";

export const createApiClient = (baseURL: string = env.NEXT_PUBLIC_API_URL): AxiosInstance => {
  const instance = axios.create({
    baseURL,
    withCredentials: true,
    timeout: API_TIMEOUT_MS,
    headers: { Accept: API_ACCEPT_HEADER, "Content-Type": "application/json" },
    responseType: "json",
  });
  instance.interceptors.response.use(undefined, (error: unknown) =>
    Promise.reject(ApiError.from(error)),
  );
  return instance;
};

export const apiClient = createApiClient();
