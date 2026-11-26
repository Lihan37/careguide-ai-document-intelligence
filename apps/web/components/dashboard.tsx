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
  Badge,
  Empty,
  Json,
  Evidence,
  Action,
} from "./shared";
import { Table } from "./document-table";

export function Dashboard({
  version,
  onError,
}: {
  version: number;
  onError: (s: string) => void;
}) {
  const [data, setData] = useState<{
    total: number;
    statuses: Record<string, number>;
    types: Record<string, number>;
  } | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  useEffect(() => {
    const load = () =>
      Promise.all([
        api<typeof data>("/api/dashboard"),
        api<{ items: Row[] }>("/api/documents?page_size=6"),
        api<{ items: Job[] }>("/api/jobs?page_size=5"),
      ])
        .then(([stats, docs, jobData]) => {
          setData(stats);
          setRows(docs.items);
          setJobs(jobData.items);
        })
        .catch((e) => onError(e.message));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [version, onError]);
  if (!data)
    return (
      <div className="panel loading">
        <LoaderCircle className="spin" /> Loading document data…
      </div>
    );
  const cards = [
    {
      name: "Total documents",
      value: data.total,
      Icon: Files,
      note: "Across all uploaded file types",
      color: "blue",
    },
    {
      name: "Processed",
      value:
        (data.statuses.COMPLETED || 0) + (data.statuses.REQUIRES_REVIEW || 0),
      Icon: CheckCircle2,
      note: "Extraction completed",
      color: "teal",
    },
    {
      name: "In processing",
      value: (data.statuses.PROCESSING || 0) + (data.statuses.QUEUED || 0) + (data.statuses.CANCELLING || 0),
      Icon: Activity,
      note: "Queued and active jobs",
      color: "blue",
    },
    {
      name: "Needs attention",
      value: (data.statuses.REQUIRES_REVIEW || 0) + (data.statuses.FAILED || 0),
      Icon: AlertTriangle,
      note: `${data.statuses.FAILED || 0} failed · ${data.statuses.REQUIRES_REVIEW || 0} require review`,
      color: "amber",
    },
  ];
  return (
    <>
      <div className="stat-grid">
        {cards.map((c) => (
          <div className="stat-card" key={c.name}>
            <div>
              {c.name}
              <span className={"stat-icon " + c.color}>
                <c.Icon size={19} />
              </span>
            </div>
            <strong>{c.value}</strong>
            <p>{c.note}</p>
          </div>
        ))}
      </div>
      <div className="dashboard-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Processing activity</h2>
              <p>Latest document jobs</p>
            </div>
            <Link href="/jobs">View all jobs</Link>
          </div>
          {jobs.length ? (
            <div className="activity-list">
              {jobs.map((job) => (
                <Link
                  href={"/documents/" + job.document_id}
                  className="activity-row"
                  key={job.id}
                >
                  <span
                    className={
                      "activity-icon " + (job.status === "FAILED" ? "red" : "")
                    }
                  >
                    {job.status === "FAILED" ? (
                      <AlertTriangle size={18} />
                    ) : (
                      <FileText size={18} />
                    )}
                  </span>
                  <div>
                    <strong>{job.stage}</strong>
                    <small>
                      {job.pages_processed} / {job.total_pages} source units ·{" "}
                      {job.progress}% complete
                    </small>
                  </div>
                  <Badge status={job.status} />
                </Link>
              ))}
            </div>
          ) : (
            <Empty
              text="Ready when you are"
              sub="Processing activity will appear after your first upload."
            />
          )}
        </section>
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Document mix</h2>
              <p>Uploaded files by format</p>
            </div>
            <ChartNoAxesCombined size={19} />
          </div>
          <div className="distribution">
            <div className="distribution-total">
              <strong>{data.total}</strong>
              <span>total documents</span>
            </div>
            {Object.entries(data.types).map(([type, count], index) => (
              <div className="distribution-row" key={type}>
                <div>
                  <span>{type.slice(1).toUpperCase()}</span>
                  <strong>{count}</strong>
                </div>
                <div className="bar">
                  <span
                    style={{
                      width: `${(count / Math.max(data.total, 1)) * 100}%`,
                      background: ["#2870df", "#21a899", "#8f82d4", "#e6a84f"][
                        index % 4
                      ],
                    }}
                  />
                </div>
              </div>
            ))}
            {!data.total && (
              <p className="muted">Your file distribution will appear here.</p>
            )}
          </div>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Recent documents</h2>
            <p>A live view of your latest uploads</p>
          </div>
          <Link href="/documents">View all documents</Link>
        </div>
        {rows.length ? <Table rows={rows} /> : <Empty />}
      </section>
      <div className="info-strip">
        <ShieldCheck size={22} />
        <div>
          <strong>Every number has a source.</strong>
          <p>
            Inspect original files, financial validation, and correction history
            from any document.
          </p>
        </div>
        <Link href="/review">Open review queue</Link>
      </div>
    </>
  );
}
