"""Opt-in cleanup of proven automation-owned records. Default is read-only dry run.

Historical development records without provenance are NEVER cleanup candidates.
Originals are quarantined with a recovery journal, not permanently removed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'services/api')]
from app.config import settings
from app.inspection import readonly_database, inventory


def cleanup_plan(cfg, ids=None):
    with readonly_database(cfg.database_url) as connection:
        records = inventory(connection, cfg)
        from sqlalchemy import text
        details = {}
        for record in records:
            if record['cleanup_eligible']:
                document_id = record['document_id']
                original = connection.execute(text('SELECT storage_path FROM documents WHERE id=:id'), {'id': document_id}).scalar_one()
                related = {table: connection.execute(text('SELECT count(*) FROM ' + table + ' WHERE document_id=:id'), {'id': document_id}).scalar_one() for table in ('source_units', 'processing_jobs', 'audit_logs', 'document_embeddings')}
                details[document_id] = {'original_path': original, 'related_records_to_delete': related}
        comparisons = connection.execute(text('SELECT id, document_ids FROM document_comparisons')).mappings().all()
    requested = set(ids or [])
    eligible = [row for row in records if row['cleanup_eligible'] and (not requested or row['document_id'] in requested)]
    if requested - {row['document_id'] for row in eligible}:
        raise ValueError('Requested IDs include unproven, manual, foreign-run or nonexistent records')
    eligible = [record | details[record['document_id']] for record in eligible]
    selected = {row['document_id'] for row in eligible}
    from app.inspection import json_value
    related_comparisons = [{'comparison_id': row['id'], 'document_ids': json_value(row['document_ids']), 'blocks_cleanup': bool(set(json_value(row['document_ids'])) - selected)} for row in comparisons if set(json_value(row['document_ids'])) & selected]
    return {'mode': 'dry-run', 'environment': cfg.app_env, 'run_id': cfg.automation_run_id or None, 'would_delete': eligible, 'related_comparisons': related_comparisons, 'retained_records': len(records) - len(eligible), 'original_file_action': 'Move to run-owned quarantine with a recovery journal; no permanent file deletion'}


def apply_plan(cfg, plan, ids, confirmation):
    if cfg.app_env not in {'test', 'evaluation'} or not ids or confirmation != 'DELETE AUTOMATED RECORDS ' + cfg.automation_run_id:
        raise ValueError('Deletion requires an isolated environment, explicit IDs and exact run-specific confirmation')
    if not plan['would_delete']:
        raise ValueError('No proven automation records selected')
    if not cfg.database_url.startswith('sqlite'):
        raise ValueError('Optional cleanup currently supports isolated SQLite only')
    refreshed = cleanup_plan(cfg, ids)
    if {row['document_id'] for row in refreshed['would_delete']} != {row['document_id'] for row in plan['would_delete']}:
        raise ValueError('Cleanup provenance changed; rerun dry-run')
    from sqlalchemy import select, delete
    from app.db import Session, Document, SourceUnit, Job, Audit, Comparison, Embedding
    from scripts.runtime_env import verify_owned_directory
    root = verify_owned_directory(cfg.runtime_root, cfg.automation_run_id, cfg.app_env, cfg.automation_kind)
    operation = root / 'quarantine' / str(uuid.uuid4())
    selected = {row['document_id'] for row in plan['would_delete']}
    moves = []
    committed = False
    journal = {'state': 'planned', 'document_ids': sorted(selected), 'files': moves}
    with Session() as db:
        if db.scalar(select(Job.id).where(Job.status.in_(['QUEUED', 'PROCESSING'])).limit(1)):
            raise ValueError('Stop active processing before optional cleanup')
        # Refuse deleting history still referenced by any unselected record.
        for comparison in db.scalars(select(Comparison)):
            references = set(comparison.document_ids)
            if references & selected and references - selected:
                raise ValueError('Comparison also references retained records; cleanup refused')
        for document in db.scalars(select(Document).where(Document.id.not_in(selected))):
            if any(issue.get('related_document_id') in selected for issue in document.issues):
                raise ValueError('A retained document references these records; cleanup refused')
        documents = db.scalars(select(Document).where(Document.id.in_(selected))).all()
        if len(documents) != len(selected):
            raise ValueError('Cleanup plan changed; rerun dry-run')
        for document in documents:
            source = Path(document.storage_path).resolve()
            if not source.is_relative_to(root) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != document.checksum:
                raise ValueError('Original path/checksum changed; cleanup refused')
            moves.append({'source': str(source), 'quarantine': str(operation / source.name), 'document_id': document.id})
        operation.mkdir(parents=True, exist_ok=False)
        journal_path = operation / 'operation.json'
        journal_path.write_text(json.dumps(journal, indent=2), encoding='utf-8')
        try:
            for move in moves:
                shutil.move(move['source'], move['quarantine'])
            for model in (Embedding, SourceUnit, Job, Audit):
                db.execute(delete(model).where(model.document_id.in_(selected)))
            for comparison in db.scalars(select(Comparison)):
                if set(comparison.document_ids) & selected:
                    db.delete(comparison)
            db.execute(delete(Document).where(Document.id.in_(selected)))
            db.commit()
            committed = True
            journal['state'] = 'committed'
            journal_path.write_text(json.dumps(journal, indent=2), encoding='utf-8')
        except Exception:
            db.rollback()
            if not committed:
                for move in moves:
                    if Path(move['quarantine']).exists():
                        shutil.move(move['quarantine'], move['source'])
                journal['state'] = 'rolled-back'
                journal_path.write_text(json.dumps(journal, indent=2), encoding='utf-8')
            raise
    return {'deleted_document_ids': sorted(selected), 'recovery_journal': str(journal_path), 'originals_retained_in_quarantine': True}


def recover_operation(cfg, journal_path):
    from scripts.runtime_env import verify_owned_directory
    from sqlalchemy import text
    root = verify_owned_directory(cfg.runtime_root, cfg.automation_run_id, cfg.app_env, cfg.automation_kind)
    journal_path = journal_path.resolve()
    if not journal_path.is_relative_to(root / 'quarantine') or journal_path.name != 'operation.json':
        raise ValueError('Recovery journal must belong to this isolated run')
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    with readonly_database(cfg.database_url) as connection:
        existing = {row[0] for row in connection.execute(text('SELECT id FROM documents'))}
    selected = set(journal['document_ids'])
    if existing & selected and not selected.issubset(existing):
        raise ValueError('Mixed record state; manual inspection required')
    for move in journal['files']:
        source, quarantine = Path(move['source']).resolve(), Path(move['quarantine']).resolve()
        if not source.is_relative_to(root) or not quarantine.is_relative_to(journal_path.parent):
            raise ValueError('Unsafe recovery path')
    if selected.issubset(existing):
        for move in journal['files']:
            source, quarantine = Path(move['source']), Path(move['quarantine'])
            if quarantine.exists():
                if source.exists():
                    raise ValueError('Original already exists; refusing overwrite')
                shutil.move(quarantine, source)
        journal['state'] = 'rolled-back'
    else:
        journal['state'] = 'committed'
    journal_path.write_text(json.dumps(journal, indent=2), encoding='utf-8')
    return {'state': journal['state'], 'journal': str(journal_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--environment', choices=['test', 'evaluation'])
    parser.add_argument('--run-id')
    parser.add_argument('--ids', nargs='+')
    parser.add_argument('--confirm')
    parser.add_argument('--recover', type=Path)
    args = parser.parse_args()
    if args.environment or args.run_id:
        if not args.environment or not args.run_id:
            parser.error('--environment and --run-id must be provided together; no development fallback')
        from scripts.runtime_env import existing_run_environment
        os.environ.update(existing_run_environment(args.environment, args.run_id))
    cfg = settings()
    if args.recover:
        if args.confirm != 'RECOVER AUTOMATED FILES ' + cfg.automation_run_id or cfg.app_env == 'development':
            raise SystemExit('Recovery requires an isolated run and explicit confirmation')
        print(json.dumps(recover_operation(cfg, args.recover), indent=2))
        return
    plan = cleanup_plan(cfg, args.ids)
    print(json.dumps(plan, indent=2))
    if args.apply:
        print(json.dumps(apply_plan(cfg, plan, args.ids, args.confirm), indent=2))


if __name__ == '__main__':
    main()
