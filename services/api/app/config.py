from functools import lru_cache
from pathlib import Path
import os
import sys
import uuid
import json
from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_file_encoding='utf-8-sig', extra='ignore')
    app_env: Literal['development', 'test', 'evaluation'] = 'development'
    automation_kind: Literal['', 'pytest', 'playwright', 'evaluation'] = ''
    automation_run_id: str = ''
    runtime_root: str = ''
    database_url: str = ''
    redis_url: str = 'redis://localhost:6379/0'
    execution_mode: str = 'local'
    extraction_mode: str = 'deterministic_demo'
    storage_dir: str = ''
    session_secret: str = ''
    demo_username: str = 'reviewer'
    demo_password: str = ''
    llm_api_key: str = ''
    llm_base_url: str = 'https://api.openai.com/v1'
    llm_model: str = 'gpt-4.1-mini'
    max_llm_chunks: int = 100
    embedding_model: str = 'text-embedding-3-small'
    embedding_dimensions: int = 1536
    embeddings_enabled: bool = False
    tesseract_cmd: str = ''
    tesseract_data_dir: str = ''
    ocr_language: str = Field(default='eng', pattern=r'^[a-zA-Z0-9_/-]+(?:\+[a-zA-Z0-9_/-]+)*$')
    ocr_review_threshold: float = Field(default=0.80, ge=0, le=1)
    max_file_mb: int = 30
    max_upload_files: int = 10
    max_pages: int = 1200
    max_cells: int = 200000
    max_image_pixels: int = 25000000
    ocr_timeout: int = Field(default=30, gt=0)
    job_timeout: int = 3600
    currency_tolerances: dict[str, str] = {'JPY': '1', 'KRW': '1', 'KWD': '0.001', 'BHD': '0.001'}
    cors_origin: str = 'http://localhost:3000'

    @model_validator(mode='after')
    def protect_environments(self):
        automated = self.automation_kind or self.automation_run_id or self.runtime_root or 'pytest' in sys.modules or os.getenv('PYTEST_CURRENT_TEST') or os.getenv('CAREGUIDE_E2E_CONTEXT')
        if self.app_env == 'development':
            if automated:
                raise ValueError('Automation cannot use the development environment')
            self.database_url = self.database_url or 'sqlite:///' + (PROJECT_ROOT / 'data/careguide.db').as_posix()
            self.storage_dir = self.storage_dir or str(PROJECT_ROOT / 'data/uploads')
            url = make_url(self.database_url)
            paths = [Path(self.storage_dir).resolve()]
            if url.get_backend_name() == 'sqlite' and url.database and url.database != ':memory:':
                paths.append(Path(url.database).resolve())
            for base in (PROJECT_ROOT / 'data/test-runs', PROJECT_ROOT / 'data/evaluation'):
                if any(path.is_relative_to(base.resolve()) for path in paths):
                    raise ValueError('Development cannot reuse an automated database or upload directory')
            return self
        if not all((self.database_url, self.storage_dir, self.runtime_root, self.automation_run_id, self.automation_kind)):
            raise ValueError('Isolated runs require explicit database, storage, runtime root, run ID and automation kind; no development fallback')
        run_id = str(uuid.UUID(self.automation_run_id))
        if run_id != self.automation_run_id:
            raise ValueError('Run ID must be a canonical UUID')
        expected = 'evaluation' if self.app_env == 'evaluation' else None
        if (expected and self.automation_kind != expected) or (self.app_env == 'test' and self.automation_kind not in {'pytest', 'playwright'}):
            raise ValueError('Automation kind and environment do not match')
        base = PROJECT_ROOT / ('data/evaluation' if expected else 'data/test-runs')
        root = Path(self.runtime_root).resolve()
        if root != (base / run_id).resolve() or not root.is_relative_to(base.resolve()) or root == base.resolve():
            raise ValueError('Runtime root must be the environment-owned UUID directory')
        marker_path = root / '.careguide-run.json'
        if not marker_path.is_file() or json.loads(marker_path.read_text(encoding='utf-8')) != {'environment': self.app_env, 'kind': self.automation_kind, 'run_id': run_id}:
            raise ValueError('Runtime ownership marker is missing or does not match')
        storage = Path(self.storage_dir).resolve()
        if not storage.is_relative_to(root) or storage == root:
            raise ValueError('Automated uploads must stay inside their isolated runtime root')
        url = make_url(self.database_url)
        if url.get_backend_name() == 'sqlite':
            if not url.database or url.database == ':memory:':
                raise ValueError('Automated application runs require an isolated file database')
            database = Path(url.database).resolve()
            if not database.is_relative_to(root) or database == root:
                raise ValueError('Automated database must stay inside its isolated runtime root')
        elif url.get_backend_name() == 'postgresql':
            if not (url.database or '').endswith('_' + self.app_env + '_' + run_id.replace('-', '')):
                raise ValueError('Automated PostgreSQL database must include environment and unique run ID')
        else:
            raise ValueError('Unsupported isolated database backend')
        # Check the actual development configuration too, including custom paths.
        from dotenv import dotenv_values
        development = dotenv_values(PROJECT_ROOT / '.env', encoding='utf-8-sig')
        dev_url = make_url(development.get('DATABASE_URL') or 'sqlite:///' + (PROJECT_ROOT / 'data/careguide.db').as_posix())
        dev_storage = Path(development.get('STORAGE_DIR') or PROJECT_ROOT / 'data/uploads').resolve()
        if storage.is_relative_to(dev_storage) or dev_storage.is_relative_to(root):
            raise ValueError('Automated storage overlaps development storage')
        if url.get_backend_name() == dev_url.get_backend_name() == 'sqlite':
            dev_database = Path(dev_url.database).resolve()
            if database == dev_database or (database.exists() and dev_database.exists() and database.samefile(dev_database)):
                raise ValueError('Automated database is the development database')
        elif url.get_backend_name() == dev_url.get_backend_name() == 'postgresql':
            if (url.host, url.port, url.database) == (dev_url.host, dev_url.port, dev_url.database):
                raise ValueError('Automated database is the development database')
        self.runtime_root, self.storage_dir = str(root), str(storage)
        return self

    @property
    def provenance(self):
        return {'environment': self.app_env, 'automation_kind': self.automation_kind or None, 'run_id': self.automation_run_id or None}


def guard_migration(environment, direction):
    if environment == 'development' and direction == 'downgrade':
        raise RuntimeError('Development database downgrades/resets are disabled; use a backed-up disposable database in an isolated environment')


def request_environment_matches(cfg, environment, run_id):
    if not environment and not run_id:
        return True  # Ordinary development/browser clients remain supported.
    if environment != cfg.app_env:
        return False
    return not run_id if cfg.app_env == 'development' else run_id == cfg.automation_run_id


@lru_cache
def settings():
    # Test/evaluation processes never read the development .env file.
    environment = os.getenv('APP_ENV', 'development')
    result = Settings(_env_file=PROJECT_ROOT / '.env' if environment == 'development' else None)
    Path(result.storage_dir).mkdir(parents=True, exist_ok=True)
    return result
