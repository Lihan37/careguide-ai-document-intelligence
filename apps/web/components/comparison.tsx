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

export function ComparisonPage({
  version,
  onError,
}: {
  version: number;
  onError: (s: string) => void;
}) {
  const [docs, setDocs] = useState<Row[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [mapping, setMapping] = useState<
    Record<string, Record<string, string>>
  >({});
  const [sheets, setSheets] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Record<string, number>>({});
  const [result, setResult] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<{ id: string; created_at: string }[]>([]);
  const [docPage, setDocPage] = useState(1);
  const [docTotal, setDocTotal] = useState(0);
  useEffect(() => {
    api<{ items: Row[]; total: number }>(
      `/api/documents?page_size=100&page=${docPage}`,
    )
      .then((d) => {
        setDocs(
          d.items.filter((r) =>
            ["COMPLETED", "REQUIRES_REVIEW"].includes(r.status),
          ),
        );
        setDocTotal(d.total);
      })
      .catch((e) => onError(e.message));
    api<{ items: typeof saved }>("/api/comparisons")
      .then((r) => setSaved(r.items))
      .catch((e) => onError(e.message));
  }, [version, onError, result?.id, docPage]);
  const choose = async (id: string) => {
    if (selected.includes(id)) {
      setSelected((old) => old.filter((s) => s !== id));
      return;
    }
    if (selected.length >= 10) return;
    setSelected((old) => [...old, id]);
    if (!details[id]) {
      try {
        const d = await api<Detail>("/api/documents/" + id);
        setDetails((old) => ({ ...old, [id]: d }));
      } catch (e) {
        onError((e as Error).message);
      }
    }
  };
  return (
    <>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Select documents to verify</h2>
            <p>
              The first selected document is the baseline. Comparisons use
              structured values and exact financial tolerances.
            </p>
          </div>
        </div>
        <div className="comparison-select">
          {docs.length ? (
            docs.map((d) => (
              <label
                className={
                  "selection-card " + (selected.includes(d.id) ? "chosen" : "")
                }
                key={d.id}
              >
                <input
                  type="checkbox"
                  checked={selected.includes(d.id)}
                  onChange={() => choose(d.id)}
                />
                <FileText size={20} />
                <span>
                  {d.filename}
                  <small>
                    {d.invoice_number || "No invoice number"} · {d.file_type}
                  </small>
                </span>
                {selected.includes(d.id) && (
                  <span className="selection-number">
                    {selected.indexOf(d.id) === 0 ? "Baseline" : "Compare"}
                  </span>
                )}
              </label>
            ))
          ) : (
            <Empty
              text="No processed documents"
              sub="Upload and process at least two documents to compare them."
            />
          )}
        </div>
        <div className="pagination">
          <span>Document page {docPage}</span>
          <button
            className="button secondary"
            disabled={docPage === 1}
            onClick={() => setDocPage((p) => p - 1)}
          >
            Previous
          </button>
          <button
            className="button secondary"
            disabled={docPage * 100 >= docTotal}
            onClick={() => setDocPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
        {selected.map((id) => {
          const d = details[id];
          const sources = d?.sources.filter((s) => s.rows) || [];
          if (!sources.length) return null;
          const source =
            sources.find((s) => s.sheet === sheets[id]) || sources[0];
          const headers = source.rows?.[0]?.map(String) || [];
          return (
            <details className="mapping" key={id}>
              <summary>Spreadsheet column mapping · {d.filename}</summary>
              <p>
                Optional. Select the sheet and data row, then map nonstandard
                headers. Unmapped values remain missing.
              </p>
              <div className="form-grid">
                <label>
                  Worksheet
                  <select
                    value={sheets[id] || source.sheet}
                    onChange={(e) =>
                      setSheets((old) => ({ ...old, [id]: e.target.value }))
                    }
                  >
                    {sources.map((s) => (
                      <option key={s.sheet}>{s.sheet}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Data row
                  <input
                    type="number"
                    min={2}
                    max={source.rows?.length}
                    value={rows[id] || 2}
                    onChange={(e) =>
                      setRows((old) => ({
                        ...old,
                        [id]: Number(e.target.value),
                      }))
                    }
                  />
                </label>
                {fields.slice(0, 8).map((field) => (
                  <label key={field}>
                    {label(field)}
                    <select
                      value={mapping[id]?.[field] || ""}
                      onChange={(e) =>
                        setMapping((old) => ({
                          ...old,
                          [id]: { ...old[id], [field]: e.target.value },
                        }))
                      }
                    >
                      <option value="">Use extracted / unmapped</option>
                      {headers.map((h, i) => (
                        <option key={i} value={h}>
                          {h}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
            </details>
          );
        })}
        <div className="section-pad">
          <button
            className="button primary"
            disabled={selected.length < 2 || busy}
            onClick={async () => {
              setBusy(true);
              try {
                const cleanMapping = Object.fromEntries(
                  Object.entries(mapping)
                    .filter(([id]) => selected.includes(id))
                    .map(([id, values]) => [
                      id,
                      Object.fromEntries(
                        Object.entries(values).filter(([, v]) => v),
                      ),
                    ]),
                );
                setResult(
                  await api("/api/comparisons", {
                    method: "POST",
                    body: JSON.stringify({
                      document_ids: selected,
                      mappings: cleanMapping,
                      sheets,
                      rows,
                    }),
                  }),
                );
              } catch (e) {
                onError((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Comparing…" : `Compare ${selected.length} documents`}
          </button>
        </div>
      </section>
      {result?.results.map((r, i) => (
        <section className="panel" key={i}>
          <div className="panel-heading">
            <div>
              <h2>
                {r.left_filename} vs {r.right_filename}
              </h2>
              <p>Saved comparison · {result.id}</p>
            </div>
            <Badge status={r.review_status} />
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Baseline</th>
                  <th>Compared document</th>
                  <th>Result</th>
                  <th>Difference</th>
                </tr>
              </thead>
              <tbody>
                {r.fields.map((f) => (
                  <tr key={f.field}>
                    <td>{label(f.field)}</td>
                    <td>
                      {display(f.left)}
                      <Evidence value={f.left_source} />
                    </td>
                    <td>
                      {display(f.right)}
                      <Evidence value={f.right_source} />
                    </td>
                    <td>
                      <Badge status={f.status} />
                    </td>
                    <td>{f.difference || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="section-pad button-row">
            <Link href={"/documents/" + r.left_id}>Review baseline</Link>
            <Link href={"/documents/" + r.right_id}>
              Review compared document
            </Link>
          </div>
        </section>
      ))}
      {saved.length > 0 && (
        <section className="panel section-pad">
          <h2>Saved comparisons</h2>
          <div className="saved-comparisons">
            {saved.map((s) => (
              <button
                className="button secondary"
                key={s.id}
                onClick={() =>
                  api<Comparison>("/api/comparisons/" + s.id)
                    .then(setResult)
                    .catch((e) => onError(e.message))
                }
              >
                {s.id.slice(0, 8)} · {date(s.created_at)}
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}
