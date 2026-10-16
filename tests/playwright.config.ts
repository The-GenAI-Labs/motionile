import { defineConfig, devices } from "@playwright/test";

const webBaseUrl = process.env["WEB_BASE_URL"] ?? "http://localhost:3000";
const apiBaseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";
const isCi = Boolean(process.env["CI"]);

export default defineConfig({
  forbidOnly: isCi,
  retries: 0,
  reporter: isCi ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "e2e",
      testDir: "./e2e",
      use: { ...devices["Desktop Chrome"], baseURL: webBaseUrl },
      testIgnore: "auth/**/*.spec.ts",
    },
    {
      name: "auth-browser",
      testDir: "./e2e/auth",
      timeout: 120000,
      workers: 1,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: process.env["AUTH_WEB_BASE_URL"] ?? "https://localhost:3443",
        ignoreHTTPSErrors: true,
      },
    },
    {
      name: "smoke",
      testDir: "./e2e",
      testMatch: "smoke.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: webBaseUrl },
    },
    {
      name: "security",
      testDir: "./security/api",
      use: { baseURL: apiBaseUrl },
    },
  ],
});
