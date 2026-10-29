import { randomBytes, randomUUID } from "node:crypto";

import { type APIRequestContext, type APIResponse, expect, test } from "@playwright/test";

import {
  Creator,
  type Job,
  type JobProblem,
  prepareBuiltinVoice,
  type SharedVideo,
  type ShareLink,
  withoutVolatileFields,
} from "../../support/generation.js";
import { PROBLEM_JSON, uniqueClientIp } from "./support.js";

const SLUG_FORMAT = /^[A-Za-z0-9_-]{22}$/;
const SAMPLES_PER_OWNER = 25;
const SLUG_BYTES = 16;
const MIN_ENTROPY_BITS = 5.3;
const MAX_SHARED_PREFIX = 4;
const MIN_DISTINCT_FIRST_CHARACTERS = 20;
const BIT_BALANCE = { low: 8, high: 42 };
const MAX_PLAYBACK_SECONDS = 3600;
const MIN_PLAYBACK_SECONDS = 60;
const TIMING_SAMPLES = 15;
const TIMING_WARMUP = 3;
const TIMING_FLOOR_MS = 150;
const RATE_LIMIT_OVERSHOOT = 5;
const PUBLIC_KEYS = [
  "allowIndexing",
  "aspect",
  "durationMs",
  "height",
  "language",
  "playbackExpiresInSeconds",
  "playbackUrl",
  "posterUrl",
  "summary",
  "title",
  "width",
];
const MALFORMED_SLUGS = [
  "x",
  "short",
  "!".repeat(22),
  "a".repeat(33),
  "x".repeat(64),
  "%00",
  "é".repeat(22),
];

let primary: Creator;
let samplerOne: Creator;
let samplerTwo: Creator;
let stranger: Creator;
let primaryJob: Job;
let samplerJobs: Job[];
let live: ShareLink;
let sampled: ShareLink[] = [];

function publicGet(
  request: APIRequestContext,
  slug: string,
  ip: string = uniqueClientIp(),
): Promise<APIResponse> {
  return request.get(`/v1/share/${encodeURIComponent(slug)}`, {
    headers: { "X-Forwarded-For": ip },
  });
}

function randomSlug(): string {
  return randomBytes(SLUG_BYTES).toString("base64url");
}

function entropyBits(text: string): number {
  const counts = new Map<string, number>();
  for (const character of text) counts.set(character, (counts.get(character) ?? 0) + 1);
  let bits = 0;
  for (const count of counts.values()) {
    const probability = count / text.length;
    bits -= probability * Math.log2(probability);
  }
  return bits;
}

function sharedPrefix(left: string, right: string): number {
  let length = 0;
  while (length < left.length && left[length] === right[length]) length += 1;
  return length;
}

function median(values: number[]): number {
  const ordered = [...values].sort((a, b) => a - b);
  return ordered[Math.floor(ordered.length / 2)] ?? 0;
}

async function medianLatency(request: APIRequestContext, slug: string): Promise<number> {
  const ip = uniqueClientIp();
  const durations: number[] = [];
  for (let attempt = 0; attempt < TIMING_WARMUP + TIMING_SAMPLES; attempt += 1) {
    const started = performance.now();
    const response = await publicGet(request, slug, ip);
    const elapsed = performance.now() - started;
    expect(response.status()).toBe(404);
    if (attempt >= TIMING_WARMUP) durations.push(elapsed);
  }
  return median(durations);
}

async function sample(owner: Creator, job: Job): Promise<ShareLink[]> {
  const links: ShareLink[] = [];
  for (let index = 0; index < SAMPLES_PER_OWNER; index += 1) {
    links.push(await owner.createShareLink(job.id));
  }
  return links;
}

test.describe.configure({ mode: "serial", timeout: 120000 });

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(900000);
  const request = await playwright.request.newContext();
  await prepareBuiltinVoice(request);
  [primary, samplerOne, samplerTwo, stranger] = await Promise.all([
    Creator.funded(request),
    Creator.funded(request),
    Creator.funded(request),
    Creator.signup(request),
  ]);
  [primaryJob, ...samplerJobs] = await Promise.all([
    primary.completedVideo(),
    samplerOne.completedVideo(),
    samplerTwo.completedVideo(),
  ]);
  live = await primary.createShareLink(primaryJob.id);
});

