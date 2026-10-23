import { randomUUID } from "node:crypto";

import { type APIResponse, expect, test } from "@playwright/test";

import {
  edgeAllows,
  edgeConfig,
  encodeCloudFrontBase64,
  KEY_PAIR_COOKIE,
  POLICY_COOKIE,
  policyOf,
  responseCookies,
  SIGNATURE_COOKIE,
  type SignedCookies,
  signedCookies,
} from "../../support/cloudfront-edge.js";
import { MediaClient, type MediaSession } from "../../support/media.js";

const config = edgeConfig();

interface Grant {
  response: APIResponse;
  body: MediaSession;
  cookies: SignedCookies;
}

async function grant(client: MediaClient): Promise<Grant> {
  const response = await client.mediaSession();
  expect(response.status(), await response.text()).toBe(200);
  return {
    response,
    body: (await response.json()) as MediaSession,
    cookies: signedCookies(responseCookies(response)),
  };
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

function mediaUrl(userId: string, path: string): string {
  return `https://${config.cdnDomain}/media/u/${userId}/${path}`;
}

function rootUrl(root: string, path: string): string {
  return `https://${config.cdnDomain}/${root}/${path}`;
}

test.describe("CloudFront signed cookies scope media to the signed-in user", () => {
  let userA: MediaClient;
  let userB: MediaClient;
  let a: Grant;
  let b: Grant;
  const renderId = randomUUID();

  test.beforeAll(async ({ playwright }) => {
    const request = await playwright.request.newContext();
    userA = await MediaClient.signup(request);
    userB = await MediaClient.signup(request);
    a = await grant(userA);
    b = await grant(userB);
  });

  test("the session reports cloudfront mode and an expiry from the configured lifetime", () => {
    expect(a.body.mode).toBe("cloudfront");
    const expiresAt = Date.parse(a.body.expiresAt ?? "") / 1000;
    expect(Math.abs(expiresAt - (nowSeconds() + config.cookieTtlSeconds))).toBeLessThan(30);
    expect(a.response.headers()["cache-control"]).toBe("no-store");
  });

  test("the three signed cookies are Secure, HttpOnly, SameSite=Lax and scoped to the cookie domain", () => {
    const cookies = responseCookies(a.response);

    expect(cookies.map((cookie) => cookie.name).sort()).toEqual(
      [KEY_PAIR_COOKIE, POLICY_COOKIE, SIGNATURE_COOKIE].sort(),
    );
    for (const cookie of cookies) {
      expect(cookie.attributes.has("secure"), cookie.name).toBe(true);
      expect(cookie.attributes.has("httponly"), cookie.name).toBe(true);
      expect(cookie.attributes.get("samesite")?.toLowerCase(), cookie.name).toBe("lax");
      expect(cookie.attributes.get("domain")?.replace(/^\./, ""), cookie.name).toBe(
        config.cookieDomain.replace(/^\./, ""),
      );
      expect(cookie.attributes.get("path"), cookie.name).toBe("/");
      expect(cookie.attributes.get("max-age"), cookie.name).toBe(String(config.cookieTtlSeconds));
    }
  });

  test("the key pair id names the configured public key", () => {
    expect(a.cookies.keyPairId).toBe(config.keyPairId);
  });

  test("the policy covers exactly the user's own media prefix with a single trailing wildcard", () => {
    const statements = policyOf(a.cookies).Statement;

    expect(statements).toHaveLength(1);
    expect(statements[0]?.Resource).toBe(`https://${config.cdnDomain}/media/u/${userA.userId}/*`);
    expect(statements[0]?.Resource.split("*")).toHaveLength(2);
  });

  test("the edge accepts the signature and the user's own render files", () => {
    const base = `renders/${renderId}`;

    for (const file of ["16x9.mp4", "9x16.mp4", "poster-16x9.webp", "subtitles.vtt", "audio.m4a"]) {
      expect(
        edgeAllows(a.cookies, config, mediaUrl(userA.userId, `${base}/${file}`), nowSeconds()),
        file,
      ).toBe(true);
    }
  });

  test("user A's cookies cannot fetch user B's media path and user B's cannot fetch user A's", () => {
    const path = `renders/${renderId}/16x9.mp4`;

    expect(edgeAllows(a.cookies, config, mediaUrl(userB.userId, path), nowSeconds())).toBe(false);
    expect(edgeAllows(b.cookies, config, mediaUrl(userA.userId, path), nowSeconds())).toBe(false);
    expect(edgeAllows(b.cookies, config, mediaUrl(userB.userId, path), nowSeconds())).toBe(true);
  });

  test("the two users' policies and signatures differ", () => {
    expect(a.cookies.policy).not.toBe(b.cookies.policy);
    expect(a.cookies.signature).not.toBe(b.cookies.signature);
    expect(policyOf(b.cookies).Statement[0]?.Resource).not.toContain(userA.userId);
  });

  test("the cookies grant nothing outside the media prefix, even for the user's own files", () => {
    const own = userA.userId;
    const urls = [
      rootUrl("voice", `u/${own}/${randomUUID()}/consent.wav`),
      rootUrl("voice", `u/${own}/${randomUUID()}/sample-0.wav`),
      rootUrl("work", `renders/${renderId}/scene-intro.wav`),
      rootUrl("tts", "ab/abcdef0123456789.mp3"),
      rootUrl("music", `${randomUUID()}.mp3`),
      rootUrl("voice-preview", `${randomUUID()}.mp3`),
      rootUrl("share", "anything"),
      `https://${config.cdnDomain}/`,
    ];

    for (const url of urls) {
      expect(edgeAllows(a.cookies, config, url, nowSeconds()), url).toBe(false);
    }
  });

  test("the cookies grant nothing on another host or over plain http", () => {
    const path = `renders/${renderId}/16x9.mp4`;

    expect(
      edgeAllows(
        a.cookies,
        config,
        `https://evil.example/media/u/${userA.userId}/${path}`,
        nowSeconds(),
      ),
    ).toBe(false);
    expect(
      edgeAllows(
        a.cookies,
        config,
        `http://${config.cdnDomain}/media/u/${userA.userId}/${path}`,
        nowSeconds(),
      ),
    ).toBe(false);
  });

  test("the edge rejects the cookies after they expire", () => {
    const url = mediaUrl(userA.userId, `renders/${renderId}/16x9.mp4`);
    const lastSecond = nowSeconds() + config.cookieTtlSeconds - 30;
    const afterExpiry = nowSeconds() + config.cookieTtlSeconds + 30;

    expect(edgeAllows(a.cookies, config, url, lastSecond)).toBe(true);
    expect(edgeAllows(a.cookies, config, url, afterExpiry)).toBe(false);
  });

  test("a policy rewritten to cover another user's prefix fails signature verification", () => {
    const forged = {
      Statement: [
        {
          Resource: `https://${config.cdnDomain}/media/u/${userB.userId}/*`,
          Condition: { DateLessThan: { "AWS:EpochTime": nowSeconds() + 3600 } },
        },
      ],
    };
    const tampered: SignedCookies = {
      ...a.cookies,
      policy: encodeCloudFrontBase64(Buffer.from(JSON.stringify(forged))),
    };

    expect(
      edgeAllows(
        tampered,
        config,
        mediaUrl(userB.userId, `renders/${renderId}/16x9.mp4`),
        nowSeconds(),
      ),
    ).toBe(false);
  });

  test("a widened wildcard or an extended expiry fails signature verification", () => {
    const original = policyOf(a.cookies);
    const widened = {
      Statement: [{ ...original.Statement[0], Resource: `https://${config.cdnDomain}/media/u/*` }],
    };
    const extended = {
      Statement: [
        {
          ...original.Statement[0],
          Condition: { DateLessThan: { "AWS:EpochTime": nowSeconds() + 10 * 365 * 86400 } },
        },
      ],
    };
    const url = mediaUrl(userB.userId, `renders/${renderId}/16x9.mp4`);

    for (const policy of [widened, extended]) {
      const tampered: SignedCookies = {
        ...a.cookies,
        policy: encodeCloudFrontBase64(Buffer.from(JSON.stringify(policy))),
      };
      expect(edgeAllows(tampered, config, url, nowSeconds())).toBe(false);
    }
  });

  test("user B's signature cannot be paired with user A's policy", () => {
    const swapped: SignedCookies = { ...a.cookies, signature: b.cookies.signature };

    expect(
      edgeAllows(
        swapped,
        config,
        mediaUrl(userA.userId, `renders/${renderId}/16x9.mp4`),
        nowSeconds(),
      ),
    ).toBe(false);
  });

  test("a new media session is issued on every call and each one is valid", async () => {
    const refreshed = await grant(userA);

    expect(
      edgeAllows(
        refreshed.cookies,
        config,
        mediaUrl(userA.userId, `renders/${renderId}/16x9.mp4`),
        nowSeconds(),
      ),
    ).toBe(true);
  });
});
