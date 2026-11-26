"use client";
import type { DeleteTarget } from "./document-delete-dialog";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Files,
  UploadCloud,
  Activity,
  ClipboardCheck,
  Columns3,
  Search,
  ChartNoAxesCombined,
  FileText,
  CheckCircle2,
  AlertTriangle,
  LoaderCircle,
  X,
  ShieldCheck,
  RefreshCw,
  FolderOpen,
} from "lucide-react";
import {
  API,
  Row,
  Issue,
  Job,
  Config,
  Source,
  Detail,
  Comparison,
  fields,
  label,
  display,
  date,
  api,
  Badge,
  ProcessingBadge,
  ReviewBadge,
  Empty,
  Json,
  Evidence,
  Action,
} from "./shared";

type CandidateVersion = {
  method: string;
  effective: Record<string, unknown>;
  issues: Issue[];
  evidence: Record<string, unknown>;
};

type CandidateReview = {
  status: "pending" | "accepted";
  stale: boolean;
  can_accept: boolean;
  current: CandidateVersion;
  candidate: CandidateVersion;
};

export function DocumentDetail({
  id,
  version,
  action,
  canReview,
  onDelete,
}: {
  id: string;
  version: number;
  action: Action;
  canReview: boolean;
  onDelete?: (document: DeleteTarget) => void;
}) {
  const [document, setDocument] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("Overview");
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [reviewBusy, setReviewBusy] = useState(false);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState(false);
  const [lineJson, setLineJson] = useState("");
  const [review, setReview] = useState<(CandidateReview & { jobId: string }) | null>(null);
  const [candidateReason, setCandidateReason] = useState("");
  const [candidateError, setCandidateError] = useState("");
  const candidateRequest = useRef(0);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api<Detail>("/api/documents/" + id)
        .then((data) => {
          if (alive) setDocument(data);
        })
        .catch((e) => { if (alive) setError(e.message); });
    load();
    const timer = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [id, version]);
  if (error)
    return (
      <div role="alert" className="alert error">
        {error}
      </div>
    );
  if (!document) return <div className="loading">Loading document…</div>;
  const ready = ["COMPLETED", "REQUIRES_REVIEW"].includes(document.status);
  const latestJob = document.history[0];
  const activeJob = document.history.find((job) => ["QUEUED", "PROCESSING", "CANCELLING"].includes(job.status));
  const progressJob = activeJob ?? (!ready ? latestJob : undefined);
  const pendingCandidate = document.history.find((job) => job.candidate_status === "pending");
  const hasBlockingIssues = document.issues.some(({ severity }) => ["FAILED", "REQUIRES_REVIEW"].includes(severity));
  const reviewDisabled = !ready || reviewBusy || note.trim().length < 3;
  const approvalDisabled = reviewDisabled || hasBlockingIssues || document.review_status === "approved";
  const submitReview = async (decision: "approved" | "follow_up") => {
    if (reviewDisabled || (decision === "approved" && approvalDisabled)) return;
    setReviewBusy(true);
    try {
      await action(async () => {
        const result = await api<{ review_status: string }>(`/api/reviews/${id}/resolve`, {
          method: "POST",
          body: JSON.stringify({ decision, note }),
        });
        setDocument((current) => current && { ...current, review_status: result.review_status });
        setNote("");
      }, decision === "approved" ? "Review approved. Validation evidence retained." : "Marked for follow-up");
    } finally {
      setReviewBusy(false);
    }
  };
  const openCandidate = async (jobId: string) => {
    const request = ++candidateRequest.current;
    setTab("History");
    setCandidateError("");
    setCandidateReason("");
    setReview(null);
    try {
      const data = await api<CandidateReview>(`/api/documents/${id}/candidates/${jobId}`);
      if (candidateRequest.current === request) setReview({ ...data, jobId });
    } catch (e) {
      if (candidateRequest.current === request) setCandidateError((e as Error).message);
    }
  };
  return (
    <>
      <section className="panel detail-summary">
        <span className="file-icon">
          <FileText size={26} />
        </span>
        <div>
          <h2>{document.filename}</h2>
          <p>
            {document.file_type.toUpperCase()} ·{" "}
            {(document.size / 1024).toFixed(1)} KB · {document.page_count} pages
            · {document.sheet_count} sheets · {document.duration.toFixed(2)} sec
          </p>
        </div>
        <dl className="document-status-pair" aria-label="Document statuses">
          <div>
            <dt>Processing status</dt>
            <dd><ProcessingBadge status={document.status} /></dd>
          </div>
          <div>
            <dt>Review status</dt>
            <dd><ReviewBadge status={document.review_status} /></dd>
          </div>
        </dl>
        <a
          className="button secondary"
          href={API + `/api/documents/${id}/source`}
          target="_blank"
          rel="noreferrer"
        >
          Download original
        </a>
        <button
          className="button secondary"
          disabled={Boolean(activeJob)}
          onClick={() =>
            action(
              () => api(`/api/documents/${id}/reprocess`, { method: "POST" }),
              "Reprocessing requested",
            )
          }
        >
          Retry processing
        </button>
        {onDelete && (
          <button type="button" className="button secondary delete-document-trigger" onClick={() => onDelete(document)}>
            Delete
          </button>
        )}
      </section>
      {document.error && <div className="alert error">{document.error}</div>}
      {progressJob && (
        <section className="panel progress-panel">
          <strong>{progressJob.stage}</strong>
          <progress max="100" value={progressJob.progress} />
          <span>
            {progressJob.progress}% · {progressJob.pages_processed}/
            {progressJob.total_pages} source units
          </span>
        </section>
      )}
      {canReview && pendingCandidate && tab !== "History" && (
        <button className="button secondary" onClick={() => openCandidate(pendingCandidate.id)}>
          Review retry candidate
        </button>
      )}
      <div className="tabs" role="tablist">
        {[
          "Overview",
          "Validation",
          "Corrections",
          "Source text",
          "History",
        ].map((name) => (
          <button
            key={name}
            role="tab"
            aria-selected={tab === name}
            className={tab === name ? "selected" : ""}
            onClick={() => setTab(name)}
          >
            {name}
            {name === "Validation" ? ` (${document.issues.length})` : ""}
          </button>
        ))}
      </div>
      {tab === "Overview" && (
        <div className="detail-grid">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Structured extraction</h2>
                <p>
                  {document.extraction_method} · uncalibrated field confidence
                </p>
              </div>
            </div>
            {ready ? (
              <>
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Field</th>
                        <th>Effective value</th>
                        <th>Original evidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fields.map((field) => (
                        <tr key={field}>
                          <td>{label(field)}</td>
                          <td className="value">
                            {display(document.effective[field])}
                            {field in document.corrected && (
                              <small className="green">
                                Human corrected · original:{" "}
                                {display(document.raw[field])}
                              </small>
                            )}
                          </td>
                          <td>
                            <Evidence value={document.evidence[field]} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="section-pad">
                  <h3>Line items</h3>
                  <Json data={document.effective.line_items} />
                </div>
              </>
            ) : (
              <Empty
                text="Extraction is not ready"
                sub="Monitor processing or inspect the failure message."
              />
            )}
          </section>
          <section className="panel source-preview">
            <div className="panel-heading">
              <div>
                <h2>Original source</h2>
                <p>Check every value against the original</p>
              </div>
            </div>
            {document.file_type === ".pdf" && document.page_count > 0 ? (
              <>
                <div className="preview-controls">
                  <button
                    className="button secondary"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => p - 1)}
                  >
                    Previous
                  </button>
                  <span>
                    Page {page} of {document.page_count}
                  </span>
                  <button
                    className="button secondary"
                    disabled={page >= document.page_count}
                    onClick={() => setPage((p) => p + 1)}
                  >
                    Next
                  </button>
                </div>
                {/* Authenticated page endpoint uses the same HttpOnly session cookie. */}
                <img
                  className="page-image"
                  alt={"Original PDF page " + page}
                  src={API + `/api/documents/${id}/source?page=${page}`}
                />
              </>
            ) : (
              <div className="section-pad">
                {document.sources.map((source, i) => (
                  <div key={i}>
                    <h3>{source.sheet || `Page ${source.page}`}</h3>
                    <pre className="source-text">{source.text}</pre>
                    {source.formulas && source.formulas.length > 0 && (
                      <>
                        <h4>Formula cache evidence (not recalculated)</h4>
                        <Json data={source.formulas} />
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
      {tab === "Validation" && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Financial validation</h2>
              <p>Exact Decimal arithmetic with currency-specific tolerance</p>
            </div>
            {ready && !document.issues.length && <Badge status="PASSED" />}
          </div>
          {document.issues.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Rule</th>
                    <th>Severity</th>
                    <th>Explanation</th>
                    <th>Expected / actual</th>
                    <th>Difference</th>
                  </tr>
                </thead>
                <tbody>
                  {document.issues.map((issue, i) => (
                    <tr key={i}>
                      <td>{label(issue.rule_id)}</td>
                      <td>
                        <Badge status={issue.severity} />
                      </td>
                      <td>{issue.explanation}</td>
                      <td>
                        {issue.expected || "—"} / {issue.actual || "—"}
                      </td>
                      <td>{issue.difference || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="section-pad">
              {ready
                ? "All applicable checks passed."
                : "Validation will run after extraction."}
            </div>
          )}
          {canReview && (
            <div className="section-pad">
              <h3>Review decision</h3>
              <label>
                Review note
                <textarea
                  value={note}
                  disabled={reviewBusy}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Explain your decision…"
                />
              </label>
              <div className="button-row">
                <button className="button primary" disabled={approvalDisabled} onClick={() => submitReview("approved")}>
                  Approve result
                </button>
                <button className="button secondary" disabled={reviewDisabled} onClick={() => submitReview("follow_up")}>
                  Mark for follow-up
                </button>
              </div>
              <p className="small-note">
                {hasBlockingIssues && "Correct failed checks and missing required fields before approval. "}
                Warnings stay visible after approval.
              </p>
            </div>
          )}
        </section>
      )}
      {tab === "Corrections" && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Correct extracted fields</h2>
              <p>Original extraction and source evidence are retained.</p>
            </div>
          </div>
          <form
            className="section-pad"
            onSubmit={async (e) => {
              e.preventDefault();
              setBusy(true);
              try {
                const changes: Record<string, unknown> = Object.fromEntries(
                  Object.entries(edit).map(([k, v]) => [k, v || null]),
                );
                if (lineJson) changes.line_items = JSON.parse(lineJson);
                await action(
                  () =>
                    api(`/api/documents/${id}/corrections`, {
                      method: "PATCH",
                      body: JSON.stringify({ fields: changes, reason }),
                    }),
                  "Correction saved and validation refreshed",
                );
                setEdit({});
              } catch (e) {
                setError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <div className="form-grid">
              {fields.map((field) => (
                <label key={field}>
                  {label(field)}
                  <input
                    aria-label={"Correct " + label(field)}
                    value={
                      edit[field] ??
                      (document.effective[field] === null ||
                      document.effective[field] === undefined
                        ? ""
                        : String(document.effective[field]))
                    }
                    onChange={(e) =>
                      setEdit((old) => ({ ...old, [field]: e.target.value }))
                    }
                  />
                  <small>Original: {display(document.raw[field])}</small>
                </label>
              ))}
            </div>
            <label>
              Line items JSON (optional)
              <textarea
                value={lineJson}
                onChange={(e) => setLineJson(e.target.value)}
                placeholder={JSON.stringify(
                  document.effective.line_items || [],
                )}
              />
            </label>
            <label>
              Reason for correction
              <textarea
                required
                minLength={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="Describe the source evidence for this change…"
              />
            </label>
            <button
              className="button primary"
              disabled={
                busy || !ready || (!Object.keys(edit).length && !lineJson)
              }
            >
              Save correction
            </button>
          </form>
          <div className="section-pad">
            <h3>Original extracted JSON</h3>
            <Json data={document.raw} />
            <h3>Human corrections</h3>
            <Json data={document.corrected} />
          </div>
        </section>
      )}
      {tab === "Source text" && (
        <section className="panel section-pad">
          <h2>Extracted text and provenance</h2>
          {document.sources.map((source, i) => (
            <div key={i}>
              <h3>
                {source.page ? `Page ${source.page}` : source.sheet} ·{" "}
                {source.method}
              </h3>
              {source.ocr_language && (
                <p>
                  OCR language {source.ocr_language} · mean word confidence{" "}
                  {source.ocr_confidence == null
                    ? "unavailable"
                    : `${Math.round(source.ocr_confidence * 100)}%`}
                </p>
              )}
              <pre className="source-text">{source.text}</pre>
              {source.rows && (
                <details>
                  <summary>Raw cells with row/column coordinates</summary>
                  <Json
                    data={source.rows.map((row, r) =>
                      row.map((value, c) => ({
                        row: r + 1,
                        column: c + 1,
                        value,
                      })),
                    )}
                  />
                </details>
              )}
            </div>
          ))}
        </section>
      )}
      {tab === "History" && (
        <section className="panel section-pad">
          <h2>Processing history</h2>
          {document.history.map((job) => (
            <div className="history-row" key={job.id}>
              <ProcessingBadge status={job.status} />
              <span>
                {job.stage} · {job.progress}% · retry {job.retries}
              </span>
              {job.error && <p>{job.error}</p>}
              {canReview && (job.candidate_status === "pending" || job.candidate_status === "accepted") && (
                <button className="button secondary" onClick={() => openCandidate(job.id)}>
                  Compare retry candidate
                </button>
              )}
            </div>
          ))}
          {candidateError && <p role="alert">{candidateError}</p>}
          {review && (
            <div className="section-pad">
              <h3>Retry comparison</h3>
              {review.stale && <p>The current extraction changed after this retry. Run a new retry to propose a replacement.</p>}
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>{review.status === "accepted" ? "Previous result" : "Current result"}<br />{review.current.method}</th>
                      <th>{review.status === "accepted" ? "Accepted replacement" : "Retry candidate"}<br />{review.candidate.method}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map((field) => (
                      <tr key={field}>
                        <td>{label(field)}</td>
                        {[review.current, review.candidate].map((result, i) => (
                          <td key={i}>
                            {display(result.effective[field])}
                            <Evidence value={result.evidence[field]} />
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr>
                      <td>Line items</td>
                      {[review.current, review.candidate].map((result, i) => (
                        <td key={i}>
                          <Json data={result.effective.line_items} />
                          <details><summary>Line item evidence</summary><Json data={result.evidence.line_items} /></details>
                        </td>
                      ))}
                    </tr>
                    <tr>
                      <td>Validation issues</td>
                      <td><Json data={review.current.issues} /></td>
                      <td><Json data={review.candidate.issues} /></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {review.can_accept && (
                <form onSubmit={(event) => {
                  event.preventDefault();
                  action(async () => {
                    await api(`/api/documents/${id}/candidates/${review.jobId}/accept`, {
                      method: "POST",
                      body: JSON.stringify({ reason: candidateReason }),
                    });
                    setReview(null);
                  }, "Candidate accepted");
                }}>
                  <label>Reason for accepting
                    <input required minLength={3} maxLength={2000} value={candidateReason} onChange={(event) => setCandidateReason(event.target.value)} />
                  </label>
                  <button className="button primary" type="submit" disabled={Boolean(activeJob) || candidateReason.trim().length < 3}>
                    Accept replacement
                  </button>
                </form>
              )}
            </div>
          )}
          <h2>Audit trail</h2>
          {document.audit.map((entry, i) => (
            <details key={i} className="audit-entry">
              <summary>
                {label(entry.action)} · {date(entry.created_at)}
              </summary>
              <p>Actor: {entry.user_id}</p>
              <Json data={entry.detail} />
            </details>
          ))}
          <p className="small-note">SHA-256: {document.checksum}</p>
        </section>
      )}
    </>
  );
}
