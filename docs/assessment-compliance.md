# Assessment compliance matrix

Assessment scope comes from `Ai Engineer Task 1.3.pdf`. `PASS` means the feature was exercised within the stated scope. `PARTIAL` means the feature works with limited evidence or coverage. `BLOCKED` means a required dependency prevents verification. `NOT_IMPLEMENTED` means the deliverable or feature is absent.

## Required features

| Assessment task | Requirement | Status | Evidence |
| --- | --- | --- | --- |
| 1. Document processing | Multiple uploads and PDF, JPG, PNG, TIFF, XLSX, XLS and CSV readers | PASS | Reader and upload tests exercise all listed formats. See [testing](testing.md). |
| 1. Document processing | Digital PDFs, image OCR, scanned and mixed PDFs, multiple pages and workbook sheets | PASS | Tesseract recognizes the bundled images and scans. Backend tests verify page and cell evidence. See [OCR results](evaluation-report.md#real-ocr-verification). |
| 1. Document processing | Poor-quality inputs and corrupt file handling | PASS | Degraded OCR produces a reviewable result. Corrupt PDF and image inputs fail visibly and the worker continues. See [test coverage](testing.md). |
| 2. AI extraction | Structured invoice number, date, supplier, customer, subtotal, tax, total, currency and line items | PASS | Free-tier live Gemini matched 69/69 checks across three synthetic invoices, including a two-page scan. See [live AI results](evaluation-report.md#gemini-invoice-extraction). |
| 2. AI extraction | Preserve unknowns and uncertain fields, with source evidence | PASS | Backend tests cover nulls, ungrounded values, invalid responses and page evidence. Human review remains available. |
| 3. Data validation | Missing fields, incorrect numbers, duplicate detection and Decimal reconciliation | PASS | Automated tests cover missing and invalid values, duplicate files and invoices, line math, subtotal, tax and total. |
| 3. Data validation | PDF-to-PDF and PDF-to-Excel reconciliation, review and correction | PASS | Comparisons run through the API and browser. Review corrections preserve the original and audit the change. |
| 4. Backend | REST uploads, processing status, extraction, search, manual correction and failed-job reprocessing | PASS | Authentication, ownership, job lifecycle and API/browser workflows passed. See [endpoint reference](api-reference.md). |
| 4. Backend | OCR and AI work off the API request path | PASS | Isolated Redis/Celery run processed eight OCR pages while all sampled API health requests succeeded. Local process mode also passed browser tests. |
| 4. Backend | Retries, duplicate delivery protection and stale-job recovery | PASS | Real Redis/Celery test replayed a delivery, retried a failed corrupt upload, and recovered an expired lease before reprocessing. |
| 5. Database and search | Store metadata, extracted text, structured results, validation errors and history | PASS | PostgreSQL migrations, audit and source storage, correction and comparison persistence after API restart, and SQLite coverage. See [database schema](database-schema.md). |
| 5. Database and search | Keyword search and filtering | PASS | Parameterized text filters verified through PostgreSQL, SQLite and Chromium. |
| 5. Database and search | Real semantic search with document sources | PASS | CPU BGE inference and pgvector ranked both tested paraphrases first. Stored excerpts matched page text, and search enforced ownership. |
| 6. Frontend | Batch upload, progress, detail, validation review, correction and search | PASS | Five Chromium workflows passed. The search page distinguishes keyword results from semantic matches. |
| 7. Testing | Automated document, OCR, spreadsheet, AI, validation, API and failure tests | PASS | 230 backend tests and five Chromium workflows passed. TypeScript and production build passed. |
| 7. Evaluation | Labeled accuracy, time, success and failure rates | PASS | Deterministic, OCR, live Gemini and scaling reports provide measured outcomes and independent fixture labels. See [evaluation report](evaluation-report.md). |
| Cross-cutting | Large PDFs and sustained processing volumes | PARTIAL | Synthetic PDF scale benchmark covers a 1,000-page digital sample and scans through 16 pages. Production volumes and 1,000-page scanned inputs require separate measurement. |
| Cross-cutting | Reliability and security | PARTIAL | Authentication, per-owner isolation, private uploads, input limits and auditable corrections are tested. Multi-worker failover and a production security assessment remain open. |

## Submission deliverables

| Deliverable | Status | Evidence |
| --- | --- | --- |
| Git repository with source | PASS | Existing GitHub repository and commit history |
| README and setup | PASS | [README](../README.md) and [Windows setup](setup-windows.md) |
| Architecture diagram and database schema | PASS | [Architecture](architecture.md) and [database schema](database-schema.md) |
| Working backend API and frontend | PASS | [API reference](api-reference.md) and [browser results](testing.md) |
| PDF, image, Excel and CSV pipelines | PASS | Reader, OCR, parser and validation evidence in the [test report](testing.md) |
| Automated tests and results | PASS | [Test summary and commands](testing.md) |
| Evaluation report with actual metrics | PASS | [Evaluation report](evaluation-report.md) |
| Recorded walkthrough | NOT_IMPLEMENTED | The [walkthrough script](demo-script.md) is ready for recording. |
| AI prompts and assistance disclosure | PASS | [Prompt locations and disclosure](ai-assistance-disclosure.md) |
