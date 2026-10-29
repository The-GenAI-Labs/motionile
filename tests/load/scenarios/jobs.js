import { check, sleep } from "k6";
import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";

import { api, headersOf, provisionAccount, send, signIn } from "../lib/session.js";
import { jobsLoadOptions, peakVirtualUsers } from "../thresholds.js";

const runId = Date.now().toString(36);
const QUESTION = "How does a hash map handle collisions?";
const JOB_BODY = { query: QUESTION, options: { durationSeconds: 20, reviewStoryboard: true } };
const POLLS = 3;
const POLL_PAUSE_SECONDS = 0.5;
const STREAM_SETTLE_SECONDS = 1;
const STREAM_TIMEOUT = "30s";
const REPLAY_EVERY = 4;
const MAX_BACKOFF_SECONDS = 10;
const ITERATION_PAUSE_SECONDS = 1;

const streamFirstByte = new Trend("stream_first_byte_ms", true);
const streamTotal = new Trend("stream_total_ms", true);
const streamsCompleted = new Counter("streams_completed");
const streamOpenErrors = new Rate("stream_open_errors");
const jobFlowErrors = new Rate("job_flow_errors");
const jobRejections = new Rate("job_rejections");

export const options = { ...jobsLoadOptions(), noCookiesReset: true };

let session = null;

export function setup() {
  const accounts = [];
  for (let index = 0; index < peakVirtualUsers(); index += 1) {
    accounts.push(provisionAccount(runId, index));
  }
  const probe = send(
    accounts[0].session,
    "POST",
    "/v1/jobs/estimate",
    { options: JOB_BODY.options },
    {
      name: "seed estimate",
    },
  );
  if (probe.status !== 200) {
    throw new Error(
      `The seeded account cannot estimate a video (${probe.status}): ${probe.body}. Ready a built-in voice before the run.`,
    );
  }
  return {
    accounts: accounts.map(({ identifier, password, index }) => ({ identifier, password, index })),
  };
}

function retryAfter(response) {
  const seconds = Number(response.headers["Retry-After"]);
  return Number.isFinite(seconds) && seconds > 0 ? Math.min(seconds, MAX_BACKOFF_SECONDS) : 2;
}

function createJob(key, name) {
  return send(session, "POST", "/v1/jobs", JOB_BODY, { name, headers: { "Idempotency-Key": key } });
}

function pollJob(job) {
  for (let poll = 0; poll < POLLS; poll += 1) {
    const read = send(session, "GET", `/v1/jobs/${job.id}`, undefined, { name: "get job" });
    const ok = check(read, {
      "job is readable": (response) => response.status === 200,
      "job keeps its id": (response) => response.json("id") === job.id,
    });
    jobFlowErrors.add(!ok);
    sleep(POLL_PAUSE_SECONDS);
  }
}

function cancelJob(job) {
  const cancelled = send(session, "POST", `/v1/jobs/${job.id}/cancel`, undefined, {
    name: "cancel job",
  });
  const ok = check(cancelled, { "job is cancelled": (response) => response.status === 202 });
  jobFlowErrors.add(!ok);
}

async function followAndCancel(job) {
  const pending = http.asyncRequest("GET", `${api}/v1/jobs/${job.id}/events`, null, {
    headers: headersOf(session, { Accept: "text/event-stream" }),
    redirects: 0,
    timeout: STREAM_TIMEOUT,
    tags: { name: "job event stream" },
  });
  sleep(STREAM_SETTLE_SECONDS);
  cancelJob(job);
  const stream = await pending;
  const opened = check(stream, {
    "stream opens": (response) => response.status === 200,
    "stream is server-sent events": (response) =>
      (response.headers["Content-Type"] || "").includes("text/event-stream"),
    "stream starts with a snapshot": (response) =>
      (response.body || "").includes("event: snapshot"),
    "stream ends with the cancellation": (response) =>
      (response.body || "").includes("job.cancelled"),
  });
  streamOpenErrors.add(stream.status !== 200);
  jobFlowErrors.add(!opened);
  if (stream.status !== 200) return;
  streamsCompleted.add(1);
  streamFirstByte.add(stream.timings.waiting);
  streamTotal.add(stream.timings.duration);
  const firstId = /^id: (.+)$/m.exec(stream.body || "");
  if (firstId) replayEvents(job, firstId[1]);
}

function replayEvents(job, lastEventId) {
  const replay = http.get(`${api}/v1/jobs/${job.id}/events`, {
    headers: headersOf(session, { Accept: "text/event-stream", "Last-Event-ID": lastEventId }),
    redirects: 0,
    timeout: STREAM_TIMEOUT,
    tags: { name: "replay job events" },
  });
  const ok = check(replay, {
    "replay succeeds": (response) => response.status === 200,
    "replay starts with a snapshot": (response) =>
      (response.body || "").includes("event: snapshot"),
  });
  jobFlowErrors.add(!ok);
}

function replayCreate(key, job) {
  const replayed = createJob(key, "replay create job");
  const ok = check(replayed, {
    "replayed create is accepted": (response) => response.status === 202,
    "replayed create is marked": (response) => response.headers["Idempotent-Replayed"] === "true",
    "replayed create returns the same job": (response) => response.json("id") === job.id,
  });
  jobFlowErrors.add(!ok);
}

function listJobs(job) {
  const listed = send(session, "GET", "/v1/jobs?limit=20", undefined, { name: "list jobs" });
  const ok = check(listed, {
    "job list is readable": (response) => response.status === 200,
    "job list holds the new job": (response) =>
      response.json("items").some((item) => item.id === job.id),
  });
  jobFlowErrors.add(!ok);
}

export default async function jobsFlow(data) {
  if (session === null) {
    session = signIn(data.accounts[(__VU - 1) % data.accounts.length]);
    if (session === null) return;
  }
  const key = `load-${runId}-${__VU}-${__ITER}`;
  const created = createJob(key, "create job");
  const rejected = created.status === 409 || created.status === 429;
  jobRejections.add(rejected);
  if (rejected) {
    sleep(retryAfter(created));
    return;
  }
  const accepted = check(created, { "job is accepted": (response) => response.status === 202 });
  jobFlowErrors.add(!accepted);
  if (!accepted) return;
  const job = created.json();

  if (__ITER % REPLAY_EVERY === 0) replayCreate(key, job);
  pollJob(job);
  if (__VU % 2 === 0) await followAndCancel(job);
  else cancelJob(job);
  listJobs(job);
  sleep(ITERATION_PAUSE_SECONDS);
}
