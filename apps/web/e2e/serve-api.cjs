const { spawn } = require('node:child_process');
const path = require('node:path');
const context = require('./context.cjs');
const root = path.resolve(__dirname, '../../..');
const child = spawn(context.python, [path.join(root, 'scripts/serve_test_api.py')], {
  cwd: root, stdio: 'inherit', env: { ...process.env, ...context.env, CAREGUIDE_API_PORT: String(context.api_port) },
});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('exit', code => { process.exitCode = code ?? 1; });
