"use client";
import Link from "next/link";
import { FolderOpen } from "lucide-react";

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Row = {
  id: string;
  filename: string;
  file_type: string;
  size: number;
  status: string;
  invoice_number: string | null;
  supplier: string | null;
  duration: number;
  uploaded_at: string;
  issue_count: number;
  error: string | null;
  excerpt?: string;
  review_status: string;
};

export type Issue = {
  rule_id: string;
  severity: string;
  explanation: string;
  expected?: string;
  actual?: string;
  difference?: string;
};

export type Job = {
  id: string;
  document_id: string;
  status: string;
  stage: string;
  progress: number;
  pages_processed: number;
  total_pages: number;
  retries: number;
  error: string | null;
};

export type Config = {
  extraction_mode: string;
  execution_mode: string;
  ai_available: boolean;
  semantic_available: boolean;
  ocr_available: boolean;
  database: string;
  max_file_mb: number;
  max_upload_files: number;
  max_pages: number;
  notice: string;
  llm_model: string;
  embedding_model: string;
};

export type Source = {
  sheet?: string;
  page?: number;
  rows?: unknown[][];
  text: string;
  method: string;
  formulas?: unknown[];
};

export type Detail = Row & {
  checksum: string;
  raw: Record<string, unknown>;
  effective: Record<string, unknown>;
  corrected: Record<string, unknown>;
  evidence: Record<string, Record<string, unknown>>;
  issues: Issue[];
  text: string;
  sources: Source[];
  history: Job[];
  audit: {
    action: string;
    detail: unknown;
    created_at: string;
    user_id: string;
  }[];
  extraction_method: string;
  page_count: number;
  sheet_count: number;
};

export type Comparison = {
  id: string;
  results: {
    left_id: string;
    right_id: string;
    left_filename: string;
    right_filename: string;
    review_status: string;
    fields: {
      field: string;
      left: unknown;
      right: unknown;
      status: string;
      difference: string | null;
      left_source: unknown;
      right_source: unknown;
    }[];
  }[];
};

export const fields = [
  "invoice_number",
  "invoice_date",
  "supplier_name",
  "customer_name",
  "subtotal",
  "tax",
  "total",
  "currency",
  "discount",
  "shipping",
  "credit",
];

export const label = (value: string) =>
  value.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const display = (v: unknown) =>
  v === null || v === undefined
    ? "—"
    : typeof v === "object"
      ? JSON.stringify(v)
      : String(v);

export const date = (s: string) => new Date(s).toLocaleString();

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(API + path, {
    ...options,
    credentials: "include",
    headers: {
      ...(options?.body && !(options.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || response.statusText),
    );
  }
  return response.json();
}

export function Badge({ status }: { status: string }) {
  return (
    <span
      className={
        "badge " +
        (["COMPLETED", "MATCHED", "approved", "PASSED"].includes(status)
          ? "good"
          : ["FAILED", "MISMATCHED"].includes(status)
            ? "bad"
            : ["PROCESSING", "QUEUED"].includes(status)
              ? "blue"
              : "warn")
      }
    >
      {label(status.toLowerCase())}
    </span>
  );
}

export function Empty({
  text = "No documents yet",
  sub = "Upload your first document to start building your workspace.",
}: {
  text?: string;
  sub?: string;
}) {
  return (
    <div className="empty">
      <FolderOpen size={36} />
      <h3>{text}</h3>
      <p>{sub}</p>
      <Link className="button secondary" href="/upload">
        Upload documents
      </Link>
    </div>
  );
}

export function Json({ data }: { data: unknown }) {
  return <pre className="json">{JSON.stringify(data, null, 2)}</pre>;
}

export function Evidence({ value }: { value: unknown }) {
  const v = value as Record<string, unknown> | null;
  return v ? (
    <span className="evidence">
      {v.page
        ? `Page ${v.page}`
        : v.sheet
          ? `Sheet ${v.sheet}${v.row ? ` · row ${v.row}, col ${v.column}` : ""}`
          : "Source"}
      <br />
      {String(v.excerpt || "").slice(0, 140)}
    </span>
  ) : (
    <span className="muted">No evidence recorded</span>
  );
}

export type Action = (
  task: () => Promise<unknown>,
  success: string,
) => Promise<void>;
