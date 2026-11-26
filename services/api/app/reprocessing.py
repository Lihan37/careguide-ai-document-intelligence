"""Compare and publish extraction snapshots without mixing result and job state."""
import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import delete, select, update

from .config import settings
from .db import Audit, Document, Embedding, Job, SourceUnit
from .schemas import Invoice
from .validation import discount_magnitude, duplicates, validate

ACTIVE_JOB = ('QUEUED', 'PROCESSING', 'CANCELLING')


def lock_document(db, document_id, owner_id=None):
    # Take a write lock before reading mutable state on both SQLite and PostgreSQL.
    statement = update(Document).where(Document.id == document_id)
    if owner_id is not None:
        statement = statement.where(Document.owner_id == owner_id)
    result = db.execute(statement.values(status=Document.status).execution_options(synchronize_session=False))
    return db.get(Document, document_id, populate_existing=True) if result.rowcount == 1 else None


def has_active_job(db, document_id):
    return db.scalar(select(Job.id).where(Job.document_id == document_id, Job.status.in_(ACTIVE_JOB)).limit(1)) is not None


def has_current_extraction(document):
    # Include successful extractions with open review issues as well as approved results.
    return bool(document.raw or document.corrected)


def current_snapshot(document):
    return {
        'raw': document.raw, 'corrected': document.corrected, 'evidence': document.evidence,
        'issues': document.issues, 'method': document.extraction_method, 'status': document.status,
        'review_status': document.review_status,
    }


def current_revision(document):
    state = json.dumps(current_snapshot(document), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(state.encode()).hexdigest()


def effective_invoice(document, raw):
    return Invoice.model_validate(raw | document.corrected)


def equivalent_invoice(document, proposed):
    try:
        current = effective_invoice(document, document.raw)
    except ValidationError:
        # Legacy data may be incomplete or invalid. Keep it available for review.
        return False
    if current.discount is None or proposed.discount is None:
        return current == proposed
    return current.model_copy(update={'discount': discount_magnitude(current.discount)}) == proposed.model_copy(
        update={'discount': discount_magnitude(proposed.discount)}
    )


def source_units(db, document_id):
    return list(db.scalars(select(SourceUnit.data).where(SourceUnit.document_id == document_id).order_by(SourceUnit.position)))


def evaluated_issues(db, document, invoice, extraction_issues):
    others = db.scalars(select(Document).where(Document.owner_id == document.owner_id)).all()
    return extraction_issues + validate(invoice) + duplicates(document, others, invoice.model_dump(mode='json'))


def publish(db, document, result, invoice, issues, *, replace_sources=True):
    sources = result['sources']
    if replace_sources:
        db.execute(delete(SourceUnit).where(SourceUnit.document_id == document.id))
        db.add_all(SourceUnit(document_id=document.id, position=position, data=unit)
                   for position, unit in enumerate(sources))
    db.execute(delete(Embedding).where(Embedding.document_id == document.id))
    document.text = '\n\n'.join(unit['text'] for unit in sources)
    document.page_count = sum('page' in unit for unit in sources)
    document.sheet_count = sum('sheet' in unit for unit in sources)
    document.raw, document.evidence = result['raw'], result['evidence']
    document.extraction_method = result['method']
    document.invoice_number, document.supplier = invoice.invoice_number, invoice.supplier_name
    document.issues = issues
    document.status = 'REQUIRES_REVIEW' if issues else 'COMPLETED'
    document.review_status = 'pending'
    document.error = None
    document.duration = result['duration']
    if settings().embeddings_enabled:
        from .search import SemanticUnavailable, index_document
        try:
            with db.begin_nested():
                index_document(db, document, sources)
        except SemanticUnavailable as exc:
            db.add(Audit(document_id=document.id, user_id=document.owner_id, action='semantic_indexing_failed',
                         detail={'reason': str(exc)}))
