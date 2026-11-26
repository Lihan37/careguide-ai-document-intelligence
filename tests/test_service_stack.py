"""Opt-in verification against real, disposable PostgreSQL and Redis services."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

from celery import Celery
from dotenv import dotenv_values
import httpx
import psycopg
from psycopg import sql
import pymupdf
import pytest
from redis import Redis
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.db import Document, Embedding, User
from app.processing import ocr_available
from app.search import CHUNK_CHARS, source_chunks
from scripts.runtime_env import ROOT, cleanup_run, create_run, free_port


def test_source_chunks_preserve_page_and_exact_offsets():
    original = ('account balances and weekly advances\n' * 150).strip()
    chunks = list(source_chunks([{'page': 3, 'method': 'digital_pdf', 'text': original},
                                {'page': 4, 'text': '  '}, {'sheet': 'Ledger', 'text': 'Balance'}]))
    previous_end = -1
    for excerpt, location in chunks[:-1]:
        assert location['page'] == 3 and location['method'] == 'digital_pdf'
        assert location['end_char'] > previous_end and len(excerpt) <= CHUNK_CHARS
        assert excerpt == original[location['start_char']:location['end_char']]
        previous_end = location['end_char']
    assert previous_end == len(original)
    assert chunks[-1] == ('Balance', {'sheet': 'Ledger', 'start_char': 0, 'end_char': 7})


@contextmanager
def child(command, env, log_path):
    with log_path.open('ab') as log:
        process = subprocess.Popen([sys.executable, *command], cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def wait_for(probe, process=None, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            pytest.fail('Service exited early. See the private service logs under data/verification.')
        if result := probe():
            return result
        time.sleep(.12)
    pytest.fail('Timed out waiting for an isolated service or job. See the private service logs.')


def seed_legacy_vector(dsn, root):
    """Insert a sentinel into revision 0001 to exercise a real in-place upgrade."""
    engine = create_engine(dsn)
    try:
        with Session(engine) as db:
            user = User(username='legacy-vector-owner', password_hash='unused', role='viewer')
            db.add(user)
            db.flush()
            document = Document(owner_id=user.id, filename='legacy-sentinel.pdf', file_type='.pdf', size=0,
                                checksum='0' * 64, storage_path=str(root / 'legacy-sentinel.pdf'))
            db.add(document)
            db.flush()
            db.add(Embedding(document_id=document.id, model='text-embedding-3-small',
                             text='Migration sentinel', source={}, vector=[1.0] + [0.0] * 1535))
            db.commit()
    finally:
        engine.dispose()


@pytest.fixture
def real_stack():
    postgres = os.getenv('CAREGUIDE_TEST_POSTGRES_URL')
    broker = os.getenv('CAREGUIDE_TEST_REDIS_URL')
    if not (postgres and broker):
        pytest.skip('Supply the isolated PostgreSQL and Redis service URLs for live stack verification.')
    url = make_url(postgres)
    redis_url = make_url(broker)
    assert url.get_backend_name() == 'postgresql' and url.host == '127.0.0.1' and url.port and not url.query
    assert redis_url.drivername == 'redis' and redis_url.host == '127.0.0.1' and redis_url.port and not redis_url.query
    # Always create a new run-owned database, even when the service is shared.
    run = create_run('test', 'pytest')
    database = 'careguide_test_' + run['run_id'].replace('-', '')
    assert database != url.database
    develop = dotenv_values(ROOT / '.env', encoding='utf-8-sig', interpolate=False)
    assert not develop.get('DATABASE_URL') or make_url(develop['DATABASE_URL']).database != database
    db_url = url.set(drivername='postgresql+psycopg', database=database).render_as_string(hide_password=False)
    pg_url = url.set(drivername='postgresql').render_as_string(hide_password=False)
    connection_url = url.set(drivername='postgresql', database=database).render_as_string(hide_password=False)
    logs = ROOT / 'data/verification' / ('services-' + run['run_id'])
    logs.mkdir(parents=True)
    port = free_port()
    while port in {3000, 8000}:
        port = free_port()
    env = os.environ | run['env'] | {
        'DATABASE_URL': db_url, 'REDIS_URL': broker, 'EXECUTION_MODE': 'celery',
        'EMBEDDINGS_ENABLED': 'true', 'EMBEDDING_PROVIDER': 'local', 'HF_HUB_OFFLINE': '1',
        'PYTHONPATH': os.pathsep.join((str(ROOT / 'services/api'), str(ROOT))),
    }
    try:
        with psycopg.connect(pg_url, connect_timeout=5, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database)))
            try:
                def migrate(revision, log):
                    subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', revision], cwd=ROOT, env=env,
                                   stdout=log, stderr=log, check=True, timeout=25)

                with (logs / 'migrations.log').open('wb') as migration_log:
                    migrate('0001', migration_log)
                    seed_legacy_vector(db_url, Path(run['root']))
                    migrate('head', migration_log)
                yield run, env, logs, connection_url, port
            finally:
                admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
    finally:
        cleanup_run(run)


def synthetic_statement(number, supplier, description):
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((45, 60), '\n'.join([
            'SYNTHETIC INVOICE', 'Invoice number: ' + number, 'Invoice date: 2026-10-21',
            'Supplier: ' + supplier, 'Customer: Synthetic Office', 'Currency: USD',
            'Description | Qty | Unit Price | Amount', description + ' | 1 | 32.50 | 32.50',
            'Subtotal: USD 32.50', 'Tax: USD 0.00', 'Total: USD 32.50',
        ]))
        return pdf.tobytes()


def longer_scan():
    with pymupdf.open(ROOT / 'sample-data/ocr/multipage.pdf') as original, pymupdf.open() as target:
        for _ in range(4):
            target.insert_pdf(original)
        assert len(target) == 8 and all(not page.get_text().strip() for page in target)
        return target.tobytes()


def test_real_postgres_pgvector_redis_celery(real_stack):
    assert ocr_available(), 'Set the Tesseract executable and language data before running the service stack verification.'
    run, env, logs, dsn, port = real_stack
    worker_pool = 'solo' if os.name == 'nt' else 'prefork'
    worker_cmd = ['-m', 'celery', '-A', 'worker.tasks:celery_app', 'worker',
                  f'--pool={worker_pool}', '--concurrency=1', '--loglevel=INFO', '--without-gossip', '--without-mingle']
    api_cmd = ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]
    headers = {'X-CareGuide-Environment': 'test', 'X-CareGuide-Run': run['run_id']}
    namespace = 'careguide:test:' + run['run_id']
    metrics = {'worker_pool': worker_pool, 'semantic': []}
    terminal = {'COMPLETED', 'REQUIRES_REVIEW', 'FAILED'}
    with Redis.from_url(env['REDIS_URL'], socket_timeout=3) as redis:
        assert redis.ping()
        metrics['redis'] = redis.info('server')['redis_version']

    def ready(process, client):
        def probe():
            try:
                response = client.get('/api/environment', timeout=1)
                return response.json() if response.is_success else None
            except httpx.TransportError:
                return None

        assert wait_for(probe, process) == {'environment': 'test', 'automation_kind': 'pytest', 'run_id': run['run_id']}
        assert client.post('/api/auth/login', json={'username': env['DEMO_USERNAME'], 'password': env['DEMO_PASSWORD']}).status_code == 200

    with httpx.Client(base_url=f'http://127.0.0.1:{port}', headers=headers, timeout=10, trust_env=False) as client:
        def upload(name, content=None):
            content = (ROOT / 'sample-data' / name).read_bytes() if content is None else content
            response = client.post('/api/documents/upload', files={'files': (name, content, 'application/pdf')})
            assert response.status_code == 202
            record = response.json()['results'][0]
            assert 'job_id' in record, record
            return record['document_id'], record['job_id']

        def job(job_id):
            response = client.get('/api/jobs/' + job_id)
            assert response.status_code == 200
            return response.json()

        def finished(job_id):
            entry = job(job_id)
            return entry if entry['status'] in terminal else None

        with child(api_cmd, env, logs / 'api.log') as api:
            ready(api, client)
            assert client.get('/api/settings').json()['semantic_available']
            energy, queue_job = upload('power-statement.pdf', synthetic_statement(
                'PWR-22', 'North Grid Utilities', 'Power consumption and kilowatt hours supplied to office premises'))
            assert job(queue_job)['status'] == 'QUEUED'
            with Redis.from_url(env['REDIS_URL'], socket_timeout=3) as redis:
                assert redis.llen(f'{namespace}:{namespace}') == 1
            publisher = Celery('verification', broker=env['REDIS_URL'])
            publisher.conf.broker_transport_options = {'global_keyprefix': namespace + ':'}
            publisher.send_task('worker.tasks.process_document', args=[queue_job], queue=namespace)
            publisher.close()
            network, network_job = upload('network-statement.pdf', synthetic_statement(
                'NET-33', 'Fiber Exchange', 'Monthly broadband connectivity and dedicated fibre circuit subscription'))
            invoice, invoice_job = upload('layout-invoice.pdf')

            with child(worker_cmd, env, logs / 'worker.log') as worker:
                for work in (queue_job, network_job, invoice_job):
                    result = wait_for(lambda: finished(work), worker)
                    assert result['status'] in {'COMPLETED', 'REQUIRES_REVIEW'}, result
                energy_record = client.get('/api/documents/' + energy).json()
                assert len(energy_record['history']) == len(energy_record['sources']) == 1
                assert energy_record['sources'][0]['page'] == 1
                assert client.get('/api/documents/' + energy + '/source').content.startswith(b'%PDF')
                assert client.get('/api/search', params={'q': 'PWR-22'}).json()['total'] == 1
                for query, expected in [('electricity bill', energy), ('internet service subscription', network),
                                        ('equipment for digitizing paperwork', invoice)]:
                    started = time.perf_counter()
                    response = client.post('/api/search/semantic', json={'query': query, 'limit': 10})
                    elapsed = time.perf_counter() - started
                    assert response.status_code == 200, response.text
                    rows = response.json()['items']
                    assert rows[0]['document_id'] == expected, rows
                    selected = client.get('/api/documents/' + expected).json()['sources'][0]
                    source = rows[0]['source']
                    assert source['page'] == selected['page'] == 1
                    assert rows[0]['excerpt'] == selected['text'][source['start_char']:source['end_char']]
                    assert client.get('/api/search', params={'q': query}).json()['total'] == 0
                    metrics['semantic'].append({'query': query, 'rank': 1, 'top_distance': rows[0]['distance'],
                                                'page': source['page'], 'seconds': round(elapsed, 6)})

                correction = client.patch('/api/documents/' + energy + '/corrections',
                                          json={'fields': {'customer_name': 'Verified Synthetic Office'}, 'reason': 'Review original'})
                assert correction.status_code == 200
                compare = client.post('/api/comparisons', json={'document_ids': [energy, invoice]})
                assert compare.status_code == 201
                comparison_id = compare.json()['id']
                corrupt, corrupt_job = upload('corrupted.pdf')
                assert wait_for(lambda: finished(corrupt_job), worker)['status'] == 'FAILED'
                retry = client.post('/api/documents/' + corrupt + '/reprocess')
                assert retry.status_code == 202
                second = wait_for(lambda: finished(retry.json()['id']), worker)
                assert second['status'] == 'FAILED' and second['retries'] == 1

                scan, scan_job = upload('eight-page-scan.pdf', longer_scan())
                samples, health_times = [], []
                def observe_scan():
                    state = job(scan_job)
                    if state['status'] == 'PROCESSING':
                        samples.append(state['pages_processed'])
                        started = time.perf_counter()
                        assert client.get('/api/health').status_code == 200
                        health_times.append(time.perf_counter() - started)
                    return state if state['status'] in terminal else None

                result = wait_for(observe_scan, worker)
                assert result['status'] in {'COMPLETED', 'REQUIRES_REVIEW'}, result
                assert result['pages_processed'] == 8 and any(0 < n < 8 for n in samples)
                pages = client.get('/api/documents/' + scan).json()['sources']
                assert [page['page'] for page in pages] == list(range(1, 9))
                assert all(page['method'] == 'tesseract_ocr' for page in pages)
                metrics['queued_scan'] = {'pages': 8, 'progress_observations': sorted(set(samples)),
                                          'api_health_requests': len(health_times), 'api_health_max_seconds': max(health_times)}

                # Simulate an interrupted worker with an expired database lease.
                with psycopg.connect(dsn) as db:
                    db.execute("UPDATE processing_jobs SET status='PROCESSING', updated_at='2000-01-01' WHERE id=%s", (scan_job,))
                    db.execute("UPDATE documents SET status='PROCESSING' WHERE id=%s", (scan,))
                assert client.post('/api/jobs/recover-stale').json()['recovered'] == 1
                assert job(scan_job)['status'] == 'FAILED'
                retry = client.post('/api/documents/' + scan + '/reprocess')
                assert retry.status_code == 202
                assert wait_for(lambda: finished(retry.json()['id']), worker)['status'] in {'COMPLETED', 'REQUIRES_REVIEW'}

        with child(api_cmd, env, logs / 'api.log') as api:
            ready(api, client)
            assert client.get('/api/documents/' + energy).json()['effective']['customer_name'] == 'Verified Synthetic Office'
            assert client.get('/api/comparisons/' + comparison_id).status_code == 200
            with psycopg.connect(dsn) as db:
                metrics['postgresql'] = db.execute('SHOW server_version').fetchone()[0]
                metrics['pgvector'] = db.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
                assert db.execute('SELECT version_num FROM alembic_version').fetchone()[0] == '0002'
                assert db.execute('SELECT DISTINCT vector_dims(vector) FROM document_embeddings ORDER BY 1').fetchall() == [(384,), (1536,)]
                legacy = db.execute("SELECT vector::text FROM document_embeddings WHERE text='Migration sentinel'").fetchone()[0]
                assert json.loads(legacy) == [1] + [0] * 1535
                indexes = {row[0] for row in db.execute('SELECT indexname FROM pg_indexes WHERE schemaname=current_schema()')}
                assert {'ix_documents_owner_uploaded', 'ix_source_units_document_position',
                        'ix_document_embeddings_model_document'} <= indexes
                owner = db.execute('SELECT owner_id FROM documents WHERE id=%s', (energy,)).fetchone()[0]
                db.execute('SET LOCAL enable_seqscan=off')
                plan = db.execute('EXPLAIN SELECT id FROM documents WHERE owner_id=%s ORDER BY uploaded_at DESC LIMIT 1', (owner,)).fetchall()
                assert any('ix_documents_owner_uploaded' in row[0] for row in plan)
                stranger = str(uuid4())
                db.execute("INSERT INTO users (id, username, password_hash, role) VALUES (%s, %s, %s, 'viewer')",
                           (stranger, 'synthetic-other-user', 'unused'))
                db.execute('UPDATE documents SET owner_id=%s WHERE id=%s', (stranger, network))
            assert client.get('/api/documents/' + network).status_code == 404
            rows = client.post('/api/search/semantic', json={'query': 'internet service subscription', 'limit': 50}).json()['items']
            assert rows and all(row['document_id'] != network for row in rows)

    (logs / 'results.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
