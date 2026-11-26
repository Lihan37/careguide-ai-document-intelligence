import time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from sqlalchemy import select, update, delete
from .db import Session, Document, Job, SourceUnit, Audit, now
from .config import settings
from .processing import ProcessingError, units
from .extraction import extract
from .gemini import GeminiExtractionError
from .reprocessing import (current_revision, effective_invoice, equivalent_invoice, evaluated_issues,
                           has_current_extraction, lock_document, publish)

_pool = None


def shutdown_executor():
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=True, cancel_futures=True)
        _pool = None


class JobStopped(Exception):
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
        try:
            document = processing_document(db, job)
            job.preserves_current = job.preserves_current or has_current_extraction(document)
            revision = None
            if job.preserves_current:
                # Older workers may already have marked the document as processing.
                if document.status not in ('COMPLETED', 'REQUIRES_REVIEW'):
                    document.status = 'REQUIRES_REVIEW' if document.issues else 'COMPLETED'
                    document.error = None
                revision = current_revision(document)
            else:
                document.status = 'PROCESSING'
                db.execute(delete(SourceUnit).where(SourceUnit.document_id == document.id))
            db.commit()
            source = []
            for position, unit in enumerate(units(Path(document.storage_path), document.file_type)):
                db.refresh(job)
                if job.status != 'PROCESSING':
                    raise JobStopped()
                if time.monotonic() - started > settings().job_timeout:
                    raise TimeoutError('Document processing time limit exceeded')
                unit['document_id'] = document.id
                source.append(unit)
                if not job.preserves_current:
                    db.add(SourceUnit(document_id=document.id, position=position, data=unit))
                job.pages_processed = position + 1
                job.total_pages = unit['total']
                job.progress = min(70, int(70 * (position + 1) / max(1, unit['total'])))
                job.updated_at = now()
                db.commit()
            if not source:
                raise ValueError('No readable content found')
            job.progress, job.stage = 75, 'Structured extraction'
            db.commit()
            invoice, evidence, extraction_issues, method, usage = extract(source)
            if usage:
                db.add(provider_audit(document, usage))
                db.commit()
            for unit in source:
                if unit['method'] != 'tesseract_ocr':
                    continue
                confidence = unit['ocr_confidence']
                if confidence is None or confidence < settings().ocr_review_threshold:
                    extraction_issues.append({'rule_id': 'ocr_review', 'severity': 'WARNING', 'page': unit['page'],
                                              'explanation': f'Check OCR text against the original on page {unit["page"]}.',
                                              'actual': confidence, 'expected': settings().ocr_review_threshold})
            if not job.preserves_current:
                job.stage, job.progress = 'Indexing', 90
                db.commit()
            document = processing_document(db, job)
            raw = invoice.model_dump(mode='json')
            effective = effective_invoice(document, raw)
            issues = evaluated_issues(db, document, effective, extraction_issues)
            result = {'raw': raw, 'evidence': evidence, 'method': method, 'sources': source,
                      'extraction_issues': extraction_issues, 'issues': issues, 'duration': time.monotonic() - started}
            job.status = 'REQUIRES_REVIEW' if issues else 'COMPLETED'
            job.stage, job.progress = 'Finished', 100
            job.error = None
            if not job.preserves_current:
                publish(db, document, result, effective, issues, replace_sources=False)
            elif equivalent_invoice(document, effective):
                job.candidate_status, job.stage = 'equivalent', 'Equivalent extraction; current result retained'
            else:
                job.candidate = result | {'base_revision': revision, 'corrected': document.corrected}
                job.candidate_status, job.stage = 'pending', 'Candidate ready for review'
        except JobStopped:
            db.rollback()
            return
        except Exception as exc:
            db.rollback()
            try:
                document = processing_document(db, job)
            except JobStopped:
                db.rollback()
                return
            # Never persist exception payloads that can include document data or provider secrets.
            safe_types = (ValueError, TimeoutError)
            cfg = settings()
            safe_message = isinstance(exc, (ProcessingError, GeminiExtractionError)) or (
                isinstance(exc, safe_types) and not (cfg.llm_api_key or cfg.gemini_api_key)
            )
            if isinstance(exc, GeminiExtractionError) and exc.usage:
                db.add(provider_audit(document, exc.usage))
            message = str(exc)[:300] if safe_message else type(exc).__name__ + ': processing failed; inspect configuration or retry'
            job.error, job.status, job.stage = message, 'FAILED', 'Failed'
            if not job.preserves_current and not has_current_extraction(document):
                document.error, document.status = message, 'FAILED'
                document.duration = time.monotonic() - started
        job.updated_at = now()
        db.commit()


def processing_document(db, job):
    document = lock_document(db, job.document_id)
    db.refresh(job)
    if job.status != 'PROCESSING':
        raise JobStopped()
    return document


def provider_audit(document, usage):
    detail = {'model': settings().llm_model, 'cost': 'not calculated; consult provider billing'} | usage
    return Audit(document_id=document.id, user_id=document.owner_id, action='provider_usage', detail=detail)


def recover_stale(db, owner_id):
    """Explicit recovery of jobs whose lease exceeded the configured hard time limit."""
    from datetime import timedelta
    cutoff = now() - timedelta(seconds=settings().job_timeout + 120)
    eligible = (Job.status == 'PROCESSING', Job.updated_at < cutoff)
    candidates = db.execute(select(Job.id, Job.document_id).join(Document).where(
        Document.owner_id == owner_id, *eligible).order_by(Job.document_id)).all()
    recovered = 0
    for job_id, document_id in candidates:
        document = lock_document(db, document_id)
        job = db.scalar(select(Job).where(Job.id == job_id, *eligible))
        if job is None:
            continue
        job.status = 'FAILED'
        job.stage = 'Failed'
        job.updated_at = now()
        job.error = 'Worker lease expired; manual retry required'
        if not job.preserves_current:
            document.status, document.error = 'FAILED', job.error
        recovered += 1
    db.commit()
    return recovered
