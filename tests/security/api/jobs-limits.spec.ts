import { randomUUID } from "node:crypto";

import { type APIResponse, expect, test } from "@playwright/test";

import {
  Creator,
  type EventStream,
  jobBody,
  type JobProblem,
  prepareBuiltinVoice,
  QUESTION,
  SHORT_DURATION_SECONDS,
} from "../../support/generation.js";
import { PROBLEM_JSON } from "./support.js";

const MAX_QUERY_CHARS = 2000;
const MAX_ACTIVE_JOBS = 2;
const STREAM_CAP = 5;
const CREATE_LIMIT = 5;
const OVERSIZED_QUERY_CHARS = 300000;
const BOUNDARY_QUERY = `${QUESTION} ${"Hash tables spread keys over buckets. ".repeat(60)}`
  .slice(0, MAX_QUERY_CHARS - 1)
  .concat(".");

const OPTIONS = { durationSeconds: SHORT_DURATION_SECONDS, reviewStoryboard: true };

type InvalidBody = readonly [label: string, body: Record<string, unknown>, field: string];

const INVALID_BODIES: readonly (readonly [group: string, bodies: InvalidBody[]])[] = [
  [
    "field bounds",
    [
      [
        "a query of 2001 characters",
        { query: "x".repeat(MAX_QUERY_CHARS + 1), options: OPTIONS },
        "body.query",
      ],
      [
        "a query of 300000 characters",
        { query: "x".repeat(OVERSIZED_QUERY_CHARS), options: OPTIONS },
        "body.query",
      ],
      [
        "a duration of 9 seconds",
        { query: QUESTION, options: { durationSeconds: 9 } },
        "body.options.durationSeconds",
      ],
      [
        "a duration of 121 seconds",
        { query: QUESTION, options: { durationSeconds: 121 } },
        "body.options.durationSeconds",
      ],
    ],
  ],
  [
    "unknown and conflicting fields",
    [
      [
        "an unknown top-level field",
        { query: QUESTION, options: OPTIONS, creditsOverride: 0 },
        "body.creditsOverride",
      ],
      [
        "an unknown option",
        { query: QUESTION, options: { ...OPTIONS, priceOverride: 1 } },
        "body.options.priceOverride",
      ],
      [
        "both a topic and a query",
        { query: QUESTION, topicId: randomUUID(), options: OPTIONS },
        "body",
      ],
      ["neither a topic nor a query", { options: OPTIONS }, "body"],
    ],
  ],
  [
    "malformed options",
    [
      [
        "duplicate aspects",
        { query: QUESTION, options: { ...OPTIONS, aspects: ["16:9", "16:9"] } },
        "body.options",
      ],
      [
        "four aspects",
        { query: QUESTION, options: { ...OPTIONS, aspects: ["16:9", "9:16", "1:1", "16:9"] } },
        "body.options.aspects",
      ],
      ["a blank query", { query: "   ", options: OPTIONS }, "body.query"],
      [
        "burned-in subtitles without subtitles",
        { query: QUESTION, options: { ...OPTIONS, subtitles: false, burnInSubtitles: true } },
        "body.options",
      ],
    ],
  ],
];

test.describe.configure({ timeout: 180000 });

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(180000);
  await prepareBuiltinVoice(await playwright.request.newContext());
});

async function expectJobProblem(
  response: APIResponse,
  status: number,
  code: string,
): Promise<JobProblem> {
  const text = await response.text();
  expect(response.status(), text).toBe(status);
  expect(response.headers()["content-type"]).toBe(PROBLEM_JSON);
  const problem = JSON.parse(text) as JobProblem;
  expect(problem.code).toBe(code);
  return problem;
}

test("the sixth job request of a minute is limited with Retry-After and rate limit headers", async ({
  playwright,
}) => {
  const user = await Creator.signup(await playwright.request.newContext());
  const statuses: number[] = [];
  for (let attempt = 0; attempt < CREATE_LIMIT; attempt += 1) {
    statuses.push((await user.createJob(jobBody(QUESTION))).status());
  }

  const limited = await user.createJob(jobBody(QUESTION));

  expect(statuses).toEqual(Array.from({ length: CREATE_LIMIT }, () => 402));
  const problem = await expectJobProblem(limited, 429, "rate_limited");
  expect(problem.status).toBe(429);
  expect(Number(limited.headers()["retry-after"])).toBeGreaterThanOrEqual(1);
  expect(Number(limited.headers()["retry-after"])).toBeLessThanOrEqual(60);
  expect(limited.headers()["ratelimit-limit"]).toBe(String(CREATE_LIMIT));
  expect(limited.headers()["ratelimit-remaining"]).toBe("0");
  expect(limited.headers()["ratelimit-reset"]).toBeDefined();
  expect((await user.jobs()).items).toEqual([]);
});

