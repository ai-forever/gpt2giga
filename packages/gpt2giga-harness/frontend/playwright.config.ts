import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig, devices } from "@playwright/test";

const frontendDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(frontendDirectory, "../../..");
const qaDataDirectory = path.join(repositoryRoot, ".cache", "browser-qa-state");
const baseURL = "http://127.0.0.1:8091";

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: Boolean(process.env.CI),
  fullyParallel: false,
  outputDir: path.join(repositoryRoot, "test-results", "browser-qa"),
  reporter: process.env.CI ? "line" : "list",
  retries: process.env.CI ? 1 : 0,
  timeout: 30_000,
  workers: 1,
  use: {
    baseURL,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
      },
    },
    {
      name: "mobile-390x844",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: {
    command: [
      `GPT2GIGA_HARNESS_DATA_DIR="${qaDataDirectory}"`,
      `"${path.join(repositoryRoot, ".venv", "bin", "giga")}"`,
      "ui --no-start-worker --host 127.0.0.1 --port 8091",
    ].join(" "),
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    url: `${baseURL}/local-access`,
  },
});
