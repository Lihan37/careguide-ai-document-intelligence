import hashlib
import json
import time
import logging
from datetime import timezone
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import select, func, or_, text as sqltext
from .config import settings, request_environment_matches
from .db import Session, User, Document, SourceUnit, Job, Audit, Comparison, get_db, uid
from .security import current_user, reviewer, password_check, password_hash, token
from .schemas import Login, Invoice, Correction, Review, CompareRequest, SemanticRequest
from .processing import EXTENSIONS, signature, ProcessingError, ocr_available
from .validation import validate, duplicates
from .jobs import dispatch, recover_stale
from .comparison import compare, mapped_invoice
from .limits import RequestBodyLimit

logger = logging.getLogger('careguide')


@asynccontextmanager
async def lifespan(app):
    cfg = settings()
    if len(cfg.session_secret) < 32 or len(cfg.demo_password) < 12:
        raise RuntimeError('Set SESSION_SECRET (32+ characters) and DEMO_PASSWORD (12+ characters); see scripts/setup-local.ps1')
    with Session() as db:
        if not db.scalar(select(User).where(User.username == cfg.demo_username)):
            db.add(User(username=cfg.demo_username, password_hash=password_hash(cfg.demo_password), role='reviewer'))
            db.commit()
    try:
        yield
    finally:
        from .jobs import shutdown_executor
        shutdown_executor()


app = FastAPI(title='CareGuide Document Intelligence', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings().cors_origin], allow_credentials=True, allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Content-Type', 'X-CareGuide-Environment', 'X-CareGuide-Run'])
app.add_middleware(RequestBodyLimit)
_requests = defaultdict(deque)


