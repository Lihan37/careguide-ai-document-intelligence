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

export function Upload({
  config,
  onComplete,
}: {
  config: Config | null;
  onComplete: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [queue, setQueue] = useState<File[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [results, setResults] = useState<
    { filename: string; document_id?: string; error?: string }[]
  >([]);
  const add = (files: FileList | File[]) => {
    const valid: File[] = [];
    const invalid: string[] = [];
    for (const file of Array.from(files)) {
      if (!/\.(pdf|jpe?g|png|tiff?|xlsx?|csv)$/i.test(file.name))
        invalid.push(file.name + ": unsupported file type");
      else if (file.size > (config?.max_file_mb || 30) * 1024 * 1024)
        invalid.push(file.name + ": file exceeds size limit");
      else valid.push(file);
    }
    setQueue((old) => [...old, ...valid]);
    setErrors(invalid);
  };
  const send = () => {
    if (queue.length > (config?.max_upload_files || 10)) {
      setErrors([
        "Too many files in this upload. Remove files to meet the batch limit.",
      ]);
      return;
    }
    setBusy(true);
    setProgress(0);
    const form = new FormData();
    queue.forEach((file) => form.append("files", file));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", API + "/api/documents/upload");
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        setProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => {
      setErrors(["Cannot reach API"]);
      setBusy(false);
    };
    xhr.onload = () => {
      setBusy(false);
      if (xhr.status === 202) {
        setResults(JSON.parse(xhr.responseText).results);
        setQueue([]);
        onComplete();
      } else {
        setErrors([xhr.responseText]);
      }
    };
    xhr.send(form);
  };
  return (
    <>
      <section className="panel upload-panel">
        <div
          className={"dropzone " + (drag ? "drag" : "")}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (!busy) add(e.dataTransfer.files);
          }}
        >
          <span className="upload-icon">
            <UploadCloud size={32} />
          </span>
          <h2>Drop your documents here</h2>
          <p>Invoices, receipts, spreadsheets. We’ll take it from here.</p>
          <button
            className="button primary"
            disabled={busy}
            onClick={() => input.current?.click()}
          >
            Browse files
          </button>
          <input
            ref={input}
            aria-label="Choose documents"
            type="file"
            multiple
            accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.xlsx,.xls,.csv"
            onChange={(e) => {
              if (e.target.files) add(e.target.files);
              e.target.value = "";
            }}
            hidden
          />
          <small>
            PDF, JPG, PNG, TIFF, XLSX, XLS, CSV · {config?.max_file_mb || 30} MB
            per file · {config?.max_upload_files || 10} files per batch
          </small>
        </div>
        {errors.map((message, i) => (
          <div className="alert error" role="alert" key={i}>
            {message}
          </div>
        ))}
        {queue.length > 0 && (
          <div className="upload-queue">
            <h3>Upload queue ({queue.length})</h3>
            {queue.map((file, index) => (
              <div className="queue-row" key={index}>
                <FileText size={20} />
                <span>
                  {file.name}
                  <small>{(file.size / 1024).toFixed(1)} KB</small>
                </span>
                <button
                  disabled={busy}
                  className="icon-button"
                  aria-label={"Remove " + file.name}
                  onClick={() =>
                    setQueue((old) => old.filter((_, i) => i !== index))
                  }
                >
                  <X size={18} />
                </button>
              </div>
            ))}
            {busy && (
              <>
                <progress value={progress} max="100" />
                <p>{progress}% uploaded · waiting for server confirmation</p>
              </>
            )}
            <button className="button primary" disabled={busy} onClick={send}>
              {busy
                ? "Uploading…"
                : `Upload ${queue.length} document${queue.length === 1 ? "" : "s"}`}
            </button>
          </div>
        )}
        {results.length > 0 && (
          <div className="upload-queue">
            <h3>Upload results</h3>
            {results.map((result, i) => (
              <div className="queue-row" key={i}>
                {result.error ? (
                  <AlertTriangle className="red" />
                ) : (
                  <CheckCircle2 className="green" />
                )}
                <span>
                  {result.filename}
                  <small>
                    {result.error ||
                      "Stored securely. Processing runs in the background."}
                  </small>
                </span>
                {result.document_id && (
                  <Link href={"/documents/" + result.document_id}>
                    Open document
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <div className="three-grid">
        {[
          [
            "1",
            "Store securely",
            "Originals stay private and retain their checksum.",
          ],
          [
            "2",
            "Extract & verify",
            "Parse source data and check financial arithmetic.",
          ],
          [
            "3",
            "Review exceptions",
            "Resolve issues with original evidence and an audit trail.",
          ],
        ].map(([step, title, text]) => (
          <div className="mini-card" key={step}>
            <span className="step">{step}</span>
            <h3>{title}</h3>
            <p>{text}</p>
          </div>
        ))}
      </div>
    </>
  );
}
