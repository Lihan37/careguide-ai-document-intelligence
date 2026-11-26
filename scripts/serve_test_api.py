"""Start only an explicitly isolated E2E API; never connect to development."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services/api'))
from app.config import settings


if __name__ == '__main__':
    cfg = settings()
    if cfg.app_env != 'test' or cfg.automation_kind != 'playwright':
        raise SystemExit('E2E API requires an isolated Playwright test environment')
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, check=True)
    import uvicorn
    server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=int(os.environ['CAREGUIDE_API_PORT']), log_level='warning', access_log=False))
    def stop_when_requested():
        while not server.should_exit:
            if (Path(cfg.runtime_root) / 'stop-request').exists():
                server.should_exit = True
                break
            time.sleep(.1)
    threading.Thread(target=stop_when_requested, daemon=True).start()
    server.run()
