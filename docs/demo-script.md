# Recorded walkthrough: 5–8 minutes

Record the actual local app after reviewing the README. No recording was created by this session. Show the capability banner and explain missing services honestly. Use synthetic files only; hide `.env` and credentials from recording. Screen recording can use Windows Snipping Tool or another local recorder at no service cost.

| Time | Demonstration |
| --- | --- |
| 0:00–0:45 | Introduce manual financial-document reconciliation, the seven assessment tasks and architecture. State whether extraction is deterministic demo or configured live AI. Show current service/OCR availability in Settings. |
| 0:45–1:45 | Upload `sample-data/invoice.pdf` and `accounting.xlsx` together. Show real upload acknowledgment, processing jobs, page/sheet counts and the structured output. Background work may finish quickly on tiny fixtures; do not fabricate waiting/progress. |
| 1:45–2:30 | Open invoice source preview and field evidence. Show exact arithmetic: 2 × 100 = 200; 200 + 20 = 220. Explain decimal strings and Decimal calculation. XLSX has two sheets, original coordinates and an intentional total of 225. |
| 2:30–3:30 | Select invoice PDF and accounting XLSX in Document Comparison. Show the total difference of 5, provenance and review warning. Optionally demonstrate spreadsheet column mapping and data-row selection. Select another PDF to show PDF-to-PDF comparison too. |
| 3:30–4:30 | Upload `incorrect-total.pdf` (250 instead of 220). Open Validation, inspect expected/actual/difference; go to Corrections and change total to 220 with a reason. Show original 250 and corrected 220 separately, refreshed validation and audit old/new/actor/time. Approve with a note when blocking issues are resolved. |
| 4:30–5:15 | Search `CG-2026-002`, supplier or amount. Show highlighted keyword results and original link. Explain semantic search availability accurately; do not call keyword search semantic search. |
| 5:15–6:00 | Upload `corrupted.pdf`, show FAILED job, then Retry and retry count. It should fail again because the source remains deliberately corrupt. This proves retry behavior, not recovery from corrupt bytes. Upload `duplicate.pdf` and show checksum duplicate warning; no file is silently deleted. |
| 6:00–7:00 | Show actual pytest/Playwright results and the Evaluation page. Explain sample size, failures, successful-document field accuracy and the deterministic-only metric. If OCR is installed, demonstrate `scanned.pdf`; otherwise show its explicit unavailable/failure state. |
| 7:00–8:00 | Close with limitations: no live model or embeddings evaluation without credentials, Docker engine unavailable in the verified session, no 1000-page benchmark. Explain how PostgreSQL/Redis/Celery and real providers are configured and what you would test next. |

Before recording, start API/frontend, verify login and use the documented fixture names. Existing browser tests create real synthetic records in local data; counts reflect those records. For a clean walkthrough use a separate data directory/database configured in `.env`; do not delete data blindly. Run tests before showing results. See README's submission checklist for GitHub and disclosure requirements.