test("a user who exhausted the job creation limit does not limit another user", async ({
  playwright,
}) => {
  const request = await playwright.request.newContext();
  const exhausted = await Creator.signup(request);
  for (let attempt = 0; attempt <= CREATE_LIMIT; attempt += 1) {
    await exhausted.createJob(jobBody(QUESTION));
  }
  const other = await Creator.signup(request);

  const response = await other.createJob(jobBody(QUESTION));

  expect(response.status()).toBe(402);
});

test("a third active job is refused with too_many_active_jobs and reserves nothing", async ({
  playwright,
}) => {
  const user = await Creator.funded(await playwright.request.newContext());
  const first = await user.startJob(QUESTION);
  const second = await user.startJob(QUESTION);

  const third = await user.createJob(jobBody(QUESTION));
  const problem = await expectJobProblem(third, 409, "too_many_active_jobs");
  const wallet = await user.session.wallet();
  const listed = await user.jobs("?limit=100");

  expect(problem.limit).toBe(MAX_ACTIVE_JOBS);
  expect(wallet.reserved).toBe(first.creditsReserved + second.creditsReserved);
  expect(listed.items).toHaveLength(MAX_ACTIVE_JOBS);

  expect((await user.cancel(first.id)).status()).toBe(202);
  await user.waitForJob(first.id, ["cancelled"]);
  const fourth = await user.startJob(QUESTION);
  await expect
    .poll(async () => (await user.session.wallet()).reserved, { timeout: 30000 })
    .toBe(second.creditsReserved + fourth.creditsReserved);
});

test("a wallet that cannot cover the video is refused with insufficient_credits and stays unchanged", async ({
  playwright,
}) => {
  const user = await Creator.funded(await playwright.request.newContext(), "pack_starter");
  const options = { durationSeconds: 120, aspects: ["16:9", "9:16", "1:1"] };
  const estimate = await user.estimate(options);
  expect(estimate.affordable).toBe(false);
  const before = await user.session.wallet();

  const problem = await expectJobProblem(
    await user.createJob({ query: QUESTION, options }),
    402,
    "insufficient_credits",
  );
  const after = await user.session.wallet();

  expect(problem.available).toBe(estimate.availableCredits);
  expect(problem.required).toBe(estimate.credits);
  expect(problem.shortfall).toBe(estimate.credits - estimate.availableCredits);
  expect(after).toEqual(before);
  expect((await user.jobs()).items).toEqual([]);
});

test("an empty wallet is refused with insufficient_credits and no job exists afterwards", async ({
  playwright,
}) => {
  const user = await Creator.signup(await playwright.request.newContext());

  const problem = await expectJobProblem(
    await user.createJob(jobBody(QUESTION)),
    402,
    "insufficient_credits",
  );

  expect(problem.available).toBe(0);
  expect(problem.required).toBeGreaterThan(0);
  expect(problem.shortfall).toBe(problem.required);
  expect((await user.session.wallet()).reserved).toBe(0);
  expect((await user.jobs()).items).toEqual([]);
});

test("a repeated request with the same key and body replays the first job", async ({
  playwright,
}) => {
  const user = await Creator.funded(await playwright.request.newContext());
  const key = randomUUID();
  const body = jobBody(QUESTION);

  const first = await user.createJob(body, key);
  const second = await user.createJob(body, key);
  const created = (await first.json()) as { id: string; creditsReserved: number };

  expect(first.status(), await first.text()).toBe(202);
  expect(first.headers()["idempotent-replayed"]).toBeUndefined();
  expect(second.status()).toBe(202);
  expect(second.headers()["idempotent-replayed"]).toBe("true");
  expect(second.headers()["location"]).toBe(first.headers()["location"]);
  expect(((await second.json()) as { id: string }).id).toBe(created.id);
  expect((await user.jobs()).items).toHaveLength(1);
  expect((await user.session.wallet()).reserved).toBe(created.creditsReserved);
});

test("the same key with a different body is a conflict and creates nothing", async ({
  playwright,
}) => {
  const user = await Creator.funded(await playwright.request.newContext());
  const key = randomUUID();
  const first = await user.createJob(jobBody(QUESTION), key);

  const reused = await user.createJob(jobBody("Why is the sky blue?"), key);

  expect(first.status()).toBe(202);
  await expectJobProblem(reused, 409, "idempotency_key_reused");
  expect((await user.jobs()).items).toHaveLength(1);
});

