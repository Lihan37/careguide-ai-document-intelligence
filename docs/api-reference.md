# API reference

Base URL: `http://localhost:8000`. Interactive OpenAPI: `/docs`; machine schema: `/openapi.json`. Browser access uses credentials and the `careguide_session` HttpOnly cookie. All financial-data routes require authentication and document ownership; mutation routes for corrections/comparisons/review/retry/cancel/recovery require reviewer/admin role. Health/readiness and login are public.

| Method | Route | Behavior |
| --- | --- | --- |
| POST | /api/auth/login | `{username,password}`; validate scrypt hash, set eight-hour cookie |
| POST | /api/auth/logout | Clear local session cookie |
| GET | /api/auth/me | Current username and role |
| POST | /api/documents/upload | Multipart repeated `files`; 202 with per-file success/error; async processing |
| GET | /api/documents | Paged document metadata; `q`, `status`, `file_type`, `sort=newest/oldest`, `page`, `page_size` |
| GET | /api/documents/{id} | Metadata, raw/effective fields, evidence, issues, sources, jobs and audit |
| GET | /api/documents/{id}/status | Document and latest job progress |
| GET | /api/documents/{id}/extraction | Original, corrections, effective values, evidence and extraction method |
| GET | /api/documents/{id}/validation | PASSED/WARNING/FAILED/REQUIRES_REVIEW and rule details |
| GET | /api/documents/{id}/source | Authenticated original download/inline PDF; optional `page=1` renders bounded PNG |
| POST | /api/documents/{id}/reprocess | 202; new attempt, maximum three manual retries; 409 while active |
| PATCH | /api/documents/{id}/corrections | `{fields:{total:"220.00"},reason:"Source checked"}`; strict schema, audit old/new, revalidate |
| GET | /api/jobs | Paged processing history (`page`, `page_size`) |
| GET | /api/jobs/{id} | Status, stage, progress, counters, retries and error |
| POST | /api/jobs/{id}/cancel | Cooperative cancellation of queued/active jobs |
| POST | /api/jobs/recover-stale | Fail current owner's expired processing leases |
| GET | /api/review-queue | Unapproved flagged documents; `q`, `page`, `page_size` |
| POST | /api/reviews/{id}/resolve | `{decision:"approved" or "follow_up",note:"Evidence checked"}`; block approval on failed/required-field issues |
| GET | /api/search | Keyword search with same filters as documents |
| POST | /api/search/semantic | `{query,limit}`; real embeddings and pgvector cosine ranking; 503 if unavailable |
| POST | /api/comparisons | Select 2–10 distinct processed document IDs; first is baseline; persist all field differences |
| GET | /api/comparisons | Latest 100 comparison references for owner |
| GET | /api/comparisons/{id} | Saved field snapshots and source provenance |
| GET | /api/dashboard | Database-derived counts by status/type |
| GET | /api/settings | Safe capability flags, limits and model names; no secrets |
| GET | /api/evaluation/results | Actual saved evaluation results, or explicit not-run state |
| GET | /api/health | API liveness |
| GET | /api/environment | Environment/automation kind/run UUID only; no credentials or storage paths |
| GET | /api/ready | Database/broker readiness; does not assert worker liveness |

Comparison mappings example:

```json
{
  "document_ids": ["pdf-uuid", "xlsx-uuid"],
  "mappings": {"xlsx-uuid": {"invoice_number": "Invoice ID", "total": "Amount", "currency": "CCY"}},
  "sheets": {"xlsx-uuid": "Accounting"},
  "rows": {"xlsx-uuid": 2}
}
```

Mapping selects one spreadsheet record; unmapped fields are missing. All data rows can be inspected in source cells. Dates must be ISO format and amounts decimal strings. A currency mismatch prevents a monetary match even if the numeric values are equal. Different line-item arrays require review; semantic similarity never establishes a financial match. A mismatch adds a review warning to both records. Saved comparisons are immutable snapshots; rerun after corrections.

Responses use standard FastAPI JSON errors: 401 authentication, 403 role/origin, 404 not found or not owned, 409 state conflict, 413 request size, 422 schema/count validation, 429 rate limit, 503 dependency unavailable. Per-file extension/signature/size failures are reported inside the upload's 202 results so other files can proceed. Unexpected errors return generic 500 messages without document text. API response dictionaries are serialized as JSON; request models and OpenAPI are strict, but not every response currently has a dedicated Pydantic response model.
