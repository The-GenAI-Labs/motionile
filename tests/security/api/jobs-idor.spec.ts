import { randomUUID } from "node:crypto";

import { type APIResponse, expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";
import {
  Creator,
  type Job,
  type JobProblem,
  prepareBuiltinVoice,
  type StoryboardView,
  withoutVolatileFields,
} from "../../support/generation.js";
import { PROBLEM_JSON } from "./support.js";

type Attempt = readonly [
  label: string,
  run: (user: Creator, jobId: string) => Promise<APIResponse>,
];

const ATTEMPTS: Attempt[] = [
  ["read the job", (user, id) => user.call("GET", `/v1/jobs/${id}`)],
  ["read the storyboard", (user, id) => user.call("GET", `/v1/jobs/${id}/storyboard`)],
  [
    "edit the storyboard",
    (user, id) =>
      user.call("PUT", `/v1/jobs/${id}/storyboard`, {
        expectedVersion: 1,
        content: ownerStoryboard.content,
      }),
  ],
  ["regenerate the storyboard", (user, id) => user.regenerate(id, "Make the video shorter")],
  ["approve the storyboard", (user, id) => user.approve(id, 1)],
  ["cancel the job", (user, id) => user.cancel(id)],
  ["revise the job", (user, id) => user.revise(id, "Use a calmer tone")],
  ["delete the job", (user, id) => user.remove(id)],
  ["open the event stream", (user, id) => user.events(id)],
  ["share the job", (user, id) => user.share(id)],
  ["unshare the job", (user, id) => user.unshare(id)],
];

const ANONYMOUS_REQUESTS: readonly (readonly [string, string, Record<string, unknown>?])[] = [
  ["GET", "/v1/jobs"],
  ["POST", "/v1/jobs", { query: "anything", options: { durationSeconds: 20 } }],
  ["POST", "/v1/jobs/estimate", { options: { durationSeconds: 20 } }],
  ["GET", "/v1/library"],
  ["GET", "/v1/jobs/{id}"],
  ["GET", "/v1/jobs/{id}/storyboard"],
  ["PUT", "/v1/jobs/{id}/storyboard", { expectedVersion: 1, content: {} }],
  ["POST", "/v1/jobs/{id}/storyboard/regenerate", { instructions: "Shorter" }],
  ["POST", "/v1/jobs/{id}/approve", { expectedVersion: 1 }],
  ["POST", "/v1/jobs/{id}/cancel"],
  ["POST", "/v1/jobs/{id}/revise", { instructions: "Calmer" }],
  ["DELETE", "/v1/jobs/{id}"],
  ["GET", "/v1/jobs/{id}/events"],
  ["POST", "/v1/jobs/{id}/share", { aspect: "16:9" }],
  ["DELETE", "/v1/jobs/{id}/share"],
];

let owner: Creator;
let stranger: Creator;
let ownerJob: Job;
let ownerStoryboard: StoryboardView;
const missingId = randomUUID();

async function problemOf(response: APIResponse): Promise<JobProblem> {
  return (await response.json()) as JobProblem;
}

test.describe.configure({ mode: "serial", timeout: 180000 });

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(240000);
  const request = await playwright.request.newContext();
  await prepareBuiltinVoice(request);
  owner = await Creator.funded(request);
  stranger = await Creator.signup(request);
  ownerJob = await owner.awaitingApproval();
  ownerStoryboard = await owner.storyboardView(ownerJob.id);
});

test("the owner reads the job, its storyboard and opens its event stream", async () => {
  const read = await owner.fetchJob(ownerJob.id);
  const stream = await owner.openEvents(ownerJob.id);

  expect(read.id).toBe(ownerJob.id);
  expect(ownerStoryboard.version).toBe(1);
  expect(stream.status).toBe(200);
  expect(stream.headers["content-type"]).toContain("text/event-stream");
  await stream.received(/event: snapshot/);
  stream.close();
});

for (const [label, run] of ATTEMPTS) {
  test(`another user cannot ${label} and gets the same 404 as for a missing job`, async () => {
    const foreign = await run(stranger, ownerJob.id);
    const missing = await run(stranger, missingId);

    expect(foreign.status(), await foreign.text()).toBe(404);
    expect(missing.status()).toBe(404);
    expect(foreign.headers()["content-type"]).toBe(PROBLEM_JSON);
    const foreignProblem = await problemOf(foreign);
    expect(foreignProblem.code).toBe("job_not_found");
    expect(withoutVolatileFields(foreignProblem)).toEqual(
      withoutVolatileFields(await problemOf(missing)),
    );
    expect(Object.keys(foreignProblem).sort()).toEqual(
      Object.keys(await problemOf(missing)).sort(),
    );
    expect(await foreign.text()).not.toContain(ownerJob.query);
  });
}

test("the owner's job is untouched by every attempt of the other user", async () => {
  const after = await owner.fetchJob(ownerJob.id);
  const storyboard = await owner.storyboardView(ownerJob.id);

  expect(after.status).toBe("awaiting_approval");
  expect(after.cancelRequestedAt).toBeNull();
  expect(after.updatedAt).toBe(ownerJob.updatedAt);
  expect(storyboard.version).toBe(ownerStoryboard.version);
  expect(storyboard.approved).toBe(false);
  expect(storyboard.content).toEqual(ownerStoryboard.content);
});

test("the job list of another user never contains the job and the owner's list does", async () => {
  const strangerJobs = await stranger.jobs("?limit=100");
  const strangerFiltered = await stranger.jobs("?status=awaiting_approval&limit=100");
  const ownerJobs = await owner.jobs("?limit=100");

  expect(strangerJobs.items).toEqual([]);
  expect(strangerFiltered.items).toEqual([]);
  expect(ownerJobs.items.map((item) => item.id)).toContain(ownerJob.id);
});

test("the library of another user never lists the job", async () => {
  const library = await stranger.library("?limit=100");

  expect(library.items.map((item) => item.jobId)).not.toContain(ownerJob.id);
  expect(JSON.stringify(library)).not.toContain(ownerJob.id);
});

test("a job id that is not a UUID answers 422, never a lookup", async () => {
  const response = await stranger.call("GET", "/v1/jobs/not-a-uuid");

  expect(response.status()).toBe(422);
  expect(((await response.json()) as JobProblem).code).toBe("validation_failed");
});

for (const [method, template, body] of ANONYMOUS_REQUESTS) {
  const path = template.replace("{id}", missingId);
  test(`${method} ${template} answers 401 without a session`, async ({ request }) => {
    const anonymous = new AuthApi(request);

    const response = await anonymous.send(method, path, body, {
      "Idempotency-Key": randomUUID(),
    });

    expect(response.status(), await response.text()).toBe(401);
    expect(response.headers()["content-type"]).toBe(PROBLEM_JSON);
    expect(((await response.json()) as JobProblem).code).toBe("unauthenticated");
  });
}

test("a tampered access token cannot read the job", async ({ request }) => {
  const tampered = new AuthApi(request);
  await tampered.signup();
  const [header = "", payload = ""] = (tampered.cookies.get("__Secure-mo_at") ?? "").split(".");
  tampered.cookies.set("__Secure-mo_at", `${header}.${payload}.AAAAAAAA`);

  const response = await tampered.send("GET", `/v1/jobs/${ownerJob.id}`);

  expect(response.status()).toBe(401);
});