test("fifty share slugs are 22 URL-safe characters, unique and unguessable", async () => {
  const [jobOne, jobTwo] = samplerJobs;
  if (jobOne === undefined || jobTwo === undefined) throw new Error("The sampler jobs are missing");

  sampled = (await Promise.all([sample(samplerOne, jobOne), sample(samplerTwo, jobTwo)])).flat();
  const slugs = sampled.map((link) => link.slug);

  expect(slugs).toHaveLength(2 * SAMPLES_PER_OWNER);
  for (const slug of slugs) expect(slug).toMatch(SLUG_FORMAT);
  expect(new Set(slugs).size).toBe(slugs.length);
  let longestPrefix = 0;
  for (const [index, slug] of slugs.entries()) {
    for (const other of slugs.slice(index + 1)) {
      longestPrefix = Math.max(longestPrefix, sharedPrefix(slug, other));
    }
  }
  expect(longestPrefix).toBeLessThanOrEqual(MAX_SHARED_PREFIX);
  expect(new Set(slugs.map((slug) => slug[0])).size).toBeGreaterThanOrEqual(
    MIN_DISTINCT_FIRST_CHARACTERS,
  );
  expect(entropyBits(slugs.join(""))).toBeGreaterThanOrEqual(MIN_ENTROPY_BITS);
  for (const slug of slugs) {
    expect(new Set(slug).size).toBeGreaterThanOrEqual(10);
    expect(slug).not.toContain(primaryJob.id.slice(0, 8));
  }
});

test("every bit of the decoded slugs is balanced and nothing in a slug is derived from an id", () => {
  const decoded = sampled.map((link) => Buffer.from(link.slug, "base64url"));
  const owners = [samplerOne.userId, samplerTwo.userId].map((id) => id.replaceAll("-", ""));

  for (const bytes of decoded) expect(bytes).toHaveLength(SLUG_BYTES);
  for (let bit = 0; bit < SLUG_BYTES * 8; bit += 1) {
    const ones = decoded.filter((bytes) => ((bytes[bit >> 3] ?? 0) >> (7 - (bit & 7))) & 1).length;
    expect(ones, `bit ${bit}`).toBeGreaterThanOrEqual(BIT_BALANCE.low);
    expect(ones, `bit ${bit}`).toBeLessThanOrEqual(BIT_BALANCE.high);
  }
  for (const link of sampled) {
    expect(owners.some((id) => link.slug.includes(id.slice(0, 8)))).toBe(false);
    expect(link.url.endsWith(`/v/${link.slug}`)).toBe(true);
    expect(link.viewCount).toBe(0);
    expect(link.allowIndexing).toBe(false);
  }
});

test("a live link shows the video without the owner, the job or any storage key", async ({
  request,
}) => {
  const response = await publicGet(request, live.slug);
  const body = (await response.json()) as SharedVideo;
  const { playbackUrl, posterUrl, ...fields } = body;
  const text = JSON.stringify(fields);
  const renderId = primaryJob.renderId;
  if (renderId === null) throw new Error("The finished job has no render");
  const secrets = [
    primary.userId,
    primary.auth.email,
    primaryJob.id,
    renderId,
    live.renditionId,
    "media/u/",
    "renders/",
  ];

  expect(response.status(), JSON.stringify(body)).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(Object.keys(body).sort()).toEqual(PUBLIC_KEYS);
  expect(body.allowIndexing).toBe(false);
  for (const secret of secrets) expect(text).not.toContain(secret);
  for (const url of [playbackUrl, posterUrl ?? ""]) {
    expect(url).not.toContain(primaryJob.id);
    expect(decodeURIComponent(url)).not.toContain(primary.auth.email);
  }
});

test("the playback URL is short-lived, signed and plays the video", async ({ request }) => {
  const response = await publicGet(request, live.slug);
  const body = (await response.json()) as SharedVideo;
  const playback = new URL(body.playbackUrl);
  const signedLifetime = playback.searchParams.get("X-Amz-Expires");

  expect(body.playbackExpiresInSeconds).toBeGreaterThanOrEqual(MIN_PLAYBACK_SECONDS);
  expect(body.playbackExpiresInSeconds).toBeLessThanOrEqual(MAX_PLAYBACK_SECONDS);
  if (signedLifetime !== null) expect(Number(signedLifetime)).toBe(body.playbackExpiresInSeconds);
  expect(playback.searchParams.get("X-Amz-Signature")).not.toBeNull();
  const ranged = await request.get(body.playbackUrl, { headers: { Range: "bytes=0-63" } });
  expect(ranged.status()).toBe(206);
  const unsigned = await request.get(body.playbackUrl.split("?")[0] ?? "");
  expect(unsigned.status()).toBe(403);
});