@app.middleware('http')
async def guard(request: Request, call_next):
    if not request_environment_matches(settings(), request.headers.get('x-careguide-environment'), request.headers.get('x-careguide-run')):
        return JSONResponse({'detail': 'Automation environment/run does not match this server'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method in {'POST', 'PATCH', 'DELETE'} and origin and origin != settings().cors_origin:
        return JSONResponse({'detail': 'Origin rejected'}, status_code=403)
    # Bounded process-local rate limiter; production proxy must enforce shared limits.
    current = time.monotonic()
    key = (request.client.host if request.client else 'unknown', 'login' if request.url.path == '/api/auth/login' else 'api')
    queue = _requests[key]
    while queue and queue[0] < current - 60:
        queue.popleft()
    if len(queue) >= (10 if key[1] == 'login' else 300):
        return JSONResponse({'detail': 'Rate limit exceeded'}, status_code=429, headers={'Retry-After': '60'})
    queue.append(current)
    if len(_requests) > 10000:
        for old in list(_requests)[:5000]:
            if not _requests[old] or _requests[old][-1] < current - 60:
                del _requests[old]
    length = request.headers.get('content-length')
    if length and not length.isdigit():
        return JSONResponse({'detail': 'Invalid content length'}, status_code=400)
    if length and int(length) > settings().max_file_mb * settings().max_upload_files * 1024 * 1024 + 100000:
        return JSONResponse({'detail': 'Request body too large'}, status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logger.error('request_failed type=%s path=%s', type(exc).__name__, request.url.path)
    return JSONResponse({'detail': 'Internal operation failed'}, status_code=500)


def owned(db, document_id, user):
    document = db.get(Document, document_id)
    if not document or document.owner_id != user.id:
        raise HTTPException(404, 'Document not found')
    return document


def timestamp(value):
    # SQLite drops offset metadata; all stored application timestamps originate in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def summary(document):
    return {'id': document.id, 'filename': document.filename, 'file_type': document.file_type, 'size': document.size, 'checksum': document.checksum, 'uploaded_at': timestamp(document.uploaded_at), 'status': document.status, 'invoice_number': document.invoice_number, 'supplier': document.supplier, 'page_count': document.page_count, 'sheet_count': document.sheet_count, 'duration': document.duration, 'error': document.error, 'review_status': document.review_status, 'issue_count': len(document.issues)}


def job_view(job):
    result = {k: getattr(job, k) for k in ('id', 'document_id', 'status', 'stage', 'progress', 'pages_processed', 'total_pages', 'retries', 'error', 'created_at', 'updated_at')}
    return result | {'created_at': timestamp(job.created_at), 'updated_at': timestamp(job.updated_at)}


def audit(db, user, document_id, action, detail):
    db.add(Audit(user_id=user.id, document_id=document_id, action=action, detail=detail))


@app.post('/api/auth/login')
def login(body: Login, response: Response, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not password_check(body.password, user.password_hash):
        raise HTTPException(401, 'Invalid credentials')
    response.set_cookie('careguide_session', token(user.id), httponly=True, samesite='lax', max_age=28800, secure=settings().cors_origin.startswith('https:'))
    return {'username': user.username, 'role': user.role}


@app.post('/api/auth/logout')
def logout(response: Response):
    response.delete_cookie('careguide_session')
    return {'ok': True}


@app.get('/api/auth/me')
def me(user=Depends(current_user)):
    return {'username': user.username, 'role': user.role}


@app.get('/api/health')
def health():
    return {'status': 'ok'}


@app.get('/api/environment')
def environment_identity():
    return settings().provenance


@app.get('/api/ready')
def ready(db=Depends(get_db)):
    try:
        db.execute(sqltext('SELECT 1'))
        if settings().execution_mode == 'celery':
            import redis
            redis.Redis.from_url(settings().redis_url, socket_connect_timeout=2).ping()
    except Exception:
        raise HTTPException(503, 'Database or broker unavailable')
    return {'status': 'ready', 'worker_liveness': 'Inspect processing jobs; readiness checks database and broker only'}


@app.get('/api/settings')
def configuration(user=Depends(current_user)):
    cfg = settings()
    return {'environment': cfg.app_env, 'execution_mode': cfg.execution_mode, 'extraction_mode': cfg.extraction_mode, 'ai_available': bool(cfg.llm_api_key), 'semantic_available': bool(cfg.llm_api_key and cfg.embeddings_enabled and cfg.database_url.startswith('postgresql')), 'ocr_available': ocr_available(), 'database': 'postgresql' if cfg.database_url.startswith('postgresql') else 'sqlite', 'max_file_mb': cfg.max_file_mb, 'max_upload_files': cfg.max_upload_files, 'max_pages': cfg.max_pages, 'llm_model': cfg.llm_model, 'embedding_model': cfg.embedding_model, 'notice': 'Deterministic demonstration parsing is not AI. AI and semantic search require explicitly configured credentials.'}


@app.post('/api/documents/upload', status_code=202)
async def upload(files: list[UploadFile] = File(...), user=Depends(current_user), db=Depends(get_db)):
    cfg = settings()
    if not files or len(files) > cfg.max_upload_files:
        raise HTTPException(422, f'Upload between 1 and {cfg.max_upload_files} files')
    results = []
    for upload_file in files:
        name = (upload_file.filename or 'unnamed').replace('\\', '/').split('/')[-1][:255]
        extension = Path(name).suffix.lower()
        path = Path(cfg.storage_dir).resolve() / (uid() + extension)
        try:
            if extension not in EXTENSIONS:
                raise ProcessingError('Unsupported file extension')
            size, checksum = 0, hashlib.sha256()
            with path.open('xb') as target:
                while chunk := await upload_file.read(1024 * 1024):
                    size += len(chunk)
                    if size > cfg.max_file_mb * 1024 * 1024:
                        raise ProcessingError('File exceeds configured size limit')
                    checksum.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise ProcessingError('Empty file')
            signature(path, extension)
            document = Document(owner_id=user.id, filename=name, file_type=extension, size=size, checksum=checksum.hexdigest(), storage_path=str(path))
            db.add(document)
            db.flush()
            job = Job(document_id=document.id)
            db.add(job)
            audit(db, user, document.id, 'uploaded', {'filename': name, 'size': size} | cfg.provenance)
            db.commit()
            try:
                dispatch(job.id)
            except Exception:
                document.status = job.status = 'FAILED'
                document.error = job.error = 'Worker dispatch unavailable; start worker/broker and retry'
                db.commit()
            results.append({'filename': name, 'document_id': document.id, 'job_id': job.id, 'status': document.status})
        except (ProcessingError, OSError, ValueError) as exc:
            db.rollback()
            path.unlink(missing_ok=True)
            results.append({'filename': name, 'error': str(exc)[:300]})
        finally:
            await upload_file.close()
    return {'results': results}


@app.get('/api/documents')
@app.get('/api/search')
def documents(q: str = Query('', max_length=500), status: str | None = None, file_type: str | None = None, sort: str = 'newest', page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user=Depends(current_user), db=Depends(get_db)):
    statement = select(Document).where(Document.owner_id == user.id)
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        statement = statement.where(or_(*[column.ilike(pattern, escape='\\') for column in (Document.filename, Document.invoice_number, Document.supplier, Document.text)], Document.raw.cast(__import__('sqlalchemy').Text).ilike(pattern, escape='\\'), Document.corrected.cast(__import__('sqlalchemy').Text).ilike(pattern, escape='\\')))
    if status:
        statement = statement.where(Document.status == status)
    if file_type:
        statement = statement.where(Document.file_type == file_type)
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    rows = db.scalars(statement.order_by(Document.uploaded_at.asc() if sort == 'oldest' else Document.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size))
    items = []
    for row in rows:
        index = row.text.casefold().find(q.casefold()) if q else 0
        items.append(summary(row) | {'excerpt': row.text[max(0, index - 80):max(0, index - 80) + 250], 'highlight': q})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size}


@app.get('/api/dashboard')
def dashboard(user=Depends(current_user), db=Depends(get_db)):
    counts = dict(db.execute(select(Document.status, func.count()).where(Document.owner_id == user.id).group_by(Document.status)).all())
    types = dict(db.execute(select(Document.file_type, func.count()).where(Document.owner_id == user.id).group_by(Document.file_type)).all())
    return {'total': sum(counts.values()), 'statuses': counts, 'types': types}


@app.get('/api/documents/{document_id}')
def detail(document_id: str, user=Depends(current_user), db=Depends(get_db)):
    document = owned(db, document_id, user)
    return summary(document) | {'text': document.text, 'raw': document.raw, 'corrected': document.corrected, 'effective': document.raw | document.corrected, 'evidence': document.evidence, 'issues': document.issues, 'extraction_method': document.extraction_method, 'sources': [row.data for row in db.scalars(select(SourceUnit).where(SourceUnit.document_id == document_id).order_by(SourceUnit.position))], 'history': [job_view(row) for row in db.scalars(select(Job).where(Job.document_id == document_id).order_by(Job.created_at.desc()))], 'audit': [{'action': row.action, 'detail': row.detail, 'user_id': row.user_id, 'created_at': timestamp(row.created_at)} for row in db.scalars(select(Audit).where(Audit.document_id == document_id).order_by(Audit.created_at.desc()))]}


@app.get('/api/documents/{document_id}/status')
def document_status(document_id: str, user=Depends(current_user), db=Depends(get_db)):
    document = owned(db, document_id, user)
    job = db.scalar(select(Job).where(Job.document_id == document_id).order_by(Job.created_at.desc()))
    return summary(document) | {'job': job_view(job) if job else None}


@app.get('/api/documents/{document_id}/extraction')
def extraction(document_id: str, user=Depends(current_user), db=Depends(get_db)):
    document = owned(db, document_id, user)
    return {'original': document.raw, 'corrections': document.corrected, 'effective': document.raw | document.corrected, 'evidence': document.evidence, 'method': document.extraction_method}


@app.get('/api/documents/{document_id}/validation')
def validation(document_id: str, user=Depends(current_user), db=Depends(get_db)):
    document = owned(db, document_id, user)
    severities = {i['severity'] for i in document.issues}
    outcome = next((s for s in ('FAILED', 'REQUIRES_REVIEW', 'WARNING') if s in severities), 'PASSED') if document.raw else 'REQUIRES_REVIEW'
    return {'outcome': outcome, 'issues': document.issues}


@app.get('/api/documents/{document_id}/source')
def source(document_id: str, page: int | None = Query(None, ge=1), user=Depends(current_user), db=Depends(get_db)):
    document = owned(db, document_id, user)
    if page is not None:
        if document.file_type != '.pdf':
            raise HTTPException(422, 'Page preview is available for PDF documents')
        import pymupdf
        with pymupdf.open(document.storage_path) as pdf:
            if page > pdf.page_count:
                raise HTTPException(404, 'Page not found')
            source_page = pdf[page - 1]
            scale = min(1.0, (settings().max_image_pixels / max(1, source_page.rect.width * source_page.rect.height)) ** 0.5)
            image = source_page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return Response(image.tobytes('png'), media_type='image/png')
    media = {'.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.tif': 'image/tiff', '.tiff': 'image/tiff'}.get(document.file_type, 'application/octet-stream')
    return FileResponse(document.storage_path, media_type=media, filename=document.filename, content_disposition_type='inline' if document.file_type == '.pdf' else 'attachment')


@app.post('/api/documents/{document_id}/reprocess', status_code=202)
def reprocess(document_id: str, user=Depends(reviewer), db=Depends(get_db)):
    document = owned(db, document_id, user)
    if document.status in {'QUEUED', 'PROCESSING'}:
        raise HTTPException(409, 'Document already queued or processing')
    previous = db.scalar(select(Job).where(Job.document_id == document_id).order_by(Job.created_at.desc()))
    retries = previous.retries + 1 if previous else 1
    if retries > 3:
        raise HTTPException(409, 'Retry limit (3) reached; upload a corrected source')
    job = Job(document_id=document_id, retries=retries)
    db.add(job)
    document.status = 'QUEUED'
    document.error = None
    audit(db, user, document_id, 'reprocess', {'retry': retries})
    db.commit()
    try:
        dispatch(job.id)
    except Exception:
        document.status = job.status = 'FAILED'
        job.error = document.error = 'Worker dispatch unavailable'
        db.commit()
    return job_view(job)


@app.patch('/api/documents/{document_id}/corrections')
def corrections(document_id: str, body: Correction, user=Depends(reviewer), db=Depends(get_db)):
    document = owned(db, document_id, user)
    if document.status not in {'COMPLETED', 'REQUIRES_REVIEW'}:
        raise HTTPException(409, 'Wait for successful extraction before correcting')
    try:
        invoice = Invoice.model_validate(document.raw | document.corrected | body.fields)
    except ValidationError as exc:
        raise HTTPException(422, json.loads(exc.json(include_url=False)))
    original = document.raw | document.corrected
    effective = invoice.model_dump(mode='json')
    audit(db, user, document_id, 'correction', {'reason': body.reason, 'changes': {k: {'old': original.get(k), 'new': effective.get(k)} for k in body.fields}})
    document.corrected = document.corrected | {k: effective[k] for k in body.fields}
    document.invoice_number, document.supplier = invoice.invoice_number, invoice.supplier_name
    ocr_warnings = [issue for issue in document.issues if issue['rule_id'] == 'ocr_review']
    document.issues = validate(invoice) + duplicates(document, db.scalars(select(Document).where(Document.owner_id == user.id)).all(), effective) + ocr_warnings
    document.status = 'REQUIRES_REVIEW' if document.issues else 'COMPLETED'
    document.review_status = 'pending'
    db.commit()
    return {'effective': effective, 'issues': document.issues, 'original': document.raw}


@app.get('/api/jobs')
def jobs(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100), user=Depends(current_user), db=Depends(get_db)):
    base = select(Job).join(Document).where(Document.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    return {'items': [job_view(row) for row in db.scalars(base.order_by(Job.created_at.desc()).offset((page - 1) * page_size).limit(page_size))], 'total': total}


@app.get('/api/jobs/{job_id}')
def job_detail(job_id: str, user=Depends(current_user), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    owned(db, job.document_id, user)
    return job_view(job)


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id: str, user=Depends(reviewer), db=Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, 'Job not found')
    document = owned(db, job.document_id, user)
    if job.status not in {'QUEUED', 'PROCESSING'}:
        raise HTTPException(409, 'Only queued or active jobs can be cancelled')
    job.status = document.status = 'CANCELLED'
    audit(db, user, document.id, 'cancelled', {'job_id': job.id})
    db.commit()
    return job_view(job)


@app.post('/api/jobs/recover-stale')
def recover(user=Depends(reviewer), db=Depends(get_db)):
    return {'recovered': recover_stale(db, user.id)}


@app.get('/api/review-queue')
def review_queue(q: str = Query('', max_length=500), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user=Depends(current_user), db=Depends(get_db)):
    statement = select(Document).where(Document.owner_id == user.id, Document.status == 'REQUIRES_REVIEW', Document.review_status != 'approved')
    if q:
        pattern = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        statement = statement.where(or_(Document.filename.ilike(pattern, escape='\\'), Document.invoice_number.ilike(pattern, escape='\\'), Document.supplier.ilike(pattern, escape='\\')))
    total = db.scalar(select(func.count()).select_from(statement.subquery()))
    return {'items': [summary(row) | {'issues': row.issues} for row in db.scalars(statement.order_by(Document.uploaded_at.desc()).offset((page - 1) * page_size).limit(page_size))], 'total': total}


@app.post('/api/reviews/{document_id}/resolve')
def resolve(document_id: str, body: Review, user=Depends(reviewer), db=Depends(get_db)):
    document = owned(db, document_id, user)
    if document.status not in {'COMPLETED', 'REQUIRES_REVIEW'}:
        raise HTTPException(409, 'Document extraction is not ready')
    if body.decision == 'approved' and any(i['severity'] in {'FAILED', 'REQUIRES_REVIEW'} for i in document.issues):
        raise HTTPException(409, 'Correct failed arithmetic and missing required fields before approval')
    document.review_status = body.decision
    audit(db, user, document_id, 'review_decision', body.model_dump())
    db.commit()
    return {'review_status': document.review_status, 'issues_retained': True}


@app.post('/api/comparisons', status_code=201)
def create_comparison(body: CompareRequest, user=Depends(reviewer), db=Depends(get_db)):
    if len(set(body.document_ids)) != len(body.document_ids):
        raise HTTPException(422, 'Select distinct documents')
    docs = [owned(db, id, user) for id in body.document_ids]
    values, evidence = {}, {}
    for document in docs:
        if document.status not in {'COMPLETED', 'REQUIRES_REVIEW'}:
            raise HTTPException(409, 'Comparison requires processed documents')
        values[document.id], evidence[document.id] = document.raw | document.corrected, document.evidence
        if body.mappings.get(document.id):
            sources = [row.data for row in db.scalars(select(SourceUnit).where(SourceUnit.document_id == document.id))]
            sheet = body.sheets.get(document.id)
            source = next((s for s in sources if s.get('rows') and (sheet is None or s.get('sheet') == sheet)), None)
            if source is None:
                raise HTTPException(422, 'Spreadsheet sheet not found')
            try:
                values[document.id], evidence[document.id] = mapped_invoice(source, body.mappings[document.id], body.rows.get(document.id, 2))
            except ValueError as exc:
                raise HTTPException(422, str(exc))
    results = []
    left = docs[0]
    for right in docs[1:]:
        fields = compare(values[left.id], values[right.id], evidence[left.id], evidence[right.id])
        results.append({'left_id': left.id, 'right_id': right.id, 'left_filename': left.filename, 'right_filename': right.filename, 'review_status': 'requires_review' if any(f['status'] != 'MATCHED' for f in fields) else 'matched', 'fields': fields})
        if any(f['status'] == 'MISMATCHED' for f in fields):
            for document in (left, right):
                document.issues = document.issues + [{'rule_id': 'comparison_mismatch', 'severity': 'WARNING', 'explanation': 'Cross-document fields differ; inspect saved comparison'}]
                document.status, document.review_status = 'REQUIRES_REVIEW', 'pending'
    comparison = Comparison(owner_id=user.id, document_ids=body.document_ids, results=results)
    db.add(comparison)
    db.flush()
    audit(db, user, left.id, 'comparison', {'comparison_id': comparison.id, 'mappings': body.mappings, 'rows': body.rows, 'sheets': body.sheets})
    db.commit()
    return {'id': comparison.id, 'results': results}


@app.get('/api/comparisons')
def comparisons(user=Depends(current_user), db=Depends(get_db)):
    return {'items': [{'id': c.id, 'document_ids': c.document_ids, 'created_at': timestamp(c.created_at)} for c in db.scalars(select(Comparison).where(Comparison.owner_id == user.id).order_by(Comparison.created_at.desc()).limit(100))]}


@app.get('/api/comparisons/{comparison_id}')
def comparison_detail(comparison_id: str, user=Depends(current_user), db=Depends(get_db)):
    record = db.get(Comparison, comparison_id)
    if not record or record.owner_id != user.id:
        raise HTTPException(404, 'Comparison not found')
    return {'id': record.id, 'results': record.results}


@app.post('/api/search/semantic')
def semantic_search(body: SemanticRequest, user=Depends(current_user), db=Depends(get_db)):
    from .search import semantic
    try:
        return {'items': semantic(db, user.id, body.query, body.limit)}
    except ValueError as exc:
        raise HTTPException(503, str(exc))


@app.get('/api/evaluation/results')
def evaluation(user=Depends(current_user)):
    cfg = settings()
    from .config import PROJECT_ROOT
    path = PROJECT_ROOT / 'data/evaluation/latest-results.json' if cfg.app_env == 'development' else Path(cfg.runtime_root) / 'evaluation-results.json'
    if not path.exists() and cfg.app_env == 'development':
        path = PROJECT_ROOT / 'docs/evaluation-results.json'  # Historical checked-in report.
    if not path.exists():
        return {'status': 'not_run', 'notice': 'Run scripts/evaluate.py to generate actual results'}
    return json.loads(path.read_text(encoding='utf-8'))
