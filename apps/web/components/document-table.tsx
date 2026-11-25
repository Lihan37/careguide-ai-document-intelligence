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

export function Table({
  rows,
  highlight,
}: {
  rows: Row[];
  highlight?: string;
}) {
  const excerpt = (text: string) => {
    if (!highlight) return text;
    const index = text.toLowerCase().indexOf(highlight.toLowerCase());
    return index < 0 ? (
      text
    ) : (
      <>
        {text.slice(0, index)}
        <mark>{text.slice(index, index + highlight.length)}</mark>
        {text.slice(index + highlight.length)}
      </>
    );
  };
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Document</th>
            <th>Supplier / invoice</th>
            <th>Status</th>
            <th>Uploaded</th>
            <th>Review</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <Link className="document-name" href={"/documents/" + row.id}>
                  <span
                    className={
                      "file-icon " +
                      ([".xlsx", ".xls", ".csv"].includes(row.file_type)
                        ? "sheet"
                        : "")
                    }
                  >
                    <FileText size={20} />
                  </span>
                  <span>
                    {row.filename}
                    <small>
                      {row.file_type.slice(1).toUpperCase()} ·{" "}
                      {(row.size / 1024).toFixed(1)} KB
                    </small>
                  </span>
                </Link>
                {highlight && row.excerpt && (
                  <div className="search-excerpt">{excerpt(row.excerpt)}</div>
                )}
              </td>
              <td>
                {row.supplier || <span className="muted">Not extracted</span>}
                <small>{row.invoice_number || "—"}</small>
              </td>
              <td>
                <Badge status={row.status} />
              </td>
              <td className="muted">{date(row.uploaded_at)}</td>
              <td>
                {row.issue_count ? (
                  <Link href={"/documents/" + row.id} className="issue-link">
                    {row.issue_count} issues
                  </Link>
                ) : row.status === "COMPLETED" ? (
                  <span className="green">
                    <CheckCircle2 size={16} /> Verified
                  </span>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
