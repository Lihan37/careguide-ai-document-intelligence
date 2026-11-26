import { defineConfig } from "@playwright/test";
import path from 'node:path';
const context = require('./e2e/context.cjs');
export default defineConfig({
  testDir: "./e2e",
  globalTeardown: './e2e/teardown.cjs',
  workers: 1,
  timeout: 90000,
  outputDir: path.join(context.root, 'artifacts/test-results'),
  use: {
    baseURL: context.web_url,
    extraHTTPHeaders: { 'X-CareGuide-Environment': 'test', 'X-CareGuide-Run': context.run_id },
    timezoneId: "Asia/Dhaka",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  reporter: [
    ["list"],
    ["json", { outputFile: path.join(context.root, 'artifacts/results.json') }],
  ],
  webServer: [
    { command: 'node e2e/serve-api.cjs', url: context.api_url + '/api/health', reuseExistingServer: false, timeout: 60000 },
    { command: 'node e2e/serve-web.cjs', url: context.web_url, reuseExistingServer: false, timeout: 120000 },
  ],
});
