import "server-only";

import { headers } from "next/headers";
import type { z } from "zod";

import { serverEnv } from "@/config/server-env";
import { ApiError, REQUEST_ID_HEADER } from "@/lib/api/api-error";
import { API_ACCEPT_HEADER, API_TIMEOUT_MS } from "@/lib/api/constants";

export type ServerFetchMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ServerFetchOptions<Schema extends z.ZodType> {
  schema: Schema;
  method?: ServerFetchMethod;
  body?: unknown;
  headers?: Record<string, string>;
  timeoutMs?: number;
  signal?: AbortSignal;
  cache?: RequestCache;
  next?: NextFetchRequestConfig;
}

const FORWARDED_HEADERS = ["cookie", REQUEST_ID_HEADER, "accept-language"] as const;

const readBody = async (response: Response): Promise<unknown> => {
  const text = await response.text();
  if (text === "") {
    return null;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
};

const forwardedHeaders = async (): Promise<Record<string, string>> => {
  const incoming = await headers();
  const forwarded: Record<string, string> = {};
  for (const name of FORWARDED_HEADERS) {
    const value = incoming.get(name);
    if (value !== null && value !== "") {
      forwarded[name] = value;
    }
  }
  return forwarded;
};

const buildSignal = (timeoutMs: number, signal: AbortSignal | undefined): AbortSignal => {
  const timeout = AbortSignal.timeout(timeoutMs);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
};

export const buildApiUrl = (path: string, baseUrl: string = serverEnv.apiBaseUrl): string =>
  new URL(path.replace(/^\/+/, ""), `${baseUrl}/`).toString();

export async function serverFetch<Schema extends z.ZodType>(
  path: string,
  options: ServerFetchOptions<Schema>,
): Promise<z.infer<Schema>> {
  const requestHeaders: Record<string, string> = {
    accept: API_ACCEPT_HEADER,
    ...(await forwardedHeaders()),
    ...options.headers,
  };
  if (options.body !== undefined) {
    requestHeaders["content-type"] = "application/json";
  }
  let response: Response;
  try {
    response = await fetch(buildApiUrl(path), {
      method: options.method ?? "GET",
      headers: requestHeaders,
      body: options.body === undefined ? null : JSON.stringify(options.body),
      cache: options.cache ?? "no-store",
      next: options.next,
      signal: buildSignal(options.timeoutMs ?? API_TIMEOUT_MS, options.signal),
    });
  } catch (error) {
    throw ApiError.from(error);
  }
  const body = await readBody(response);
  if (!response.ok) {
    throw ApiError.fromResponse({
      status: response.status,
      body,
      getHeader: (name) => response.headers.get(name),
    });
  }
  const parsed = options.schema.safeParse(body);
  if (!parsed.success) {
    throw new ApiError({
      kind: "unknown",
      status: response.status,
      code: "invalid_response",
      title: "Invalid response",
      detail: "The server returned a response in an unexpected format.",
      requestId: response.headers.get(REQUEST_ID_HEADER),
      cause: parsed.error,
    });
  }
  return parsed.data;
}
