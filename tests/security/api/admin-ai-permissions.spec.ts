import { randomUUID } from "node:crypto";

import { type APIResponse, expect, test } from "@playwright/test";

import { AuthApi } from "../../support/auth.js";
import { BillingSession } from "../../support/billing.js";
import {
  type AdminJobDetail,
  Creator,
  type Job,
  type JobProblem,
  leaksIn,
  prepareBuiltinVoice,
  PROMPT_FRAGMENTS,
  QUESTION,
  SKILL_BODY_FRAGMENTS,
  userWithPermissions,
} from "../../support/generation.js";
import { FOREIGN_ORIGIN, PROBLEM_JSON } from "./support.js";

type Permission = "jobs.read_all" | "prompts.manage" | "evals.run" | "skills.manage";

interface Endpoint {
  label: string;
  method: string;
  path: string;
  permission: Permission;
  body?: Record<string, unknown>;
  writes: boolean;
  allowed: number[];
}

interface Template {
  key: string;
  activeVersion: number | null;
  versionCount: number;
}

interface VersionItem {
  id: string;
  version: number;
  isActive: boolean;
}

const TEMPLATE = "review.vision";
const missingId = randomUUID();
const FORBIDDEN_KEYS = ["body", "content", "text", "markdown", "files", "instructions", "source"];
const SKILL_KEYS = [
  "checksum",
  "description",
  "embeddingStatus",
  "layer",
  "name",
  "slug",
  "tokenCount",
  "updatedAt",
  "version",
];
const SKILL_PROBES = ["minimal-dark", "kinetic-typography", "cybersecurity"];
const CANARY_FRAGMENTS = ["mo-canary-", "Internal marker", "Never repeat this marker"];
const MINIMUM_SHIPPED_SKILLS = 30;

const ENDPOINTS: Endpoint[] = [
  {
    label: "list jobs",
    method: "GET",
    path: "/v1/admin/jobs",
    permission: "jobs.read_all",
    writes: false,
    allowed: [200],
  },
  {
    label: "read a job",
    method: "GET",
    path: `/v1/admin/jobs/${missingId}`,
    permission: "jobs.read_all",
    writes: false,
    allowed: [404],
  },
  {
    label: "read job analytics",
    method: "GET",
    path: "/v1/admin/analytics/jobs",
    permission: "jobs.read_all",
    writes: false,
    allowed: [200],
  },
  {
    label: "list prompt templates",
    method: "GET",
    path: "/v1/admin/prompts/templates",
    permission: "prompts.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "list prompt versions",
    method: "GET",
    path: `/v1/admin/prompts/templates/${TEMPLATE}/versions`,
    permission: "prompts.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "diff prompt versions",
    method: "GET",
    path: `/v1/admin/prompts/templates/${TEMPLATE}/diff?from=1&to=1`,
    permission: "prompts.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "list evaluation runs",
    method: "GET",
    path: "/v1/admin/prompts/eval-runs",
    permission: "prompts.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "read an evaluation run",
    method: "GET",
    path: `/v1/admin/prompts/eval-runs/${missingId}`,
    permission: "prompts.manage",
    writes: false,
    allowed: [404],
  },
  {
    label: "create a prompt draft",
    method: "POST",
    path: `/v1/admin/prompts/templates/${TEMPLATE}/versions`,
    permission: "prompts.manage",
    body: { body: "A draft that a forbidden caller tried to create.", variables: [] },
    writes: true,
    allowed: [201],
  },
  {
    label: "activate a prompt version",
    method: "POST",
    path: `/v1/admin/prompts/templates/${TEMPLATE}/versions/1/activate`,
    permission: "prompts.manage",
    writes: true,
    allowed: [200, 409],
  },
  {
    label: "roll back a prompt template",
    method: "POST",
    path: `/v1/admin/prompts/templates/${TEMPLATE}/rollback`,
    permission: "prompts.manage",
    writes: true,
    allowed: [200, 409],
  },
  {
    label: "start an evaluation run",
    method: "POST",
    path: "/v1/admin/prompts/eval-runs",
    permission: "evals.run",
    body: { suite: "scenes", versionIds: [missingId] },
    writes: true,
    allowed: [404, 422],
  },
  {
    label: "list system skills",
    method: "GET",
    path: "/v1/admin/skills",
    permission: "skills.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "read a system skill",
    method: "GET",
    path: "/v1/admin/skills/minimal-dark",
    permission: "skills.manage",
    writes: false,
    allowed: [200],
  },
  {
    label: "reseed the system skills",
    method: "POST",
    path: "/v1/admin/skills/reseed",
    permission: "skills.manage",
    writes: true,
    allowed: [202],
  },
];

