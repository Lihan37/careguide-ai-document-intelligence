// Cooperative test-only shutdown avoids Windows process-tree kill problems.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const context = require('./context.cjs');
Object.assign(process.env, context.env, { NEXT_TELEMETRY_DISABLED: '1' });
const app = require('next')({ dev: true, dir: context.web_root, hostname: '127.0.0.1', port: context.web_port });
(async () => {
  await app.prepare();
  const handler = app.getRequestHandler();
  const server = http.createServer((request, response) => handler(request, response));
  server.listen(context.web_port, '127.0.0.1');
  let stopping = false;
  const timer = setInterval(async () => {
    if (stopping || !fs.existsSync(path.join(context.root, 'stop-request'))) return;
    stopping = true;
    clearInterval(timer);
    server.closeAllConnections();
    server.close();
    await app.close();
    process.exit(0);
  }, 100);
})().catch(error => { console.error(error.message); process.exit(1); });
