"""Fail-closed configuration and automation ownership, without touching dev data."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import select, delete

from app.config import Settings, settings, PROJECT_ROOT, guard_migration, request_environment_matches
from app.db import engine, Session, Document, Audit
from app.inspection import automation_proof, readonly_database
from scripts.runtime_env import create_run, cleanup_run, verify_owned_directory, discard_empty_run, existing_run_environment
from scripts.cleanup_automated_records import cleanup_plan, apply_plan


@pytest.fixture
def context():
    run = create_run('test', 'pytest')
    yield run
    cleanup_run(run)
    assert not Path(run['root']).exists()


def model(context, **changes):
    values = {name.lower(): value for name, value in context['env'].items()}
    return Settings(_env_file=None, **(values | changes))


def test_current_pytest_engine_and_uploads_are_isolated():
    cfg = settings()
    assert cfg.app_env == 'test' and cfg.automation_kind == 'pytest'
    root = Path(cfg.runtime_root)
    assert Path(engine.url.database).is_relative_to(root)
    assert Path(cfg.storage_dir).is_relative_to(root)
    assert root != PROJECT_ROOT / 'data'


def test_explicit_complete_test_configuration(context):
    cfg = model(context)
    assert cfg.app_env == 'test'
    assert cfg.database_url != 'sqlite:///./data/careguide.db'


@pytest.mark.parametrize('missing', ['database_url', 'storage_dir', 'runtime_root', 'automation_run_id', 'automation_kind'])
def test_missing_test_configuration_has_no_development_fallback(context, missing):
    with pytest.raises(ValueError, match='require explicit'):
        model(context, **{missing: ''})


def test_pytest_cannot_choose_development_even_with_explicit_url(context):
    with pytest.raises(ValueError, match='Automation cannot use'):
        model(context, app_env='development')


@pytest.mark.parametrize('url', ['sqlite:///./data/careguide.db', 'sqlite:///./data/test-runs/../careguide.db', 'sqlite:///:memory:'])
def test_development_or_nonowned_sqlite_database_rejected(context, url):
    with pytest.raises(ValueError):
        model(context, database_url=url)


@pytest.mark.parametrize('storage', ['./data/uploads', './data', './sample-data'])
def test_development_and_fixture_storage_rejected(context, storage):
    with pytest.raises(ValueError, match='uploads must stay'):
        model(context, storage_dir=storage)


def test_runtime_root_cannot_be_development_root(context):
    with pytest.raises(ValueError, match='UUID directory'):
        model(context, runtime_root=str(PROJECT_ROOT / 'data'))


def test_run_identity_must_match_environment(context):
    with pytest.raises(ValueError, match='do not match'):
        model(context, app_env='evaluation')
    with pytest.raises(ValueError):
        model(context, automation_run_id='not-a-uuid')


def test_ownership_marker_is_required(context):
    marker = Path(context['root']) / '.careguide-run.json'
    original = marker.read_text()
    marker.write_text('{}')
    try:
        with pytest.raises(ValueError, match='ownership marker'):
            model(context)
    finally:
        marker.write_text(original)


def test_hardlink_to_protected_development_database_rejected(context, tmp_path, monkeypatch):
    protected = tmp_path / 'protected-development.db'
    protected.write_bytes(b'not an actual application database')
    alias = Path(context['root']) / 'careguide.db'
    os.link(protected, alias)
    monkeypatch.setattr('dotenv.dotenv_values', lambda *args, **kwargs: {'DATABASE_URL': 'sqlite:///' + protected.as_posix()})
    with pytest.raises(ValueError, match='is the development database'):
        model(context)


def test_postgresql_compatibility_requires_unique_nondev_database(context):
    with pytest.raises(ValueError, match='unique run ID'):
        model(context, database_url='postgresql+psycopg://local@localhost/careguide')
    url = 'postgresql+psycopg://local@localhost/careguide_test_' + context['run_id'].replace('-', '')
    assert model(context, database_url=url).database_url == url


def test_evaluation_and_test_namespaces_are_distinct():
    run = create_run('evaluation', 'evaluation')
    cfg = model(run)
    assert cfg.app_env == 'evaluation'
    assert Path(cfg.runtime_root).is_relative_to(PROJECT_ROOT / 'data/evaluation')
    assert not Path(cfg.runtime_root).is_relative_to(PROJECT_ROOT / 'data/test-runs')
    # Only empty configuration artifacts were created; retain evaluation runs by
    # design, rather than giving automatic test cleanup authority over evaluation.
    with pytest.raises(ValueError, match='restricted to temporary test'):
        cleanup_run(run)
    discard_empty_run(run)
    assert not Path(run['root']).exists()


def test_development_migration_reset_is_blocked():
    with pytest.raises(RuntimeError, match='downgrades/resets are disabled'):
        guard_migration('development', 'downgrade')
    guard_migration('development', 'upgrade')
    guard_migration('test', 'downgrade')


def test_missing_development_mode_is_not_a_pytest_escape_hatch(context):
    # The framework marker is independent of configuration values.
    values = {name.lower(): value for name, value in context['env'].items()}
    values.update(app_env='development', automation_kind='', automation_run_id='', runtime_root='')
    with pytest.raises(ValueError, match='Automation cannot use'):
        Settings(_env_file=None, **values)


def test_subprocess_engine_import_refuses_development_for_automation():
    env = os.environ | {'APP_ENV': 'development', 'AUTOMATION_KIND': 'pytest', 'PYTHONPATH': str(PROJECT_ROOT / 'services/api')}
    result = subprocess.run([sys.executable, '-c', 'import app.db'], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert 'Automation cannot use the development environment' in result.stderr


def test_playwright_without_isolation_context_fails_before_starting_servers():
    env = dict(os.environ)
    env.pop('CAREGUIDE_E2E_CONTEXT', None)
    result = subprocess.run(['node', '-e', "require('./e2e/context.cjs')"], cwd=PROJECT_ROOT / 'apps/web', env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert 'no development fallback' in result.stderr


def test_playwright_refuses_normal_app_address():
    run = create_run('test', 'playwright')
    try:
        run['api_url'] = 'http://127.0.0.1:8000'
        env = os.environ | {'CAREGUIDE_E2E_CONTEXT': json.dumps(run)}
        result = subprocess.run(['node', '-e', "require('./e2e/context.cjs')"], cwd=PROJECT_ROOT / 'apps/web', env=env, capture_output=True, text=True, timeout=15)
        assert result.returncode != 0
        assert 'Refusing normal development server' in result.stderr
    finally:
        cleanup_run(run)
    assert not Path(run['root']).exists() and not Path(run['web_root']).exists()


def test_runtime_cleanup_cannot_target_development_or_foreign_run(context):
    for target in [PROJECT_ROOT / 'data', PROJECT_ROOT / 'data/uploads', PROJECT_ROOT / 'sample-data']:
        with pytest.raises(ValueError, match='Refusing operation'):
            verify_owned_directory(target, context['run_id'], 'test', 'pytest')


def test_api_identifies_environment_and_records_upload_provenance(client):
    cfg = settings()
    assert client.get('/api/environment').json() == cfg.provenance
    response = client.post('/api/documents/upload', files=[('files', ('invoice.pdf', Path('sample-data/invoice.pdf').read_bytes()))])
    id = response.json()['results'][0]['document_id']
    with Session() as db:
        event = db.scalar(select(Audit).where(Audit.document_id == id, Audit.action == 'uploaded'))
        assert all(event.detail[name] == value for name, value in cfg.provenance.items())
        document = db.get(Document, id)
        assert Path(document.storage_path).is_relative_to(Path(cfg.storage_dir))


def test_development_server_rejects_tagged_browser_automation():
    cfg = SimpleNamespace(app_env='development', automation_run_id='')
    assert not request_environment_matches(cfg, 'test', settings().automation_run_id)
    assert request_environment_matches(cfg, None, None)


@pytest.mark.parametrize('headers', [
    {'X-CareGuide-Environment': 'development'},
    {'X-CareGuide-Environment': 'test', 'X-CareGuide-Run': 'wrong-run'},
])
def test_cross_environment_upload_is_blocked_before_insertion(client, headers):
    with Session() as db:
        before = set(db.scalars(select(Document.id)))
    response = client.post('/api/documents/upload', files=[('files', ('fixture.csv', b'a,b\n1,2'))], headers=headers)
    assert response.status_code == 403
    with Session() as db:
        assert set(db.scalars(select(Document.id))) == before


def test_ordinary_startup_does_not_seed_documents(client):
    from fastapi.testclient import TestClient
    from app.main import app
    with Session() as db:
        before = set(db.scalars(select(Document.id)))
    with TestClient(app):
        pass
    with Session() as db:
        assert set(db.scalars(select(Document.id))) == before


def test_cleanup_never_selects_filename_or_checksum_alone(client):
    response = client.post('/api/documents/upload', files=[('files', ('invoice.pdf', Path('sample-data/invoice.pdf').read_bytes()))])
    id = response.json()['results'][0]['document_id']
    with Session() as db:
        db.execute(delete(Audit).where(Audit.document_id == id))
        db.commit()
    plan = cleanup_plan(settings())
    assert id not in {row['document_id'] for row in plan['would_delete']}
    with pytest.raises(ValueError, match='unproven'):
        cleanup_plan(settings(), [id])


def test_cleanup_dry_run_lists_exact_proven_records_but_changes_nothing(client):
    response = client.post('/api/documents/upload', files=[('files', ('fixture.csv', b'invoice_number,total,currency\nTEMP-1,1,USD'))])
    id = response.json()['results'][0]['document_id']
    with Session() as db:
        document = db.get(Document, id)
        original = Path(document.storage_path)
    plan = cleanup_plan(settings(), [id])
    assert plan['mode'] == 'dry-run' and plan['would_delete'][0]['document_id'] == id
    assert plan['would_delete'][0]['original_path'] == str(original)
    assert plan['would_delete'][0]['related_records_to_delete']['processing_jobs'] == 1
    assert original.is_file()
    with Session() as db:
        assert db.get(Document, id) is not None
    # No actual cleanup deletion is executed by this test suite.
    with pytest.raises(ValueError, match='explicit IDs'):
        apply_plan(settings(), plan, [id], 'wrong confirmation')
    assert original.is_file()


def test_cleanup_apply_refuses_development_unconditionally():
    cfg = SimpleNamespace(app_env='development', automation_run_id='')
    with pytest.raises(ValueError, match='isolated environment'):
        apply_plan(cfg, {'would_delete': []}, ['any'], 'DELETE AUTOMATED RECORDS ')


def test_inventory_connection_is_read_only():
    with readonly_database(settings().database_url) as connection:
        with pytest.raises(Exception):
            connection.exec_driver_sql('DELETE FROM documents')


def test_importing_evaluation_script_does_not_import_database_or_seed():
    result = subprocess.run([sys.executable, '-c', "import sys; import scripts.evaluate; assert 'app.db' not in sys.modules; print('read-only import')"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0 and 'read-only import' in result.stdout


def test_celery_queue_is_scoped_to_environment_and_run_without_connecting():
    from worker.tasks import celery_app
    assert settings().automation_run_id in celery_app.conf.task_default_queue
    assert settings().app_env in celery_app.conf.broker_transport_options['global_keyprefix']


def test_existing_run_selection_never_accepts_development_or_traversal(context):
    assert existing_run_environment('test', context['run_id'])['DATABASE_URL'] == context['env']['DATABASE_URL']
    with pytest.raises(ValueError):
        existing_run_environment('development', context['run_id'])
    with pytest.raises(ValueError):
        existing_run_environment('test', '../careguide.db')


def test_explicit_windows_environment_file_encoding(tmp_path, monkeypatch):
    monkeypatch.delenv('MAX_FILE_MB', raising=False)
    file = tmp_path / 'explicit.env'
    file.write_text('MAX_FILE_MB=17\n', encoding='utf-8-sig')
    cfg = Settings(_env_file=file)
    assert cfg.app_env == 'test' and cfg.max_file_mb == 17


def test_evaluation_refuses_cached_application_without_mutating_environment():
    from scripts.evaluate import evaluate
    before = dict(os.environ)
    with pytest.raises(RuntimeError, match='separate process'):
        evaluate()
    assert dict(os.environ) == before


def test_snapshot_comparison_cannot_overwrite_baseline_and_hide_changes(client):
    command = [sys.executable, 'scripts/inspect_records.py']
    first = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15)
    assert first.returncode == 0
    baseline = Path(settings().runtime_root) / 'inspection/current-snapshot.json'
    before = baseline.read_bytes()
    assert client.post('/api/documents/upload', files=[('files', ('snapshot.csv', b'invoice_number,total\nCHECK-1,10'))]).status_code == 202
    compared = subprocess.run(command + ['--compare-snapshot', str(baseline)], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15)
    assert compared.returncode != 0
    assert 'documents' in json.loads(compared.stdout)['changed_tables']
    assert baseline.read_bytes() == before
