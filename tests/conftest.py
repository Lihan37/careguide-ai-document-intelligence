import os
import subprocess
import sys
from pathlib import Path
from scripts.runtime_env import create_run, cleanup_run

RUN = create_run('test', 'pytest')
TEST_ROOT = Path(RUN['root'])
RUN['env']['DEMO_PASSWORD'] = 'test-only-password-123'
os.environ.update(RUN['env'])

import pytest
from fastapi.testclient import TestClient
from app.db import engine
from app.main import app


def pytest_configure(config):
    # Keep test artifacts within the writable workspace on managed Windows machines.
    if config.option.basetemp is None:
        config.option.basetemp = str(TEST_ROOT / 'pytest')


def pytest_unconfigure(config):
    engine.dispose()
    cleanup_run(RUN)


@pytest.fixture(scope='session', autouse=True)
def database():
    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=Path(__file__).resolve().parents[1], check=True, capture_output=True, text=True)
    # Committed synthetic fixtures are read-only test inputs, never startup seeds.
    yield
    engine.dispose()


@pytest.fixture
def client(monkeypatch):
    from app.jobs import run_job
    # Synchronous execution only inside API integration tests; production uses background workers.
    monkeypatch.setattr('app.main.dispatch', run_job)
    from app.main import _requests
    _requests.clear()
    with TestClient(app) as test_client:
        assert test_client.post('/api/auth/login', json={'username': 'reviewer', 'password': 'test-only-password-123'}).status_code == 200
        yield test_client
