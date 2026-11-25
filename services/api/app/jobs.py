import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from sqlalchemy import select, update, delete
from .db import Session, Document, Job, SourceUnit, Embedding, now
from .config import settings
from .processing import units
from .extraction import extract
from .validation import validate, duplicates

_pool = None


class Cancelled(Exception):
    pass


def dispatch(job_id):
    if settings().execution_mode == 'celery':
        from worker.tasks import process_document
        process_document.delay(job_id)
    else:
        global _pool
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=1)
        _pool.submit(run_job, job_id)


def run_job(job_id):
    started = time.monotonic()
    with Session() as db:
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == 'QUEUED').values(status='PROCESSING', stage='Reading document', updated_at=now()))
        db.commit()
        if claimed.rowcount != 1:
            return  # Atomic claim prevents duplicate deliveries from doing work.
        job = db.get(Job, job_id)
        document = db.get(Document, job.document_id)
        document.status = 'PROCESSING'
        db.execute(delete(SourceUnit).where(SourceUnit.document_id == document.id))
        db.execute(delete(Embedding).where(Embedding.document_id == document.id))
        db.commit()
        try:
            for position, unit in enumerate(units(Path(document.storage_path), document.file_type)):
                db.refresh(job)
                if job.status == 'CANCELLED':
                    raise Cancelled()
                if time.monotonic() - started > settings().job_timeout:
                    raise TimeoutError('Document processing time limit exceeded')
                unit['document_id'] = document.id
                db.add(SourceUnit(document_id=document.id, position=position, data=unit))
                job.pages_processed = position + 1
                job.total_pages = unit['total']
                job.progress = min(70, int(70 * (position + 1) / max(1, unit['total'])))
                job.updated_at = now()
                db.commit()
            source = [row.data for row in db.scalars(select(SourceUnit).where(SourceUnit.document_id == document.id).order_by(SourceUnit.position))]
            if not source:
                raise ValueError('No readable content found')
            document.text = '\n\n'.join(unit['text'] for unit in source)
            document.page_count = sum('page' in unit for unit in source)
            document.sheet_count = sum('sheet' in unit for unit in source)
            job.progress, job.stage = 75, 'Structured extraction'
            db.commit()
            invoice, evidence, issues, method, usage = extract(source)
            document.raw = invoice.model_dump(mode='json')
            document.evidence = evidence
            document.extraction_method = method
            effective = document.raw | document.corrected
            from .schemas import Invoice
            invoice = Invoice.model_validate(effective)
            document.invoice_number = invoice.invoice_number
            document.supplier = invoice.supplier_name
            issues += validate(invoice)
            others = db.scalars(select(Document).where(Document.owner_id == document.owner_id)).all()
            issues += duplicates(document, others, effective)
            document.issues = issues
            job.stage, job.progress = 'Indexing', 90
            db.commit()
            if settings().embeddings_enabled:
                from .search import index_document
                index_document(db, document, source)
            db.refresh(job)
            if job.status == 'CANCELLED':
                raise Cancelled()
            document.status = 'REQUIRES_REVIEW' if issues else 'COMPLETED'
            document.review_status = 'pending'
            document.error = None
            job.status, job.stage, job.progress = document.status, 'Finished', 100
            job.error = None
            if usage:
                from .db import Audit
                db.add(Audit(document_id=document.id, user_id=document.owner_id, action='provider_usage', detail=usage | {'model': settings().llm_model, 'cost': 'not calculated; consult provider billing'}))
        except Cancelled:
            document.status = job.status = 'CANCELLED'
            job.stage = 'Cancelled'
        except Exception as exc:
            db.rollback()
            document, job = db.get(Document, document.id), db.get(Job, job_id)
            # Never persist exception payloads that can include document data or provider secrets.
            safe_types = (ValueError, TimeoutError)
            message = str(exc)[:300] if isinstance(exc, safe_types) and not settings().llm_api_key else type(exc).__name__ + ': processing failed; inspect configuration or retry'
            document.error = job.error = message
            document.status = job.status = 'FAILED'
            job.stage = 'Failed'
        document.duration = time.monotonic() - started
        job.updated_at = now()
        db.commit()


def recover_stale(db, owner_id):
    """Explicit recovery of jobs whose lease exceeded the configured hard time limit."""
    from datetime import timedelta
    cutoff = now() - timedelta(seconds=settings().job_timeout + 120)
    jobs = db.scalars(select(Job).join(Document).where(Document.owner_id == owner_id, Job.status == 'PROCESSING', Job.updated_at < cutoff)).all()
    for job in jobs:
        job.status = 'FAILED'
        job.error = 'Worker lease expired; manual retry required'
        document = db.get(Document, job.document_id)
        document.status, document.error = 'FAILED', job.error
    db.commit()
    return len(jobs)