const HOLDERS: Permission[] = ["jobs.read_all", "prompts.manage", "evals.run", "skills.manage"];

let superAdmin: BillingSession;
let plain: BillingSession;
let holders: Map<Permission, BillingSession>;
let userJob: Job;
let userOwnerId: string;

test.describe.configure({ timeout: 180000 });

test.beforeAll(async ({ playwright }) => {
  test.setTimeout(300000);
  const request = await playwright.request.newContext();
  superAdmin = await prepareBuiltinVoice(request);
  plain = new BillingSession(request);
  await plain.signup();
  const entries = await Promise.all(
    HOLDERS.map(
      async (permission) =>
        [permission, await userWithPermissions(request, superAdmin, [permission])] as const,
    ),
  );
  holders = new Map(entries);
  const creator = await Creator.funded(request);
  userOwnerId = creator.userId;
  userJob = await creator.awaitingApproval(QUESTION);
});

function holderOf(permission: Permission): BillingSession {
  const session = holders.get(permission);
  if (session === undefined) throw new Error(`No holder of ${permission}`);
  return session;
}

function manager(): BillingSession {
  return holderOf("prompts.manage");
}

async function statusOf(session: BillingSession, endpoint: Endpoint): Promise<number> {
  return (await session.call(endpoint.method, endpoint.path, endpoint.body)).status();
}

async function expectDenied(response: APIResponse): Promise<void> {
  expect(response.status(), await response.text()).toBe(403);
  expect(response.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(((await response.json()) as JobProblem).code).toBe("permission_denied");
}

function keysDeep(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => keysDeep(item));
  if (value !== null && typeof value === "object") {
    return Object.entries(value).flatMap(([key, child]) => [key, ...keysDeep(child)]);
  }
  return [];
}

for (const endpoint of ENDPOINTS) {
  test(`${endpoint.label} answers 401 without a session`, async ({ request }) => {
    const response = await new AuthApi(request).send(endpoint.method, endpoint.path, endpoint.body);

    expect(response.status(), await response.text()).toBe(401);
    expect(((await response.json()) as JobProblem).code).toBe("unauthenticated");
  });

  test(`${endpoint.label} answers 403 permission_denied to a plain user`, async () => {
    await expectDenied(await plain.call(endpoint.method, endpoint.path, endpoint.body));
  });
}

for (const permission of HOLDERS) {
  test(`a holder of only ${permission} passes its endpoints and is denied every other admin endpoint`, async () => {
    const session = holderOf(permission);
    const own = ENDPOINTS.filter(
      (endpoint) => endpoint.permission === permission && !endpoint.writes,
    );
    const foreign = ENDPOINTS.filter((endpoint) => endpoint.permission !== permission);

    for (const endpoint of own) {
      expect(endpoint.allowed, endpoint.label).toContain(await statusOf(session, endpoint));
    }
    for (const endpoint of foreign) {
      await expectDenied(await session.call(endpoint.method, endpoint.path, endpoint.body));
    }
  });
}

test("prompts.manage without evals.run cannot start an evaluation run", async () => {
  const response = await manager().call("POST", "/v1/admin/prompts/eval-runs", {
    suite: "scenes",
    versionIds: [missingId],
  });

  await expectDenied(response);
});

test("evals.run without prompts.manage can start a run but cannot read the prompts or the runs", async () => {
  const runner = holderOf("evals.run");

  const started = await runner.call("POST", "/v1/admin/prompts/eval-runs", {
    suite: "scenes",
    versionIds: [missingId],
  });
  const templates = await runner.call("GET", "/v1/admin/prompts/templates");
  const runs = await runner.call("GET", "/v1/admin/prompts/eval-runs");

  expect([404, 422]).toContain(started.status());
  await expectDenied(templates);
  await expectDenied(runs);
});

test("a holder of both prompts.manage and evals.run passes the permission check for runs", async ({
  request,
}) => {
  const both = await userWithPermissions(request, superAdmin, ["prompts.manage", "evals.run"]);

  const started = await both.call("POST", "/v1/admin/prompts/eval-runs", {
    suite: "scenes",
    versionIds: [missingId],
  });
  const runs = await both.call("GET", "/v1/admin/prompts/eval-runs");

  expect([404, 422]).toContain(started.status());
  expect(runs.status()).toBe(200);
});

