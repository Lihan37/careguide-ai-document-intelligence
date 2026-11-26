"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, Row } from "./shared";

export type DeleteTarget = Pick<Row, "id" | "filename">;

type DeletionDetails = {
  filename: string;
  comparison_ids: string[];
  active_processing: boolean;
  blocked: boolean;
};

export function DocumentDeleteDialog({ target, onClose, onDeleted }: {
  target: DeleteTarget;
  onClose: () => void;
  onDeleted: (message: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const [details, setDetails] = useState<DeletionDetails | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const endpoint = `/api/documents/${target.id}`;

  useEffect(() => {
    dialog.current?.showModal();
  }, []);

  useEffect(() => {
    const abort = new AbortController();
    api<DeletionDetails>(`${endpoint}/deletion`, { signal: abort.signal })
      .then(setDetails)
      .catch((failure: Error) => { if (!abort.signal.aborted) setError(failure.message); })
      .finally(() => { if (!abort.signal.aborted) setLoading(false); });
    return () => abort.abort();
  }, [endpoint, refresh]);

  function refreshDetails() {
    setLoading(true);
    setError("");
    setRefresh((current) => current + 1);
  }

  function closeDialog() {
    dialog.current?.close();
    onClose();
  }

  async function confirmDelete() {
    if (submitting.current || !details || details.active_processing || details.blocked) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ comparisons_deleted: number; warning: string | null }>(endpoint, {
        method: "DELETE",
        body: JSON.stringify({ comparison_ids: details.comparison_ids }),
      });
      const count = result.comparisons_deleted;
      const success = count ? `Document and ${count} saved ${count === 1 ? "comparison" : "comparisons"} deleted.` : "Document deleted.";
      dialog.current?.close();
      onDeleted(result.warning ? `${success} ${result.warning}` : success);
    } catch (failure) {
      setError((failure as Error).message);
      setDetails(null);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  const count = details?.comparison_ids.length ?? 0;
  return (
    <dialog ref={dialog} className="document-delete-dialog" aria-labelledby="delete-document-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting.current) closeDialog();
      }}>
      <h2 id="delete-document-title">Delete document?</h2>
      <p className="delete-filename">{details?.filename ?? target.filename}</p>
      <p>Deletion is permanent. The document, extraction, corrections, and processing history will be removed.</p>
      {loading && <p role="status">Checking saved comparisons and processing status…</p>}
      {details && (
        <>
          <dl className="delete-document-status">
            <dt>Dependent saved comparisons</dt><dd>{count}</dd>
            <dt>Processing status</dt><dd>{details.active_processing ? "Active or cancelling" : "Inactive"}</dd>
          </dl>
          {count > 0 && <p>Deleting also removes every saved comparison listed in this count. The other documents in those comparisons stay in your workspace.</p>}
          {details.active_processing && (
            <p>Cancel the job in <Link href="/jobs" onClick={closeDialog}>Processing Jobs</Link> and wait for cancellation to finish before deleting.</p>
          )}
          {details.blocked && <p role="alert">This document has a saved comparison your account cannot remove.</p>}
        </>
      )}
      {error && <p className="alert error" role="alert">{error}</p>}
      <div className="delete-dialog-actions">
        <button autoFocus type="button" className="button secondary" disabled={busy} onClick={closeDialog}>Cancel</button>
        {(error || details?.active_processing) && (
          <button type="button" className="button secondary" disabled={loading || busy} onClick={refreshDetails}>Refresh details</button>
        )}
        <button type="button" className="button danger" onClick={confirmDelete}
          disabled={loading || busy || !details || details.active_processing || details.blocked}>
          {busy ? "Deleting…" : count > 0 ? "Delete document and comparisons" : "Delete document"}
        </button>
      </div>
    </dialog>
  );
}
