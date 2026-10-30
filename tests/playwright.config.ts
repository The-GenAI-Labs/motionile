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
      testIgnore: [
        "auth/**/*.spec.ts",
        "billing/**/*.spec.ts",
        "generation/**/*.spec.ts",
        "media/**/*.spec.ts",
      ],
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
      name: "billing-browser",
      testDir: "./e2e/billing",
      timeout: 120000,
      workers: 1,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: process.env["AUTH_WEB_BASE_URL"] ?? "https://localhost:3443",
        ignoreHTTPSErrors: true,
      },
    },
    {
      name: "media-browser",
      testDir: "./e2e/media",
      timeout: 600000,
      workers: 1,
      expect: { timeout: 15000 },
      use: {
        ...devices["Desktop Chrome"],
        baseURL: process.env["AUTH_WEB_BASE_URL"] ?? "https://localhost:3443",
        ignoreHTTPSErrors: true,
      },
    },
    {
      name: "generation-browser",
      testDir: "./e2e/generation",
      timeout: 900000,
      workers: 1,
      expect: { timeout: 15000 },
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
      testIgnore: [
        "media-cdn-scope.spec.ts",
        "media-delivery-render.spec.ts",
        "share-links.spec.ts",
        "storyboard-edit-injection.spec.ts",
      ],
      use: { baseURL: apiBaseUrl },
    },
    {
      name: "security-cdn",
      testDir: "./security/api",
      testMatch: "media-cdn-scope.spec.ts",
      use: { baseURL: apiBaseUrl },
    },
    {
      name: "security-render",
      testDir: "./security/api",
      testMatch: [
        "media-delivery-render.spec.ts",
        "share-links.spec.ts",
        "storyboard-edit-injection.spec.ts",
      ],
      timeout: 900000,
      use: { baseURL: apiBaseUrl },
    },
  ],
});
