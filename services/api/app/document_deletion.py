"""Remove a document and the records that explicitly depend on it."""
from hashlib import file_digest
import logging
from os.path import samestat
from pathlib import Path
from stat import S_ISREG
from uuid import UUID

from sqlalchemy import cast, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from .config import PROJECT_ROOT, settings
from .db import Audit, Comparison, Document, Embedding, Job, SourceUnit
from .reprocessing import ACTIVE_JOB


logger = logging.getLogger('careguide')


def deletion_state(db, document):
    if db.get_bind().dialect.name == 'postgresql':
        dependent = cast(Comparison.document_ids, JSONB).contains([document.id])
    else:
        members = func.json_each(Comparison.document_ids).table_valued('value')
        dependent = exists(select(1).select_from(members).where(members.c.value == document.id))
    comparisons = db.execute(select(Comparison.id, Comparison.owner_id).where(dependent).order_by(Comparison.id)).all()
    active = db.scalar(select(Job.id).where(Job.document_id == document.id,
                                           or_(Job.status.in_(ACTIVE_JOB), Job.worker_active)).limit(1))
    return {'filename': document.filename, 'active_processing': active is not None,
            'comparison_ids': [row.id for row in comparisons if row.owner_id == document.owner_id],
            'blocked': any(row.owner_id != document.owner_id for row in comparisons)}


def remove_document(db, document, comparison_ids):
    comparisons_deleted = 0
    if comparison_ids:
        comparisons_deleted = db.execute(delete(Comparison).where(
            Comparison.id.in_(comparison_ids), Comparison.owner_id == document.owner_id)).rowcount
    for model in (SourceUnit, Embedding, Job, Audit):
        db.execute(delete(model).where(model.document_id == document.id))
    db.delete(document)
    db.commit()
    return comparisons_deleted


def clean_original(db, document):
    """Run after commit. Remove only a managed original with no retained references."""
    path = Path(document.storage_path)
    try:
        root = Path(settings().storage_dir).resolve(strict=True)
        if (not path.is_absolute() or path.parent.resolve() != root or path.suffix != document.file_type
                or str(UUID(path.stem, version=4)) != path.stem
                or root.is_relative_to((PROJECT_ROOT / 'sample-data').resolve())):
            return 'retained', 'The original is outside the managed upload layout and was retained.'

        original = path.lstat()
        if not S_ISREG(original.st_mode) or original.st_nlink != 1:
            return 'retained', 'The original is linked or has an unsupported file type and was retained.'
        # Uploads always allocate a fresh UUID path. Check aliases, including
        # references from other owners, against the committed database state.
        canonical = path.resolve()
        if any(Path(reference).resolve() == canonical for reference in db.scalars(select(Document.storage_path))):
            return 'shared', 'The original is still referenced by another document and was retained.'
        with path.open('rb') as stored:
            digest = file_digest(stored, 'sha256').hexdigest()
        current = path.lstat()
        if (not samestat(original, current) or current.st_nlink != 1 or original.st_mtime_ns != current.st_mtime_ns
                or original.st_size != current.st_size or digest != document.checksum):
            return 'retained', 'The original changed or did not match the upload checksum and was retained.'
        path.unlink()
        return 'removed', None
    except FileNotFoundError:
        return 'missing', 'The original file was already missing.'
    except (OSError, RuntimeError, ValueError, SQLAlchemyError) as exc:
        logger.warning('document_original_cleanup_failed document_id=%s type=%s', document.id, type(exc).__name__)
        return 'retained', 'The database deletion succeeded, but the original file could not be cleaned up.'
