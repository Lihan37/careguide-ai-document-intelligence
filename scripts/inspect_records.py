"""Create a private, read-only record inventory and optionally verify a snapshot."""
import argparse
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'services/api')]
from app.config import settings
from app.inspection import readonly_database, inventory, logical_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compare-snapshot', type=Path)
    args = parser.parse_args()
    baseline = json.loads(args.compare_snapshot.read_text(encoding='utf-8')) if args.compare_snapshot else None
    cfg = settings()
    output = ROOT / 'data/inspection' if cfg.app_env == 'development' else Path(cfg.runtime_root) / 'inspection'
    output.mkdir(parents=True, exist_ok=True)
    with readonly_database(cfg.database_url) as connection:
        records = inventory(connection, cfg)
        snapshot = logical_snapshot(connection)
    (output / 'records-report.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    with (output / 'records-report.csv').open('w', newline='', encoding='utf-8-sig') as target:
        writer = csv.DictWriter(target, fieldnames=list(records[0]) if records else ['filename', 'document_id', 'uploaded_at', 'status', 'likely_source', 'test_or_evaluation_run', 'cleanup_eligible'])
        writer.writeheader()
        writer.writerows(records)
    snapshot_path = output / 'current-snapshot.json'
    if args.compare_snapshot and args.compare_snapshot.resolve() == snapshot_path.resolve():
        snapshot_path = output / 'comparison-snapshot.json'
    snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str), encoding='utf-8')
    report = {'environment': cfg.app_env, 'records': len(records), 'cleanup_eligible': sum(row['cleanup_eligible'] for row in records), 'report': str(output / 'records-report.csv')}
    if args.compare_snapshot:
        before = baseline
        changed_tables = [name for name, value in before['table_hashes'].items() if snapshot['table_hashes'].get(name) != value]
        unchanged_files = snapshot['files'] == before['files']
        report.update(changed_tables=changed_tables, original_files_unchanged=unchanged_files, database_unchanged=not changed_tables)
        (output / 'preservation-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if changed_tables or not unchanged_files:
            print(json.dumps(report, indent=2))
            raise SystemExit('Development data changed; inspect the preservation report')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
