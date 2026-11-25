# Security and reliability

## Implemented controls

- Private originals are written to generated UUID names under configurable storage outside the web root. API requests never accept a storage path. The supplied basename is display metadata only; traversal names cannot select destinations.
- Upload allowlist, per-file byte limit, batch count limit, signature checks, XLSX ZIP expanded-size/member count limits, macro/unsafe-member rejection, page/frame/cell/pixel limits, active PDF action/embedded-file rejection and PDF object count limits.
- OCR uses pytesseract without a shell and a per-call timeout. Image rendering has a pixel cap; pages are released individually. Worker containers have CPU/memory and task time limits. Native parser vulnerabilities still require dependency patching and stronger production isolation.
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

Tests exercise unauthenticated private-source rejection, foreign-owner access denial, viewer mutation rejection, malicious Origin rejection, path traversal filenames, signatures/extensions, file count/size limits, active PDF content, workbook dimensions, malformed CSV, invalid financial values, invalid provider outputs, cancellation, idempotent terminal deliveries, bounded retries, and stale recovery. `pip check` reports no broken backend requirements. This is not a penetration test, dependency vulnerability audit or proof of production readiness.

## Deployment work remaining

Do not expose this local assessment to the public without TLS, a hardened upload proxy, shared rate limiting, enterprise identity/session revocation, isolated workers (no outbound network except explicit provider access), malware scanning as appropriate, secret management, backups, retention policies, disk quotas and operational monitoring. Container image dependencies and Compose integration were not runtime verified here. File storage and audit DB require encrypted disks/backups for real financial records. Logout clears the browser cookie; a stolen cookie remains valid until expiration or SESSION_SECRET rotation. No public deployment was performed.
