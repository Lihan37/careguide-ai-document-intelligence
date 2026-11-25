import os
import tempfile
import uuid
from pathlib import Path

TEMP_PARENT = Path(__file__).resolve().parents[1] / 'data' / 'test-runs'
TEMP_PARENT.mkdir(parents=True, exist_ok=True)
TEST_ROOT = Path(tempfile.mkdtemp(prefix='careguide-tests-', dir=TEMP_PARENT))
os.environ.update(DATABASE_URL='sqlite:///' + str(TEST_ROOT / 'test.db'), STORAGE_DIR=str(TEST_ROOT / 'uploads'), SESSION_SECRET='test-only-session-secret-32-characters-long', DEMO_PASSWORD='test-only-password-123', EXECUTION_MODE='local', EXTRACTION_MODE='deterministic_demo', EMBEDDINGS_ENABLED='false', LLM_API_KEY='')

import pytest
from fastapi.testclient import TestClient
from app.db import Base, engine
from app.main import app


def pytest_configure(config):
    # Keep test artifacts within the writable workspace on managed Windows machines.
    if config.option.basetemp is None:
        config.option.basetemp = str(TEMP_PARENT / ('pytest-' + uuid.uuid4().hex))


@pytest.fixture(scope='session', autouse=True)
def database():
    Base.metadata.create_all(engine)
    from scripts.generate_samples import generate
    generate()
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