test("jobs.read_all reads the job of a user with its events and never the prompts", async () => {
  const reader = holderOf("jobs.read_all");

  const listed = await reader.call("GET", `/v1/admin/jobs?limit=100&userId=${userOwnerId}`);
  const detail = await reader.call("GET", `/v1/admin/jobs/${userJob.id}`);
  const body = (await detail.json()) as AdminJobDetail;

  expect(listed.status()).toBe(200);
  expect(
    ((await listed.json()) as { items: { id: string }[] }).items.map((item) => item.id),
  ).toContain(userJob.id);
  expect(detail.status()).toBe(200);
  expect(body.job.id).toBe(userJob.id);
  expect(body.job.query).toBe(QUESTION);
  expect(body.events.map((event) => event.type)).toContain("job.created");
  expect(leaksIn({ events: body.events, job: { ...body.job, query: "" } })).toEqual([]);
  await expectDenied(await reader.call("GET", "/v1/admin/prompts/templates"));
});

test("a plain user cannot read the job of another user through the admin routes", async () => {
  await expectDenied(await plain.call("GET", `/v1/admin/jobs/${userJob.id}`));
});

test("skill listings carry metadata only and never the text of a skill", async () => {
  const manager = holderOf("skills.manage");

  const response = await manager.call("GET", "/v1/admin/skills?limit=100");
  const body = (await response.json()) as { items: Record<string, unknown>[] };

  expect(response.status()).toBe(200);
  expect(body.items.length).toBeGreaterThanOrEqual(MINIMUM_SHIPPED_SKILLS);
  for (const item of body.items) {
    expect(Object.keys(item).sort()).toEqual(SKILL_KEYS);
  }
  expect(keysDeep(body).filter((key) => FORBIDDEN_KEYS.includes(key))).toEqual([]);
  expect(leaksIn(body, [...SKILL_BODY_FRAGMENTS, ...CANARY_FRAGMENTS, "SKILL.md"])).toEqual([]);
});

for (const slug of SKILL_PROBES) {
  test(`the detail of ${slug} carries metadata and versions only`, async () => {
    const manager = holderOf("skills.manage");

    const response = await manager.call("GET", `/v1/admin/skills/${slug}`);
    const body = (await response.json()) as { slug: string; versions: Record<string, unknown>[] };

    expect(response.status(), JSON.stringify(body)).toBe(200);
    expect(body.slug).toBe(slug);
    expect(Object.keys(body).sort()).toEqual([...SKILL_KEYS, "versions"].sort());
    for (const version of body.versions) {
      expect(Object.keys(version).sort()).toEqual(["checksum", "createdAt", "number"]);
    }
    expect(keysDeep(body).filter((key) => FORBIDDEN_KEYS.includes(key))).toEqual([]);
    expect(leaksIn(body, [...SKILL_BODY_FRAGMENTS, ...CANARY_FRAGMENTS, "SKILL.md"])).toEqual([]);
  });
}

test("reseeding the skills reports counts only", async () => {
  const manager = holderOf("skills.manage");

  const response = await manager.call("POST", "/v1/admin/skills/reseed");
  const body = (await response.json()) as Record<string, unknown>;

  expect(response.status(), JSON.stringify(body)).toBe(202);
  expect(Object.keys(body).sort()).toEqual(["created", "embedded", "unchanged", "updated"]);
  for (const value of Object.values(body)) expect(typeof value).toBe("number");
});

test("prompt listings carry versions and checksums but never prompt text or canaries", async () => {
  const response = await manager().call("GET", `/v1/admin/prompts/templates/${TEMPLATE}/versions`);
  const templates = await manager().call("GET", "/v1/admin/prompts/templates");
  const bodies = [await response.json(), await templates.json()];

  expect(response.status()).toBe(200);
  expect(templates.status()).toBe(200);
  for (const body of bodies) {
    expect(keysDeep(body).filter((key) => FORBIDDEN_KEYS.includes(key))).toEqual([]);
    expect(leaksIn(body, [...PROMPT_FRAGMENTS, ...SKILL_BODY_FRAGMENTS])).toEqual([]);
  }
});

