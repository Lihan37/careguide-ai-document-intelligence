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

export function DocumentList({
  mode,
  config,
  version,
  onError,
}: {
  mode: string;
  config: Config | null;
  version: number;
  onError: (s: string) => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [type, setType] = useState("");
  const [sort, setSort] = useState("newest");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [semantic, setSemantic] = useState<
    | {
        document_id: string;
        filename: string;
        excerpt: string;
        source: { page?: number; sheet?: string };
        distance: number;
      }[]
    | null
  >(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const endpoint =
      mode === "/review"
        ? `/api/review-queue?page=${page}&q=${encodeURIComponent(query)}`
        : `/api/documents?${new URLSearchParams({ q: query, status, file_type: type, sort, page: String(page) })}`;
    const load = () =>
      api<{ items: Row[]; total: number }>(endpoint)
        .then((data) => {
          setRows(data.items);
          setTotal(data.total);
        })
        .catch((e) => onError(e.message));
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [mode, page, query, status, type, sort, version, onError]);
  return (
    <section className="panel">
      <div className="toolbar">
        <form
          className="search-form"
          onSubmit={(e) => {
            e.preventDefault();
            setQuery(q);
            setPage(1);
            setSemantic(null);
          }}
        >
          <Search size={18} />
          <input
            aria-label="Search documents"
            placeholder="Search invoice, supplier, amount, or filename…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="button secondary" type="submit">
            Search
          </button>
        </form>
        {mode !== "/review" && (
          <>
            <select
              aria-label="Filter by status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {[
                "COMPLETED",
                "REQUIRES_REVIEW",
                "PROCESSING",
                "QUEUED",
                "FAILED",
                "CANCELLED",
              ].map((s) => (
                <option key={s} value={s}>
                  {label(s.toLowerCase())}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by format"
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All formats</option>
              {[".pdf", ".xlsx", ".xls", ".csv", ".png", ".jpg", ".tiff"].map(
                (s) => (
                  <option key={s}>{s}</option>
                ),
              )}
            </select>
            <select
              aria-label="Sort documents"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
            </select>
          </>
        )}
      </div>
      {mode === "/search" && (
        <div className="semantic-bar">
          <button
            className="button secondary"
            disabled={!config?.semantic_available || !q || busy}
            onClick={async () => {
              setBusy(true);
              try {
                const data = await api<{ items: NonNullable<typeof semantic> }>(
                  "/api/search/semantic",
                  { method: "POST", body: JSON.stringify({ query: q }) },
                );
                setSemantic(data.items);
              } catch (e) {
                onError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Semantic search
          </button>
          <span>
            {config?.semantic_available
              ? "Find meaning with configured vector embeddings."
              : "Semantic search requires PostgreSQL and a configured embedding provider."}
          </span>
        </div>
      )}
      {semantic ? (
        <div className="semantic-results">
          <h2>Semantic matches</h2>
          {semantic.length ? (
            semantic.map((r, i) => (
              <article key={i}>
                <Link href={"/documents/" + r.document_id}>{r.filename}</Link>
                <p>{r.excerpt}</p>
                {r.source.page !== undefined && <small>Page {r.source.page}</small>}
                {r.source.sheet !== undefined && <small>Sheet {r.source.sheet}</small>}
              </article>
            ))
          ) : (
            <Empty
              text="No semantic results"
              sub="Process documents with embeddings enabled to index them."
            />
          )}
        </div>
      ) : rows.length ? (
        <>
          <Table rows={rows} highlight={query} />
          <div className="pagination">
            <span>
              {total} documents · page {page}
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
              disabled={page * 25 >= total}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        </>
      ) : (
        <Empty
          text={
            mode === "/review"
              ? "Your review queue is clear"
              : query
                ? "No matching documents"
                : "No documents yet"
          }
          sub={
            mode === "/review"
              ? "Documents with unresolved exceptions will appear here."
              : "Upload a document or adjust your filters."
          }
        />
      )}
    </section>
  );
}
