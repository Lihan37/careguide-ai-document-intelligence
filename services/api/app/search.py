from sqlalchemy import select, delete
from .config import settings
from .db import Embedding, Document


def client():
    from openai import OpenAI
    cfg = settings()
    if not cfg.embeddings_enabled or not cfg.llm_api_key or not cfg.database_url.startswith('postgresql'):
        raise ValueError('Semantic search requires PostgreSQL, EMBEDDINGS_ENABLED=true and LLM_API_KEY')
    return OpenAI(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url, timeout=30, max_retries=2)


def embed(texts):
    cfg = settings()
    response = client().embeddings.create(model=cfg.embedding_model, input=texts, dimensions=cfg.embedding_dimensions)
    return [row.embedding for row in response.data]


def index_document(db, document, source):
    db.execute(delete(Embedding).where(Embedding.document_id == document.id))
    for unit in source:
        chunks = [unit['text'][i:i + 3000] for i in range(0, len(unit['text']), 2500)]
        for start in range(0, len(chunks), 16):
            batch = chunks[start:start + 16]
            for text, vector in zip(batch, embed(batch)):
                db.add(Embedding(document_id=document.id, text=text, vector=vector, model=settings().embedding_model, source={k: unit[k] for k in ('page', 'sheet', 'document_id') if k in unit}))
    db.commit()


def semantic(db, owner_id, query, limit):
    vector = embed([query])[0]
    distance = Embedding.vector.cosine_distance(vector)
    rows = db.execute(select(Embedding, Document.filename, distance.label('distance')).join(Document, Document.id == Embedding.document_id).where(Document.owner_id == owner_id, Embedding.model == settings().embedding_model).order_by(distance).limit(limit))
    return [{'document_id': row[0].document_id, 'filename': row[1], 'excerpt': row[0].text, 'source': row[0].source, 'distance': float(row[2])} for row in rows]
