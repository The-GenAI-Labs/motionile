import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const env = {
  ...process.env,
  NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000",
};

for (const [module, args] of [
  ["next/dist/bin/next", ["typegen"]],
  ["typescript/bin/tsc", ["--noEmit"]],
]) {
  const result = spawnSync(process.execPath, [require.resolve(module), ...args], {
    env,
    stdio: "inherit",
  });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
