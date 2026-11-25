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

export function SettingsPage({ config }: { config: Config | null }) {
  const [health, setHealth] = useState("Not checked");
  return (
    <>
      <section className="panel section-pad">
        <h2>Environment capabilities</h2>
        {config && (
          <div className="settings-grid">
            {[
              ["Processing mode", config.execution_mode],
              ["Extraction", config.extraction_mode],
              ["Database", config.database],
              [
                "OCR",
                config.ocr_available
                  ? "Available"
                  : "Unavailable — install Tesseract",
              ],
              [
                "AI extraction",
                config.ai_available
                  ? "Credentials configured; live calls depend on provider"
                  : "Unavailable — configure LLM_API_KEY",
              ],
              [
                "Semantic search",
                config.semantic_available
                  ? "Configured"
                  : "Unavailable — configure PostgreSQL and embeddings",
              ],
              ["LLM model", config.llm_model],
              ["Embedding model", config.embedding_model],
              [
                "Upload limits",
                `${config.max_upload_files} files · ${config.max_file_mb} MB each`,
              ],
              ["PDF page limit", config.max_pages],
            ].map(([name, value]) => (
              <div key={String(name)}>
                <span>{name}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        )}
        <p className="small-note">{config?.notice}</p>
      </section>
      <section className="panel section-pad">
        <h2>Service readiness</h2>
        <p>{health}</p>
        <button
          className="button secondary"
          onClick={() =>
            api<{ status: string; worker_liveness: string }>("/api/ready")
              .then((r) => setHealth(`${r.status}. ${r.worker_liveness}`))
              .catch((e) => setHealth(e.message))
          }
        >
          Check services
        </button>
      </section>
      <section className="panel section-pad">
        <h2>Server configuration</h2>
        <p>
          Update environment variables in the project’s .env file and restart
          the API and worker. Credentials are never returned to the browser.
        </p>
        <p>
          For OCR on Windows, install Tesseract and set TESSERACT_CMD to its
          executable. The Docker image includes OCR. See docs/setup-windows.md
          for provider and PostgreSQL setup.
        </p>
      </section>
    </>
  );
}
