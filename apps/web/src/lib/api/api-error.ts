import { type FieldError, zProblemDetails } from "@motionile/api-contract";
import { type AxiosError, AxiosHeaders, isAxiosError, isCancel } from "axios";
import { z } from "zod";

export type ApiErrorKind = "http" | "network" | "timeout" | "cancelled" | "unknown";

export const API_ERROR_CODES = {
  network: "network_error",
  timeout: "request_timeout",
  cancelled: "request_cancelled",
  unknown: "unknown_error",
  http: "http_error",
} as const satisfies Record<ApiErrorKind, string>;

export const REQUEST_ID_HEADER = "x-request-id";

const PROBLEM_TYPE_BLANK = "about:blank";

const STATUS_TITLES: Readonly<Record<number, string>> = {
  400: "Bad request",
  401: "Unauthorized",
  403: "Forbidden",
  404: "Not found",
  405: "Method not allowed",
  408: "Request timeout",
  409: "Conflict",
  410: "Gone",
  413: "Content too large",
  415: "Unsupported media type",
  422: "Unprocessable content",
  429: "Too many requests",
  500: "Internal server error",
  502: "Bad gateway",
  503: "Service unavailable",
  504: "Gateway timeout",
};

const KIND_TITLES: Readonly<Record<Exclude<ApiErrorKind, "http">, string>> = {
  network: "Network error",
  timeout: "Request timed out",
  cancelled: "Request cancelled",
  unknown: "Unexpected error",
};

const KIND_DETAILS: Readonly<Record<Exclude<ApiErrorKind, "http">, string>> = {
  network: "We could not reach the server. Check your connection and try again.",
  timeout: "The server took too long to respond. Please try again.",
  cancelled: "The request was cancelled before it completed.",
  unknown: "Something went wrong. Please try again.",
};

const looseErrorBodySchema = z
  .object({
    code: z.string().optional(),
    title: z.string().optional(),
    message: z.string().optional(),
    detail: z.string().optional(),
    error: z.string().optional(),
  })
  .loose();

export interface ApiErrorInit {
  kind: ApiErrorKind;
  status: number | null;
  code: string;
  title: string;
  detail: string | null;
  type?: string | null;
  instance?: string | null;
  fieldErrors?: readonly FieldError[];
  requestId?: string | null;
  retryAfterSeconds?: number | null;
  cause?: unknown;
}

export interface HttpErrorResponse {
  status: number;
  body: unknown;
  getHeader: (name: string) => string | null;
}

const titleForStatus = (status: number): string =>
  STATUS_TITLES[status] ?? (status >= 500 ? "Server error" : "Request failed");

const parseRetryAfter = (value: string | null): number | null => {
  if (value === null || value.trim() === "") {
    return null;
  }
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.ceil(seconds);
  }
  const date = Date.parse(value);
  if (Number.isNaN(date)) {
    return null;
  }
  return Math.max(0, Math.ceil((date - Date.now()) / 1000));
};

const parseJsonText = (text: string): unknown => {
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
};

const normalizeBody = (body: unknown): unknown =>
  typeof body === "string" && body.trim() !== "" ? parseJsonText(body) : body;

const emptyToNull = (value: string | null | undefined): string | null =>
  value === undefined || value === null || value === "" ? null : value;

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string;
  readonly title: string;
  readonly detail: string | null;
  readonly type: string | null;
  readonly instance: string | null;
  readonly fieldErrors: readonly FieldError[];
  readonly requestId: string | null;
  readonly retryAfterSeconds: number | null;

  constructor(init: ApiErrorInit) {
    super(init.detail ?? init.title, { cause: init.cause });
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code;
    this.title = init.title;
    this.detail = init.detail;
    this.type = init.type ?? null;
    this.instance = init.instance ?? null;
    this.fieldErrors = init.fieldErrors ?? [];
    this.requestId = init.requestId ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }

  get isClientError(): boolean {
    return this.status !== null && this.status >= 400 && this.status < 500;
  }

  get isServerError(): boolean {
    return this.status !== null && this.status >= 500;
  }

  get isTransient(): boolean {
    return this.kind === "network" || this.kind === "timeout" || this.isServerError;
  }

  fieldError(field: string): string | undefined {
    return this.fieldErrors.find((error) => error.field === field)?.message;
  }

  static ofKind(
    kind: Exclude<ApiErrorKind, "http">,
    cause?: unknown,
    requestId: string | null = null,
  ): ApiError {
    return new ApiError({
      kind,
      status: null,
      code: API_ERROR_CODES[kind],
      title: KIND_TITLES[kind],
      detail: KIND_DETAILS[kind],
      requestId,
      cause,
    });
  }

  static fromResponse({ status, body, getHeader }: HttpErrorResponse, cause?: unknown): ApiError {
    const parsedBody = normalizeBody(body);
    const headerRequestId = emptyToNull(getHeader(REQUEST_ID_HEADER));
    const retryAfterSeconds = parseRetryAfter(getHeader("retry-after"));
    const problem = zProblemDetails.safeParse(parsedBody);
    if (problem.success) {
      return new ApiError({
        kind: "http",
        status,
        code: problem.data.code,
        title: problem.data.title,
        detail: emptyToNull(problem.data.detail),
        type: problem.data.type,
        instance: emptyToNull(problem.data.instance),
        fieldErrors: problem.data.errors ?? [],
        requestId: emptyToNull(problem.data.requestId) ?? headerRequestId,
        retryAfterSeconds,
        cause,
      });
    }
    const loose = looseErrorBodySchema.safeParse(parsedBody);
    const looseBody = loose.success ? loose.data : {};
    return new ApiError({
      kind: "http",
      status,
      code: looseBody.code ?? API_ERROR_CODES.http,
      title: looseBody.title ?? titleForStatus(status),
      detail: emptyToNull(looseBody.detail ?? looseBody.message ?? looseBody.error),
      type: PROBLEM_TYPE_BLANK,
      requestId: headerRequestId,
      retryAfterSeconds,
      cause,
    });
  }

  static from(error: unknown): ApiError {
    if (error instanceof ApiError) {
      return error;
    }
    if (isCancel(error)) {
      return ApiError.ofKind("cancelled", error);
    }
    if (isAxiosError(error)) {
      return fromAxiosError(error);
    }
    if (error instanceof DOMException) {
      return fromDomException(error);
    }
    if (error instanceof TypeError) {
      return ApiError.ofKind("network", error);
    }
    return ApiError.ofKind("unknown", error);
  }
}

const TIMEOUT_CODES = new Set(["ECONNABORTED", "ETIMEDOUT"]);

const fromAxiosError = (error: AxiosError): ApiError => {
  if (error.code === "ERR_CANCELED") {
    return ApiError.ofKind("cancelled", error);
  }
  if (error.code !== undefined && TIMEOUT_CODES.has(error.code)) {
    return ApiError.ofKind("timeout", error);
  }
  const response = error.response;
  if (response === undefined) {
    return ApiError.ofKind("network", error);
  }
  return ApiError.fromResponse(
    {
      status: response.status,
      body: response.data,
      getHeader: (name) => {
        const value: unknown =
          response.headers instanceof AxiosHeaders
            ? response.headers.get(name)
            : response.headers[name];
        return typeof value === "string" ? value : null;
      },
    },
    error,
  );
};

const fromDomException = (error: DOMException): ApiError => {
  if (error.name === "TimeoutError") {
    return ApiError.ofKind("timeout", error);
  }
  if (error.name === "AbortError") {
    return ApiError.ofKind("cancelled", error);
  }
  return ApiError.ofKind("network", error);
};

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;
