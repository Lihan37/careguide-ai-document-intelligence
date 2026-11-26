# Development document cleanup

The final audit started from `e8fc3e3` on `main`. The running Windows development workspace used SQLite at `data/careguide.db` and private originals under `data/uploads/`. The API and frontend used loopback ports 8000 and 3000.

## Provenance

| Classification | Before | Removed | Retained |
| --- | ---: | ---: | ---: |
| CONFIRMED_TEST | 19 | 7 | 12 |
| MANUAL_UPLOAD | 3 | 0 | 3 |
| UNCERTAIN | 0 | 0 | 0 |
| Total | 22 | 7 | 15 |

Four archived Playwright launches and successful completion logs independently established when each browser run occurred. The development database contained the exact expected upload sequence within each window, matching upload audits and scripted correction, review and comparison activity. Each original matched its stored checksum. This evidence identified the historical Playwright runs. The three owner-identified manual files sat outside those windows.

The cleanup selected two `layout-invoice.pdf` records, two `corrupted.pdf` records, one `tax-layout-invoice.pdf`, one `invoice.pdf` and one `duplicate.pdf`. Twelve confirmed test records were retained because existing comparison snapshots or retained document references use them. All four comparison snapshots and all retained row values, audits, processing histories and original checksums matched the backup.

## Backup and verification

A timestamped private SQLite online backup and the full set of 22 original uploads were verified before applying the manifest. The cleanup checked database integrity and foreign keys, revalidated the manifest under a write lock, removed only selected rows and their dependents in a transaction, and quarantined the originals after commit. The original source-code fixtures stayed in the repository.

The developer's ignored audit directory under `data/inspection/final-audit-<timestamp>/` contains `initial-baseline.json`, `cleanup-manifest.json`, the verified `backup/`, the `quarantine/` and `operation.json`. Its private `docs/development-document-cleanup-report.md` records each document ID, exact original path, owner, UTC upload time, status, classification, evidence, retained references and dependent row IDs.

Authenticated API and browser checks observed the same 15 document IDs. The targeted IDs returned 404 and were absent from keyword results. Manual uploads remained readable and their original downloads matched the backup. Both manual invoices retained four line items and passing Decimal validation. Semantic retrieval was verified separately on the disposable PostgreSQL stack.

The generic cleanup command still limits applying cleanup to positively identified isolated test or evaluation runs. See [environment isolation](testing.md#optional-cleanup) for its normal use.
