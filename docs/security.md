# Security and reliability

## Implemented controls

- Automation is isolated by environment, run UUID, database, storage, credentials and broker queue namespace. Settings reject development paths/missing ownership for automated runs. Playwright refuses server reuse, verifies environment identity before upload and tags requests; the API rejects mismatched environment/run headers. Development `.env` is never loaded by automated runners. Inspection is read-only; optional cleanup is dry-run by default and refuses development deletion and unproven historical records. See testing.md for confirmation/quarantine/recovery behavior.

- Private originals are written to generated UUID names under configurable storage outside the web root. API requests never accept a storage path. The supplied basename is display metadata only; traversal names cannot select destinations.
- Upload allowlist, per-file byte limit, batch count limit, signature checks, XLSX ZIP expanded-size/member count limits, macro/unsafe-member rejection, page/frame/cell/pixel limits, active PDF action/embedded-file rejection and PDF object count limits.
- OCR starts the native Tesseract CLI with an argument list and a per-call timeout. Image rendering has a pixel cap and releases each rendered page. Worker containers have CPU, memory and task time limits.
- Passwords use randomly salted scrypt. Session cookies are signed with an environment secret, HttpOnly, SameSite=Lax, eight-hour expiration; Secure is enabled for an HTTPS configured origin. No default shared password/secret works: startup enforces minimum lengths. Generated local credentials remain ignored in `.env`.
- Read access is restricted to document owner; reviewer/admin role is required for corrections, comparisons, retry/cancel/recovery and review decisions. Unauthorized foreign UUIDs return 404. Stale recovery is owner-scoped. There is no public original-file route.
- CORS permits one explicit origin and credentials. State changes reject a conflicting Origin header. Scheme/host must stay consistent. SameSite cookies and Origin checks are the assessment CSRF defense; no standalone CSRF-token flow is implemented.
- Parameterized SQL, bounded request/query schemas, HTML text escaping by React and no raw document HTML execution. No macros or spreadsheet formulas are executed/recalculated; external workbook links are not loaded.
- Per-process rate limits: 10 login attempts/minute/IP and 300 other requests/minute/IP. Content-Length and streamed-body byte counters reject excessive requests, including bodies without a declared length. A production reverse proxy must also impose upload size, multipart and shared rate limits; the assessment API is not an internet-facing upload gateway.
- Prompt injection defenses: document data is JSON-encoded untrusted text under a fixed system prompt, no tools are enabled, response schema is strict, financial reconciliation is deterministic and decisions require human confirmation. This reduces instruction-following risk but does not guarantee factual model accuracy.
- Safe generic unexpected errors and no request bodies, document text, credentials or provider payloads in application logs. Default access logs contain endpoint UUIDs/status, not financial content. Audit records intentionally retain private correction/review details and are access-controlled as document data.
- Append-only correction/review audit API; original and human values stored separately. No silent deletion of duplicates. Manual decisions do not remove warnings. Duplicate candidates are limited to same owner and supplier-aware identity.
- Semantic search filters vector rows by owner/model and source references originate from real stored chunks. Disabled without real embeddings/pgvector; no fabricated vectors are used.

## Verified checks

Tests exercise unauthenticated requests, foreign-owner access, viewer mutation, conflicting origins, unsafe uploads, provider errors, cancellation, duplicate deliveries and stale recovery. A dependency advisory scan flagged the former Pillow 12.3.0 pin. After updating to Pillow 13.0.0, `pip-audit` and `npm audit` reported no known findings in the audited lockfiles, and `pip check` passed. The final Git scan checked indexed files for credential signatures and private paths. These checks cover the assessed dependencies and workflows. Production penetration testing remains open. [Pillow release notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)

## Scans with embedded attachments

An image-only page can be part of a PDF that contains an embedded file. Document-level C2PA Content Credentials are stored as an attachment and fall under the same rejection policy. The processing worker reports an attachment-specific error before OCR. It also rejects damaged PDFs that require cross-reference repair. [C2PA PDF manifest format](https://spec.c2pa.org/specifications/specifications/2.3/specs/C2PA_Specification.html#a4-embedding-manifests-into-pdfs)

If you trust the original scan, upload its JPG or PNG directly. For a PDF, use the trusted page images to create a new image-only PDF, with one image per page and attachment or Content Credentials export disabled. Keep the original file to preserve its provenance and upload the new file as a separate document so the original processing history stays available.

## Deployment work remaining

Do not expose this local assessment to the public without TLS, a hardened upload proxy, shared rate limiting, enterprise identity/session revocation, isolated workers (no outbound network except explicit provider access), malware scanning as appropriate, secret management, backups, retention policies, disk quotas and operational monitoring. Container image dependencies and Compose integration were not runtime verified here. File storage and audit DB require encrypted disks/backups for real financial records. Logout clears the browser cookie; a stolen cookie remains valid until expiration or SESSION_SECRET rotation. No public deployment was performed.
