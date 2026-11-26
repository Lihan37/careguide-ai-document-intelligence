"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Ellipsis } from "lucide-react";
import type { DeleteTarget } from "./document-delete-dialog";
import {
  Files,
  UploadCloud,
  Activity,
  ClipboardCheck,
  Columns3,
  Search,
  ChartNoAxesCombined,
  FileText,
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
  ReviewBadge,
  Empty,
  Json,
  Evidence,
  Action,
} from "./shared";

export function Table({
  rows,
  highlight,
  onDelete,
}: {
  rows: Row[];
  highlight?: string;
  onDelete?: (document: DeleteTarget) => void;
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
            <th>Processing status</th>
            <th>Uploaded</th>
            <th>Review status</th>
            <th>Validation</th>
            {onDelete && <th>Actions</th>}
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
                <ProcessingBadge status={row.status} />
              </td>
              <td className="muted">{date(row.uploaded_at)}</td>
              <td><ReviewBadge status={row.review_status} /></td>
              <td>
                {row.issue_count ? (
                  <Link href={"/documents/" + row.id} className="issue-link">
                    {row.issue_count} {row.issue_count === 1 ? "issue" : "issues"}
                  </Link>
                ) : row.status === "COMPLETED" ? (
                  <span className="green">No issues</span>
                ) : (
                  "—"
                )}
              </td>
              {onDelete && (
                <td className="document-actions-cell">
                  <details className="document-row-actions">
                    <summary className="icon-button" aria-label={`Actions for ${row.filename}`}>
                      <Ellipsis size={18} aria-hidden="true" />
                    </summary>
                    <button type="button" className="button secondary" onClick={(event) => {
                      const menu = event.currentTarget.closest("details");
                      menu?.removeAttribute("open");
                      menu?.querySelector("summary")?.focus();
                      onDelete(row);
                    }}>Delete</button>
                  </details>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
