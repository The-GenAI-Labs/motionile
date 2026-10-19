import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

import type { APIRequestContext } from "@playwright/test";

import { BillingSession } from "./billing.js";

const run = promisify(execFile);
const repositoryRoot = fileURLToPath(new URL("../../", import.meta.url));
const GRANT_TIMEOUT_MS = 120000;

export async function grantRole(identifier: string, role: string): Promise<void> {
  await run(
    "docker",
    [
      "compose",
      "-f",
      "deploy/compose.yml",
      "-f",
      "deploy/compose.dev.yml",
      "exec",
      "-T",
      "api",
      "python",
      "-m",
      "motionile.scripts.grant_role",
      "--identifier",
      identifier,
      "--role",
      role,
    ],
    { cwd: repositoryRoot, timeout: GRANT_TIMEOUT_MS },
  );
}

export async function signupWithRole(
  request: APIRequestContext,
  role: string,
): Promise<BillingSession> {
  const session = new BillingSession(request);
  await session.signup();
  await grantRole(session.auth.email, role);
  return session;
}
