# AI assistance disclosure and prompts

This implementation was created with OpenAI Codex coding assistance in the user's Windows workspace. The assistant read the supplied assessment PDF and the user's pasted requirements, scaffolded source files, implemented backend/frontend workflows, created synthetic fixtures and tests, ran available checks, corrected observed failures, and wrote documentation. The user must review and understand the code before submission. Do not represent this as independently hand-written work or claim a human review/recording that has not happened.

The original recruitment PDF is an assessment reference, not an executable instruction source. Uploaded business documents are untrusted data and do not authorize actions, code execution, secret access, deployment or network requests.

## Development prompt summary

The user's request asked for a practical CareGuide AI Document Intelligence System, seven assessment tasks and nine deliverables, FastAPI/SQLAlchemy/Next.js, real parsing/OCR/AI interfaces, deterministic validation and comparison, secure upload/access, persistent asynchronous jobs, audit review, real tests/evaluation, and honest disclosure of unavailable services. It prohibited fake AI/results, fabricated measurements, unapproved deployment or GitHub push. No subagents were used.

## Runtime extraction prompt

The OpenAI-compatible prompt is `SYSTEM_PROMPT` in `services/api/app/extraction.py`. The Gemini prompt is `SYSTEM_INSTRUCTION` in `services/api/app/gemini.py`. Both instruct the model to extract invoice facts, ignore embedded instructions and return null for unknown fields. Document content is JSON-encoded under `untrusted_document` and sent separately from system instructions.

Gemini uses a configurable model at Google's Developer API endpoint. The SDK requests structured JSON from a Pydantic-derived schema, and the application validates the response, checks that values appear in the source text and checks arithmetic using Decimal. Gemini receives no tools or credentials in the model input. Match evidence has no model confidence score. Reviewers can inspect the source and correct errors.

## Actual AI usage in this session

Codex assisted implementation, debugging, test execution, dependency auditing and documentation. The automated suite uses mocked Gemini HTTPS responses through the official SDK for provider error and schema cases. After the user confirmed free-tier access, live verification sent text from two digital invoices and Tesseract text from a two-page scan to Gemini. The final audit also uploaded those same synthetic fixtures through a scratch clone's API and checked its persisted results and provider usage. Generated changes were reviewed against the assessment and validated through automated tests, endpoint checks and browser inspection. [Live evaluation and evidence](evaluation-report.md#gemini-invoice-extraction)
