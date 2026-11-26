"""Owner-scoped cosine search over genuine embeddings of stored source chunks."""
from functools import lru_cache
from importlib.util import find_spec
from itertools import batched
from math import isfinite

from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from .config import settings
from .db import Document, Embedding

LOCAL_MODEL = 'BAAI/bge-small-en-v1.5'
LOCAL_DIMENSIONS = 384
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 120
BATCH_SIZE = 16


class SemanticUnavailable(ValueError):
    """A safe, user-facing indexing or retrieval error."""


def unavailable_reason(cfg):
    if not cfg.embeddings_enabled or make_url(cfg.database_url).get_backend_name() != 'postgresql':
        return 'Semantic search requires PostgreSQL with pgvector and EMBEDDINGS_ENABLED=true.'
    if cfg.embedding_provider == 'local' and find_spec('fastembed') is None:
        return 'Install FastEmbed in the API and worker environments.'
    if cfg.embedding_provider == 'openai' and not cfg.llm_api_key:
        return 'Set LLM_API_KEY for the OpenAI-compatible embedding provider or select EMBEDDING_PROVIDER=local.'
    return None


def model_info(cfg):
    if cfg.embedding_provider == 'local':
        return 'fastembed:' + LOCAL_MODEL, LOCAL_DIMENSIONS
    return cfg.embedding_model, cfg.embedding_dimensions


@lru_cache(maxsize=1)
def local_model(cache_dir):
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=LOCAL_MODEL, cache_dir=cache_dir, threads=2,
                         providers=['CPUExecutionProvider'], local_files_only=True)


def embed(texts, *, query=False):
    cfg = settings()
    if reason := unavailable_reason(cfg):
        raise SemanticUnavailable(reason)
    _, dimensions = model_info(cfg)
    try:
        if cfg.embedding_provider == 'local':
            model = local_model(str(cfg.embedding_cache_dir.resolve()))
            vectors = [vector.tolist() for vector in (
                model.query_embed(texts, batch_size=BATCH_SIZE) if query
                else model.passage_embed(texts, batch_size=BATCH_SIZE)
            )]
        else:
            from openai import OpenAI

            with OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url, timeout=30, max_retries=2) as client:
                result = client.embeddings.create(model=cfg.embedding_model, input=texts, dimensions=dimensions)
            ordered = sorted(result.data, key=lambda row: row.index)
            if [row.index for row in ordered] != list(range(len(texts))):
                raise SemanticUnavailable('Embedding provider returned mismatched batch positions.')
            vectors = [row.embedding for row in ordered]
    except SemanticUnavailable:
        raise
    except Exception:
        message = ('Local embedding weights could not be loaded or run. Check the FastEmbed cache and runtime.'
                   if cfg.embedding_provider == 'local' else 'Embedding provider is unavailable. Check configuration and quota.')
        raise SemanticUnavailable(message) from None
    if len(vectors) != len(texts) or any(
        len(vector) != dimensions or not all(map(isfinite, vector)) or not any(vector)
        for vector in vectors
    ):
        raise SemanticUnavailable('Embedding provider returned unusable vectors.')
    return vectors


def source_chunks(source):
    for unit in source:
        text = unit['text']
        location = {key: unit[key] for key in ('page', 'sheet', 'method', 'document_id') if key in unit}
        offset = 0
        while offset < len(text):
            end = min(offset + CHUNK_CHARS, len(text))
            if end < len(text):
                boundary = max(text.rfind(' ', offset + CHUNK_CHARS // 2, end),
                               text.rfind('\n', offset + CHUNK_CHARS // 2, end))
                if boundary != -1:
                    end = boundary + 1
            excerpt = text[offset:end]
            if excerpt.strip():
                yield excerpt, location | {'start_char': offset, 'end_char': end}
            if end == len(text):
                break
            offset = end - CHUNK_OVERLAP


def index_document(db, document, source):
    cfg = settings()
    if reason := unavailable_reason(cfg):
        raise SemanticUnavailable(reason)
    model, _ = model_info(cfg)
    db.execute(delete(Embedding).where(Embedding.document_id == document.id))
    for batch in batched(source_chunks(source), BATCH_SIZE):
        vectors = embed([text for text, _ in batch])
        for (text, location), vector in zip(batch, vectors, strict=True):
            db.add(Embedding(document_id=document.id, text=text, vector=vector, model=model, source=location))
        db.flush()


def semantic(db, owner_id, query, limit):
    cfg = settings()
    query = query.strip()
    if not query:
        return []
    model, dimensions = model_info(cfg)
    vector = embed([query], query=True)[0]
    distance = Embedding.vector.cosine_distance(vector)
    rows = db.execute(
        select(Embedding.document_id, Document.filename, Embedding.text, Embedding.source, distance.label('distance'))
        .join(Document, Document.id == Embedding.document_id)
        .where(Document.owner_id == owner_id, Document.status.in_(('COMPLETED', 'REQUIRES_REVIEW')),
               Embedding.model == model, func.vector_dims(Embedding.vector) == dimensions)
        .order_by(distance, Embedding.id).limit(limit)
    )
    return [{'document_id': row.document_id, 'filename': row.filename, 'excerpt': row.text,
             'source': row.source, 'distance': float(row.distance)} for row in rows]
