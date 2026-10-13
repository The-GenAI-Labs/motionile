import { randomInt, randomUUID } from "node:crypto";

export const ALLOWED_ORIGIN = process.env["ALLOWED_ORIGIN"] ?? "http://localhost:3000";
export const FOREIGN_ORIGIN = "https://evil.example";
export const PROBLEM_JSON = "application/problem+json";
export const ECHO_PATH = "/v1/_test/echo";
export const RATE_LIMITED_PATH = "/v1/_test/rate-limited";
export const IDEMPOTENT_PATH = "/v1/_test/idempotent";

export function uniqueClientIp(): string {
  return `198.18.${randomInt(0, 256)}.${randomInt(1, 255)}`;
}

export function clientHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { "X-Forwarded-For": uniqueClientIp(), ...extra };
}

export function uniqueKey(label: string): string {
  return `${label}-${randomUUID()}`;
}

export interface FieldError {
  field: string;
  message: string;
  type: string;
}

export interface Problem {
  type: string;
  title: string;
  status: number;
  code: string;
  requestId: string;
  detail?: string;
  instance?: string;
  errors?: FieldError[];
}