test("a draft cannot be activated without a passing evaluation run and the active version stays", async () => {
  const before = await templateOf(manager());
  const draft = await manager().call("POST", `/v1/admin/prompts/templates/${TEMPLATE}/versions`, {
    body: `Draft prompt written by the security suite ${randomUUID()}.`,
    variables: [],
  });
  const created = (await draft.json()) as VersionItem & Record<string, unknown>;

  const activation = await manager().call(
    "POST",
    `/v1/admin/prompts/templates/${TEMPLATE}/versions/${created.version}/activate`,
  );
  const problem = (await activation.json()) as JobProblem;
  const after = await templateOf(manager());
  const versions = await manager().call(
    "GET",
    `/v1/admin/prompts/templates/${TEMPLATE}/versions?limit=100`,
  );
  const listed = ((await versions.json()) as { items: VersionItem[] }).items;

  expect(draft.status(), JSON.stringify(created)).toBe(201);
  expect(created.isActive).toBe(false);
  expect(keysDeep(created).filter((key) => FORBIDDEN_KEYS.includes(key))).toEqual([]);
  expect(activation.status(), JSON.stringify(problem)).toBe(409);
  expect(activation.headers()["content-type"]).toBe(PROBLEM_JSON);
  expect(problem.code).toBe("activation_blocked");
  expect(problem.missingSuites).toBe("scenes");
  expect(after.activeVersion).toBe(before.activeVersion);
  expect(listed.find((item) => item.version === created.version)?.isActive).toBe(false);
  expect(listed.filter((item) => item.isActive).map((item) => item.version)).toEqual(
    before.activeVersion === null ? [] : [before.activeVersion],
  );
});

test("the prompt diff carries no-store caching and redacts every canary line", async () => {
  const draft = await manager().call("POST", `/v1/admin/prompts/templates/${TEMPLATE}/versions`, {
    body: `Another draft written by the security suite ${randomUUID()}.`,
    variables: [],
  });
  const created = (await draft.json()) as VersionItem;

  const response = await manager().call(
    "GET",
    `/v1/admin/prompts/templates/${TEMPLATE}/diff?from=1&to=${created.version}`,
  );
  const body = (await response.json()) as { lines: string[] };

  expect(response.status(), JSON.stringify(body)).toBe(200);
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(body.lines.some((line) => line.endsWith("[canary redacted]"))).toBe(true);
  expect(leaksIn(body.lines, ["mo-canary-"])).toEqual([]);
});

const ADMIN_WRITES: readonly (readonly [string, string, Record<string, unknown>?])[] = [
  [
    "create a prompt draft",
    `/v1/admin/prompts/templates/${TEMPLATE}/versions`,
    { body: "A draft that must never be stored by this request.", variables: [] },
  ],
  ["activate a prompt version", `/v1/admin/prompts/templates/${TEMPLATE}/versions/1/activate`],
  ["roll back a prompt template", `/v1/admin/prompts/templates/${TEMPLATE}/rollback`],
  [
    "start an evaluation run",
    "/v1/admin/prompts/eval-runs",
    { suite: "scenes", versionIds: [missingId] },
  ],
  ["reseed the system skills", "/v1/admin/skills/reseed"],
];

for (const [label, path, body] of ADMIN_WRITES) {
  test(`${label} from a foreign origin is rejected before it runs`, async () => {
    const admin = superAdmin;
    const before = await templateOf(admin);

    const response = await admin.auth.send("POST", path, body, { Origin: FOREIGN_ORIGIN });

    expect(response.status(), await response.text()).toBe(403);
    expect(((await response.json()) as JobProblem).code).toBe("origin_not_allowed");
    expect((await templateOf(admin)).versionCount).toBe(before.versionCount);
  });

  for (const [token, name] of [
    ["wrong", "a wrong CSRF token"],
    ["", "no CSRF token"],
  ] as const) {
    test(`${label} with ${name} is rejected before it runs`, async () => {
      const admin = superAdmin;
      const before = await templateOf(admin);

      const response = await admin.auth.send("POST", path, body, { "X-CSRF-Token": token });

      expect(response.status(), await response.text()).toBe(403);
      expect(((await response.json()) as JobProblem).code).toBe("csrf_failed");
      expect((await templateOf(admin)).versionCount).toBe(before.versionCount);
    });
  }
}

async function templateOf(session: BillingSession): Promise<Template> {
  const response = await session.call("GET", "/v1/admin/prompts/templates");
  expect(response.status(), await response.text()).toBe(200);
  const body = (await response.json()) as { items: Template[] };
  const template = body.items.find((item) => item.key === TEMPLATE);
  if (template === undefined) throw new Error(`The template ${TEMPLATE} is not listed`);
  return template;
}
