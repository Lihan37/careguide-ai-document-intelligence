from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./data/careguide.db'
    redis_url: str = 'redis://localhost:6379/0'
    execution_mode: str = 'local'
    extraction_mode: str = 'deterministic_demo'
    storage_dir: str = './data/uploads'
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
    max_file_mb: int = 30
    max_upload_files: int = 10
    max_pages: int = 1200
    max_cells: int = 200000
    max_image_pixels: int = 25000000
    ocr_timeout: int = 30
    job_timeout: int = 3600
    currency_tolerances: dict[str, str] = {'JPY': '1', 'KRW': '1', 'KWD': '0.001', 'BHD': '0.001'}
    cors_origin: str = 'http://localhost:3000'


@lru_cache
def settings():
    result = Settings()
    Path(result.storage_dir).mkdir(parents=True, exist_ok=True)
    return result
