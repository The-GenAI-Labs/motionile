import { createPublicKey, verify } from "node:crypto";

import type { APIResponse } from "@playwright/test";

export const POLICY_COOKIE = "CloudFront-Policy";
export const SIGNATURE_COOKIE = "CloudFront-Signature";
export const KEY_PAIR_COOKIE = "CloudFront-Key-Pair-Id";

export interface EdgeConfig {
  cdnDomain: string;
  cookieDomain: string;
  cookieTtlSeconds: number;
  keyPairId: string;
  publicKeyPem: string;
}

export interface ResponseCookie {
  name: string;
  value: string;
  attributes: Map<string, string>;
}

interface Policy {
  Statement: { Resource: string; Condition: { DateLessThan: { "AWS:EpochTime": number } } }[];
}

export interface SignedCookies {
  policy: string;
  signature: string;
  keyPairId: string;
}

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must be set for the CloudFront delivery security suite`);
  return value;
}

export function edgeConfig(): EdgeConfig {
  return {
    cdnDomain: required("CDN_DOMAIN"),
    cookieDomain: required("MEDIA_COOKIE_DOMAIN"),
    cookieTtlSeconds: Number(required("MEDIA_COOKIE_TTL_SECONDS")),
    keyPairId: required("CLOUDFRONT_KEY_PAIR_ID"),
    publicKeyPem: Buffer.from(required("CLOUDFRONT_TEST_PUBLIC_KEY"), "base64").toString("utf8"),
  };
}

export function decodeCloudFrontBase64(value: string): Buffer {
  return Buffer.from(
    value.replaceAll("-", "+").replaceAll("_", "=").replaceAll("~", "/"),
    "base64",
  );
}

export function encodeCloudFrontBase64(data: Buffer): string {
  return data.toString("base64").replaceAll("+", "-").replaceAll("=", "_").replaceAll("/", "~");
}

export function responseCookies(response: APIResponse): ResponseCookie[] {
  return response
    .headersArray()
    .filter((header) => header.name.toLowerCase() === "set-cookie")
    .map((header) => {
      const [pair = "", ...rest] = header.value.split(";").map((part) => part.trim());
      const index = pair.indexOf("=");
      const attributes = new Map<string, string>();
      for (const attribute of rest) {
        const separator = attribute.indexOf("=");
        const key = (separator === -1 ? attribute : attribute.slice(0, separator)).toLowerCase();
        attributes.set(key, separator === -1 ? "" : attribute.slice(separator + 1));
      }
      return { name: pair.slice(0, index), value: pair.slice(index + 1), attributes };
    });
}

export function signedCookies(cookies: ResponseCookie[]): SignedCookies {
  const find = (name: string): string => {
    const cookie = cookies.find((candidate) => candidate.name === name);
    if (cookie === undefined) throw new Error(`The ${name} cookie was not set`);
    return cookie.value;
  };
  return {
    policy: find(POLICY_COOKIE),
    signature: find(SIGNATURE_COOKIE),
    keyPairId: find(KEY_PAIR_COOKIE),
  };
}

function wildcardPattern(resource: string): RegExp {
  const escaped = resource.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  return new RegExp("^" + escaped.replaceAll("*", ".*").replaceAll("?", ".") + "$");
}

export function policyOf(cookies: SignedCookies): Policy {
  return JSON.parse(decodeCloudFrontBase64(cookies.policy).toString("utf8")) as Policy;
}

export function edgeAllows(
  cookies: SignedCookies,
  config: EdgeConfig,
  url: string,
  nowEpochSeconds: number,
): boolean {
  if (cookies.keyPairId !== config.keyPairId) return false;
  const signatureValid = verify(
    "RSA-SHA1",
    decodeCloudFrontBase64(cookies.policy),
    createPublicKey(config.publicKeyPem),
    decodeCloudFrontBase64(cookies.signature),
  );
  if (!signatureValid) return false;
  const statement = policyOf(cookies).Statement[0];
  if (statement === undefined) return false;
  if (nowEpochSeconds >= statement.Condition.DateLessThan["AWS:EpochTime"]) return false;
  return wildcardPattern(statement.Resource).test(url);
}
