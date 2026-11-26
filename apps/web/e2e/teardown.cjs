const fs = require('node:fs');
const path = require('node:path');
const context = require('./context.cjs');
module.exports = async () => {
  fs.writeFileSync(path.join(context.root, 'stop-request'), 'stop isolated test servers');
  // Plugins stop after global teardown. Release SQLite/build handles first.
  for (let i = 0; i < 200; i++) {
    const responses = await Promise.all([context.api_url + '/api/health', context.web_url].map(url => fetch(url, { signal: AbortSignal.timeout(500) }).then(() => true).catch(() => false)));
    if (responses.every(up => !up)) { await new Promise(resolve => setTimeout(resolve, 1000)); return; }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Owned test servers did not stop; temporary directories retained for inspection');
};