test("indexing is off unless the owner allows it and a new link revokes the previous one", async ({
  request,
}) => {
  const allowed = await primary.createShareLink(primaryJob.id, {
    aspect: "16:9",
    allowIndexing: true,
  });
  const publicAllowed = (await (await publicGet(request, allowed.slug)).json()) as SharedVideo;
  const previous = await publicGet(request, live.slug);
  const restored = await primary.createShareLink(primaryJob.id, {
    aspect: "16:9",
    allowIndexing: false,
  });
  const publicRestored = (await (await publicGet(request, restored.slug)).json()) as SharedVideo;
  const revoked = await publicGet(request, allowed.slug);

  expect(allowed.allowIndexing).toBe(true);
  expect(publicAllowed.allowIndexing).toBe(true);
  expect(previous.status()).toBe(404);
  expect(publicRestored.allowIndexing).toBe(false);
  expect(revoked.status()).toBe(404);
  live = restored;
});

test("a link request needs exactly one valid target on a rendition of the same video", async () => {
  const foreignRendition = sampled[0]?.renditionId ?? "";
  const attempts: [string, Record<string, unknown>, number, string][] = [
    ["no target", {}, 422, "validation_failed"],
    ["two targets", { aspect: "16:9", renditionId: live.renditionId }, 422, "validation_failed"],
    ["an aspect that was not rendered", { aspect: "9:16" }, 404, "share_rendition_not_found"],
    [
      "a rendition that does not exist",
      { renditionId: randomUUID() },
      404,
      "share_rendition_not_found",
    ],
    [
      "a rendition of another user's video",
      { renditionId: foreignRendition },
      404,
      "share_rendition_not_found",
    ],
  ];

  for (const [label, body, status, code] of attempts) {
    const response = await primary.share(primaryJob.id, body);
    expect(response.status(), label).toBe(status);
    expect(((await response.json()) as JobProblem).code, label).toBe(code);
  }
  expect(foreignRendition).not.toBe("");
  expect(foreignRendition).not.toBe(live.renditionId);
});

test("a video that has not finished cannot be shared", async () => {
  const waiting = await primary.awaitingApproval();

  const response = await primary.share(waiting.id);

  expect(response.status(), await response.text()).toBe(409);
  expect(((await response.json()) as JobProblem).code).toBe("job_not_shareable");
  expect((await primary.cancel(waiting.id)).status()).toBe(202);
});

