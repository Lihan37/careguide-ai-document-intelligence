// Own the complete browser run. Cleanup happens after Playwright stops its servers.
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const root = path.resolve(__dirname, '../../..');
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

// Give the end-to-end deletion flow its own workspace and API rate window.
// Explicit Playwright filters still run in one isolated context.
if (process.argv.length === 2) {
  const groups = [['--grep-invert', '@document-deletion'], ['--grep', '@document-deletion']];
  const statuses = groups.map(args => spawnSync(process.execPath, [__filename, ...args], { stdio: 'inherit' }).status ?? 1);
  process.exit(statuses.find(status => status !== 0) ?? 0);
}

let context;
let status = 1;
try {
  const create = spawnSync(python, [path.join(root, 'scripts/runtime_env.py'), 'create', 'test', 'playwright'], { cwd: root, encoding: 'utf8' });
  if (create.status !== 0) throw new Error('Could not create isolated browser environment: ' + create.stderr);
  context = JSON.parse(create.stdout);
  const child = spawnSync(process.execPath, [require.resolve('@playwright/test/cli'), 'test', ...process.argv.slice(2)], {
    cwd: path.join(root, 'apps/web'), stdio: 'inherit',
    env: { ...process.env, CAREGUIDE_E2E_CONTEXT: JSON.stringify(context) },
  });
  status = child.status ?? 1;
} catch (error) {
  console.error(error.message);
} finally {
  if (context) {
    // Retain non-sensitive test reports/screenshots, not databases or uploads.
    const results = path.join(root, 'data/verification/playwright', context.run_id);
    fs.mkdirSync(results, { recursive: true });
    const artifacts = path.join(context.root, 'artifacts');
    if (fs.existsSync(artifacts)) fs.cpSync(artifacts, results, { recursive: true });
    const cleanup = spawnSync(python, [path.join(root, 'scripts/runtime_env.py'), 'cleanup'], { cwd: root, input: JSON.stringify(context), encoding: 'utf8' });
    if (cleanup.status !== 0) {
      console.error('Isolated run cleanup failed; development data was not touched: ' + cleanup.stderr);
      status = 1;
    } else console.log('Isolated browser database, uploads and frontend copy removed. Reports: ' + results);
  }
}
process.exitCode = status;
