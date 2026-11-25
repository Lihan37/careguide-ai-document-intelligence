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

export function Evaluation({ version }: { version: number }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<Record<string, unknown>>("/api/evaluation/results")
      .then(setData)
      .catch((e) => setError(e.message));
  }, [version]);
  return (
    <section className="panel section-pad">
      <h2>Measured evaluation results</h2>
      <p>
        Generated from synthetic fixtures by scripts/evaluate.py. Deterministic
        results do not measure live AI performance. No 1000-page benchmark is
        claimed.
      </p>
      {error && <div className="alert error">{error}</div>}
      {data ? <Json data={data} /> : <p>Loading results…</p>}
    </section>
  );
}