test("revoked, unknown and malformed slugs return the same 404 body", async ({ request }) => {
  const baseline = await publicGet(request, randomSlug());
  const baselineProblem = (await baseline.json()) as JobProblem;
  const revokedSlugs = sampled.slice(0, 3).map((link) => link.slug);
  const candidates = [
    ...revokedSlugs.map((slug) => ["a revoked slug", slug] as const),
    ...MALFORMED_SLUGS.map((slug) => ["a malformed slug", slug] as const),
    ["another unknown slug", randomSlug()] as const,
  ];

  expect(baseline.status()).toBe(404);
  expect(baseline.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(baselineProblem.code).toBe("share_not_found");
  for (const [label, slug] of candidates) {
    const response = await publicGet(request, slug);
    const problem = (await response.json()) as JobProblem;

    expect(response.status(), `${label} ${slug}`).toBe(404);
    expect(response.headers()["content-type"], label).toBe(PROBLEM_JSON);
    expect(response.headers()["cache-control"], label).toBe(baseline.headers()["cache-control"]);
    expect(withoutVolatileFields(problem), `${label} ${slug}`).toEqual(
      withoutVolatileFields(baselineProblem),
    );
    expect(Object.keys(problem).sort(), label).toEqual(Object.keys(baselineProblem).sort());
  }
});

test("revoked, unknown and malformed slugs take about as long to answer", async ({ request }) => {
  const revoked = sampled[0]?.slug ?? "";
  const unknown = await medianLatency(request, randomSlug());
  const revokedMedian = await medianLatency(request, revoked);
  const malformed = await medianLatency(request, "!".repeat(22));

  for (const other of [revokedMedian, malformed]) {
    expect(Math.abs(other - unknown)).toBeLessThanOrEqual(
      Math.max(TIMING_FLOOR_MS, 2 * Math.min(other, unknown)),
    );
  }
});

test("views are limited per address with Retry-After and other addresses are unaffected", async ({
  request,
}) => {
  const ip = uniqueClientIp();
  const first = await publicGet(request, live.slug, ip);
  const limit = Number(first.headers()["ratelimit-limit"]);
  expect(Number.isInteger(limit) && limit > 0).toBe(true);
  const statuses = [first.status()];
  for (let attempt = 1; attempt < limit + RATE_LIMIT_OVERSHOOT; attempt += 1) {
    statuses.push((await publicGet(request, randomSlug(), ip)).status());
  }

  const limited = await publicGet(request, live.slug, ip);
  const other = await publicGet(request, live.slug);

  expect(statuses[0]).toBe(200);
  expect(statuses.slice(1, limit).every((status) => status === 404)).toBe(true);
  expect(statuses.slice(limit).every((status) => status === 429)).toBe(true);
  expect(limited.status()).toBe(429);
  expect(limited.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(((await limited.json()) as JobProblem).code).toBe("rate_limited");
  expect(Number(limited.headers()["retry-after"])).toBeGreaterThanOrEqual(1);
  expect(Number(limited.headers()["retry-after"])).toBeLessThanOrEqual(3600);
  expect(limited.headers()["ratelimit-limit"]).toBe(String(limit));
  expect(other.status()).toBe(200);
});

test("another user cannot share, unshare, cancel, revise or delete a finished video", async () => {
  const attempts = await Promise.all([
    stranger.share(primaryJob.id),
    stranger.unshare(primaryJob.id),
    stranger.cancel(primaryJob.id),
    stranger.revise(primaryJob.id, "Use a calmer tone"),
    stranger.remove(primaryJob.id),
  ]);

  for (const attempt of attempts) {
    expect(attempt.status(), await attempt.text()).toBe(404);
    expect(((await attempt.json()) as JobProblem).code).toBe("job_not_found");
  }
  expect((await primary.fetchJob(primaryJob.id)).status).toBe("completed");
});

test("the library of another user never lists the finished video and the owner's library does", async ({
  request,
}) => {
  const strangerLibrary = await stranger.library("?limit=100");
  const ownerLibrary = await primary.library("?limit=100");
  const entry = ownerLibrary.items.find((item) => item.jobId === primaryJob.id);
  const stillLive = await publicGet(request, live.slug);

  expect(strangerLibrary.items).toEqual([]);
  expect(JSON.stringify(strangerLibrary)).not.toContain(primaryJob.id);
  expect(entry).toBeDefined();
  expect(entry?.shareSlug).toBe(live.slug);
  expect(stillLive.status()).toBe(200);
});

test("revoking the link makes the slug look like an unknown one", async ({ request }) => {
  const baseline = await publicGet(request, randomSlug());

  const revoked = await primary.unshare(primaryJob.id);
  const response = await publicGet(request, live.slug);

  expect(revoked.status()).toBe(204);
  expect(response.status()).toBe(404);
  expect(withoutVolatileFields(await response.json())).toEqual(
    withoutVolatileFields(await baseline.json()),
  );
  const entry = (await primary.library("?limit=100")).items.find(
    (item) => item.jobId === primaryJob.id,
  );
  expect(entry).toBeDefined();
  expect(entry?.shareSlug).toBeNull();
});

test("deleting the video kills its link and removes it from the library", async ({ request }) => {
  const relinked = await primary.createShareLink(primaryJob.id);
  expect((await publicGet(request, relinked.slug)).status()).toBe(200);

  const removed = await primary.remove(primaryJob.id);
  const response = await publicGet(request, relinked.slug);

  expect(removed.status()).toBe(204);
  expect(response.status()).toBe(404);
  expect(((await response.json()) as JobProblem).code).toBe("share_not_found");
  expect((await primary.library("?limit=100")).items.map((item) => item.jobId)).not.toContain(
    primaryJob.id,
  );
  expect((await primary.call("GET", `/v1/jobs/${primaryJob.id}`)).status()).toBe(404);
});
