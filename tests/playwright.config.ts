import { defineConfig, devices } from "@playwright/test";

const webBaseUrl = process.env["WEB_BASE_URL"] ?? "http://localhost:3000";
const apiBaseUrl = process.env["API_BASE_URL"] ?? "http://localhost:8000";
const isCi = Boolean(process.env["CI"]);

export default defineConfig({
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: isCi ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "e2e",
      testDir: "./e2e",
      use: { ...devices["Desktop Chrome"], baseURL: webBaseUrl },
    },
    {
      name: "security",
      testDir: "./security/api",
      use: { baseURL: apiBaseUrl },
    },
  ],
});