test("the idempotency key is required and must be well formed", async ({ playwright }) => {
  const user = await Creator.funded(await playwright.request.newContext());

  const missing = await user.createJob(jobBody(QUESTION), null);
  const invalid = await user.call("POST", "/v1/jobs", jobBody(QUESTION), {
    "Idempotency-Key": "has spaces in it",
  });

  await expectJobProblem(missing, 400, "idempotency_key_required");
  await expectJobProblem(invalid, 400, "idempotency_key_invalid");
  expect((await user.jobs()).items).toEqual([]);
  expect((await user.session.wallet()).reserved).toBe(0);
});

test("concurrent requests with one key create exactly one job", async ({ playwright }) => {
  const user = await Creator.funded(await playwright.request.newContext());
  const key = randomUUID();

  const responses = await Promise.all(
    Array.from({ length: CREATE_LIMIT }, () => user.createJob(jobBody(QUESTION), key)),
  );

  const accepted = responses.filter((response) => response.status() === 202);
  const inFlight = responses.filter((response) => response.status() === 409);
  expect(accepted.length).toBeGreaterThanOrEqual(1);
  expect(accepted.length + inFlight.length).toBe(responses.length);
  const ids = new Set(
    await Promise.all(
      accepted.map(async (response) => ((await response.json()) as { id: string }).id),
    ),
  );
  expect(ids.size).toBe(1);
  expect((await user.jobs()).items).toHaveLength(1);
});

for (const [group, bodies] of INVALID_BODIES) {
  test.describe(`invalid request bodies: ${group}`, () => {
    let user: Creator;

    test.beforeAll(async ({ playwright }) => {
      user = await Creator.signup(await playwright.request.newContext());
    });

    for (const [label, body, field] of bodies) {
      test(`${label} is rejected with 422 and a field error`, async () => {
        const response = await user.createJob(body);
        const problem = await expectJobProblem(response, 422, "validation_failed");

        expect(problem.errors?.map((error) => error.field).join(" ")).toContain(field);
        expect(JSON.stringify(problem).length).toBeLessThan(4000);
        expect((await user.jobs()).items).toEqual([]);
      });
    }
  });
}

test("durations of 10 and 120 seconds are accepted and 9 and 121 are not", async ({
  playwright,
}) => {
  const user = await Creator.signup(await playwright.request.newContext());

  const accepted = await Promise.all(
    [10, 120].map((durationSeconds) => user.estimate({ durationSeconds })),
  );
  const rejected = await Promise.all(
    [9, 121].map((durationSeconds) =>
      user.call("POST", "/v1/jobs/estimate", { options: { durationSeconds } }),
    ),
  );

  expect(accepted.map((estimate) => estimate.seconds)).toEqual([10, 120]);
  expect(rejected.map((response) => response.status())).toEqual([422, 422]);
});

test("a query at the 2000 character limit is accepted", async ({ playwright }) => {
  const user = await Creator.funded(await playwright.request.newContext());

  const job = await user.startJob(BOUNDARY_QUERY);

  expect(BOUNDARY_QUERY).toHaveLength(MAX_QUERY_CHARS);
  expect(job.query).toBe(BOUNDARY_QUERY);
});

test("the sixth concurrent event stream of a user is refused with too_many_streams", async ({
  playwright,
}) => {
  const user = await Creator.funded(await playwright.request.newContext());
  const job = await user.awaitingApproval();
  const streams: EventStream[] = [];

  try {
    for (let index = 0; index < STREAM_CAP; index += 1) {
      const stream = await user.openEvents(job.id);
      streams.push(stream);
      expect(stream.status).toBe(200);
    }
    await expectJobProblem(await user.events(job.id), 429, "too_many_streams");

    streams.pop()?.close();
    await expect
      .poll(
        async () => {
          const retry = await user.openEvents(job.id);
          if (retry.status === 200) streams.push(retry);
          else retry.close();
          return retry.status;
        },
        { timeout: 45000, intervals: [1000, 2000] },
      )
      .toBe(200);
  } finally {
    for (const stream of streams) stream.close();
  }
});

test("the stream cap of one user does not stop another user from following a job", async ({
  playwright,
}) => {
  const request = await playwright.request.newContext();
  const busy = await Creator.funded(request);
  const calm = await Creator.funded(request);
  const busyJob = await busy.awaitingApproval();
  const calmJob = await calm.awaitingApproval();
  const streams: EventStream[] = [];

  try {
    for (let index = 0; index < STREAM_CAP; index += 1) {
      streams.push(await busy.openEvents(busyJob.id));
    }
    const calmStream = await calm.openEvents(calmJob.id);
    streams.push(calmStream);

    expect(calmStream.status).toBe(200);
  } finally {
    for (const stream of streams) stream.close();
  }
});
