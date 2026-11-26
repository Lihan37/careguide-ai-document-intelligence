"use client";
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
  ProcessingBadge,
  Empty,
  Json,
  Evidence,
  Action,
} from "./shared";

export function Jobs({ version, action }: { version: number; action: Action }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    const load = () =>
      api<{ items: Job[]; total: number }>(`/api/jobs?page=${page}`)
        .then((data) => {
          setJobs(data.items);
          setTotal(data.total);
        })
        .catch((e) => setError(e.message));
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  }, [version, page]);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Background processing</h2>
          <p>Live progress, bounded retries, and failure recovery</p>
        </div>
        <button
          className="button secondary"
          onClick={() =>
            action(
              () => api("/api/jobs/recover-stale", { method: "POST" }),
              "Expired worker leases checked",
            )
          }
        >
          Recover stale jobs
        </button>
      </div>
      {error && <div className="alert error">{error}</div>}
      {jobs.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Document</th>
                <th>Stage</th>
                <th>Progress</th>
                <th>Processing status</th>
                <th>Retries</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link href={"/documents/" + job.document_id}>
                      {job.document_id.slice(0, 8)}
                    </Link>
                    <small>{job.error}</small>
                  </td>
                  <td>
                    {job.stage}
                    <small>
                      {job.pages_processed}/{job.total_pages} source units
                    </small>
                  </td>
                  <td>
                    <progress max="100" value={job.progress} />
                    <small>{job.progress}%</small>
                  </td>
                  <td>
                    <ProcessingBadge status={job.status} />
                  </td>
                  <td>{job.retries} / 3</td>
                  <td>
                    {["QUEUED", "PROCESSING"].includes(job.status) ? (
                      <button
                        className="button secondary"
                        onClick={() =>
                          action(
                            () =>
                              api(`/api/jobs/${job.id}/cancel`, {
                                method: "POST",
                              }),
                            "Cancellation requested",
                          )
                        }
                      >
                        Cancel
                      </button>
                    ) : job.status === "FAILED" ? (
                      <button
                        disabled={job.retries >= 3}
                        className="button secondary"
                        onClick={() =>
                          action(
                            () =>
                              api(
                                `/api/documents/${job.document_id}/reprocess`,
                                { method: "POST" },
                              ),
                            "Retry requested",
                          )
                        }
                      >
                        Retry
                      </button>
                    ) : (
                      <Link href={"/documents/" + job.document_id}>
                        Inspect
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty text="No processing jobs" />
      )}
      <div className="pagination">
        <span>
          {total} jobs · page {page}
        </span>
        <button
          className="button secondary"
          disabled={page === 1}
          onClick={() => setPage((p) => p - 1)}
        >
          Previous
        </button>
        <button
          className="button secondary"
          disabled={page * 50 >= total}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </button>
      </div>
    </section>
  );
}
