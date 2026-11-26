"""Own isolated automation directories. Never reset or reuse application data."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
MARKER = '.careguide-run.json'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def create_run(environment, kind):
    if (environment, kind) not in {('test', 'pytest'), ('test', 'playwright'), ('evaluation', 'evaluation')}:
        raise ValueError('Invalid automation environment/kind')
    run_id = str(uuid.uuid4())
    base = ROOT / ('data/evaluation' if environment == 'evaluation' else 'data/test-runs')
    if not base.resolve().is_relative_to(ROOT.resolve()) or base.is_symlink() or getattr(base, 'is_junction', lambda: False)():
        raise ValueError('Automation base must stay in the workspace and cannot be a redirected directory')
    root = base / run_id
    root.mkdir(parents=True, exist_ok=False)
    marker = {'environment': environment, 'kind': kind, 'run_id': run_id}
    (root / MARKER).write_text(json.dumps(marker), encoding='utf-8')
    env = {
        'APP_ENV': environment, 'AUTOMATION_KIND': kind, 'AUTOMATION_RUN_ID': run_id,
        'RUNTIME_ROOT': str(root), 'DATABASE_URL': 'sqlite:///' + (root / 'careguide.db').as_posix(),
        'STORAGE_DIR': str(root / 'uploads'), 'SESSION_SECRET': secrets.token_urlsafe(40),
        'DEMO_USERNAME': 'reviewer', 'DEMO_PASSWORD': secrets.token_urlsafe(24),
        'EXECUTION_MODE': 'local', 'EXTRACTION_MODE': 'deterministic_demo',
        'LLM_API_KEY': '', 'EMBEDDINGS_ENABLED': 'false',
        'TESSERACT_CMD': os.getenv('TESSERACT_CMD', ''),
        'CORS_ORIGIN': 'http://localhost:3000',
    }
    result = {'run_id': run_id, 'environment': environment, 'kind': kind, 'root': str(root), 'env': env, 'python': sys.executable}
    if kind == 'playwright':
        api_port, web_port = free_port(), free_port()
        while web_port == api_port or api_port == 8000 or web_port == 3000:
            api_port, web_port = free_port(), free_port()
        result.update(api_url=f'http://127.0.0.1:{api_port}', web_url=f'http://127.0.0.1:{web_port}', api_port=api_port, web_port=web_port)
        env.update(CORS_ORIGIN=result['web_url'], NEXT_PUBLIC_API_URL=result['api_url'])
        # A source-only frontend copy avoids touching the normal Next.js server's
        # build cache or next-env.d.ts. Dependencies resolve from apps/web above it.
        web_root = ROOT / 'apps/web/.test-runs' / run_id
        web_root.mkdir(parents=True, exist_ok=False)
        (web_root / MARKER).write_text(json.dumps(marker), encoding='utf-8')
        for directory in ('app', 'components', 'public'):
            source = ROOT / 'apps/web' / directory
            if source.exists():
                shutil.copytree(source, web_root / directory)
        for filename in ('package.json', 'tsconfig.json', 'postcss.config.mjs', 'next.config.ts'):
            shutil.copy2(ROOT / 'apps/web' / filename, web_root / filename)
        result['web_root'] = str(web_root)
    return result


def verify_owned_directory(path, run_id, environment, kind, frontend=False):
    uuid.UUID(run_id)
    base = ROOT / ('apps/web/.test-runs' if frontend else 'data/evaluation' if environment == 'evaluation' else 'data/test-runs')
    target = Path(path).absolute()
    expected = base / run_id
    if target != expected or target.resolve() != expected:
        raise ValueError('Refusing operation outside the exact automation-owned directory')
    marker_path = target / MARKER
    if marker_path.is_symlink():
        raise ValueError('Refusing a redirected automation ownership marker')
    marker = json.loads(marker_path.read_text(encoding='utf-8'))
    if marker != {'environment': environment, 'kind': kind, 'run_id': run_id}:
        raise ValueError('Automation ownership marker does not match')
    return target


def cleanup_run(context):
    # No caller-supplied directory is deleted without checking the exact UUID path
    # and ownership marker. Development roots and legacy test folders never qualify.
    if context['environment'] != 'test':
        raise ValueError('Automatic cleanup is restricted to temporary test runs')
    targets = [(context['root'], False)]
    if context.get('web_root'):
        targets.append((context['web_root'], True))
    checked = [verify_owned_directory(path, context['run_id'], 'test', context['kind'], frontend) for path, frontend in targets]
    for target in checked:
        shutil.rmtree(target)


def discard_empty_run(context):
    """Unit tests may dispose of an empty evaluation configuration, never its data."""
    root = verify_owned_directory(context['root'], context['run_id'], context['environment'], context['kind'])
    if {entry.name for entry in root.iterdir()} != {MARKER}:
        raise ValueError('Refusing to discard a run containing data')
    (root / MARKER).unlink()
    root.rmdir()


def existing_run_environment(environment, run_id):
    if environment not in {'test', 'evaluation'} or str(uuid.UUID(run_id)) != run_id:
        raise ValueError('Choose an explicit automation environment and canonical run UUID')
    base = ROOT / ('data/evaluation' if environment == 'evaluation' else 'data/test-runs')
    root = base / run_id
    marker = json.loads((root / MARKER).read_text(encoding='utf-8'))
    verify_owned_directory(root, run_id, environment, marker['kind'])
    return {'APP_ENV': environment, 'AUTOMATION_KIND': marker['kind'], 'AUTOMATION_RUN_ID': run_id, 'RUNTIME_ROOT': str(root), 'DATABASE_URL': 'sqlite:///' + (root / 'careguide.db').as_posix(), 'STORAGE_DIR': str(root / 'uploads')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['create', 'cleanup'])
    parser.add_argument('environment', nargs='?', choices=['test', 'evaluation'])
    parser.add_argument('kind', nargs='?', choices=['pytest', 'playwright', 'evaluation'])
    args = parser.parse_args()
    if args.action == 'create':
        # The E2E orchestrator captures this in memory; never echo it in logs.
        print(json.dumps(create_run(args.environment, args.kind)))
    else:
        cleanup_run(json.load(sys.stdin))
