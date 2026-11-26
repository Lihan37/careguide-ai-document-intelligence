const path = require('node:path');
const fs = require('node:fs');
if (!process.env.CAREGUIDE_E2E_CONTEXT) {
  throw new Error('Run npm run test:e2e. Direct Playwright execution is disabled: no development fallback.');
}
const context = JSON.parse(process.env.CAREGUIDE_E2E_CONTEXT);
const root = path.resolve(__dirname, '../../..');
if (context.environment !== 'test' || context.kind !== 'playwright' || !/^[a-f0-9-]{36}$/.test(context.run_id) ||
    path.resolve(context.root) !== path.join(root, 'data/test-runs', context.run_id) ||
    path.resolve(context.web_root) !== path.join(root, 'apps/web/.test-runs', context.run_id) ||
    context.env?.APP_ENV !== 'test' || context.env?.AUTOMATION_RUN_ID !== context.run_id) {
  throw new Error('Invalid isolated browser context');
}
for (const address of [context.api_url, context.web_url]) {
  const url = new URL(address);
  if (url.hostname !== '127.0.0.1' || ['8000', '3000'].includes(url.port)) throw new Error('Refusing normal development server address');
}
const marker = JSON.parse(fs.readFileSync(path.join(context.root, '.careguide-run.json'), 'utf8'));
if (marker.run_id !== context.run_id || marker.kind !== 'playwright') throw new Error('Missing browser run ownership');
module.exports = context;
