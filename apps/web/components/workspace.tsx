"use client";

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
import { Login } from "./login";
import { Dashboard } from "./dashboard";
import { Upload } from "./upload";
import { DocumentList } from "./document-list";
import { DocumentDetail } from "./document-detail";
import { Jobs } from "./jobs";
import { ComparisonPage } from "./comparison";
import { SettingsPage } from "./settings";
import { Evaluation } from "./evaluation";

import { useEffect, useRef, useState } from "react";

import Link from "next/link";

import { usePathname } from "next/navigation";

import {
  LayoutDashboard,
  Files,
  UploadCloud,
  Activity,
  ClipboardCheck,
  Columns3,
  Search,
  ChartNoAxesCombined,
  Settings,
  LogOut,
  FileText,
  CheckCircle2,
  AlertTriangle,
  LoaderCircle,
  X,
  ShieldCheck,
  RefreshCw,
  FolderOpen,
} from "lucide-react";

const nav = [
  ["/", "Dashboard", LayoutDashboard],
  ["/documents", "Documents", Files],
  ["/upload", "Upload Documents", UploadCloud],
  ["/jobs", "Processing Jobs", Activity],
  ["/review", "Review Queue", ClipboardCheck],
  ["/comparison", "Document Comparison", Columns3],
  ["/search", "Search", Search],
  ["/evaluation", "Evaluation", ChartNoAxesCombined],
  ["/settings", "Settings", Settings],
] as const;

export default function Workspace() {
  const path = usePathname();
  const [user, setUser] = useState<{ username: string; role: string } | null>(
    null,
  );
  const [checking, setChecking] = useState(true);
  const [config, setConfig] = useState<Config | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    api<{ username: string; role: string }>("/api/auth/me")
      .then(setUser)
      .catch(() => {})
      .finally(() => setChecking(false));
  }, []);
  useEffect(() => {
    if (user)
      api<Config>("/api/settings")
        .then(setConfig)
        .catch((e) => setError(e.message));
  }, [user]);
  const refresh = () => setVersion((n) => n + 1);
  const action = async (task: () => Promise<unknown>, success: string) => {
    setError("");
    try {
      await task();
      setNotice(success);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  if (checking)
    return (
      <main className="loading">
        <LoaderCircle className="spin" /> Connecting to workspace…
      </main>
    );
  if (!user) return <Login onLogin={setUser} />;
  const current = nav.find((n) => n[0] === path);
  const title = path.startsWith("/documents/")
    ? "Document workspace"
    : current?.[1] || "Page not found";
  return (
    <div className="app">
      <aside className="sidebar">
        <Link className="brand" href="/">
          <span className="brand-mark">
            <Files size={24} />
          </span>
          <span>
            careguide<span className="brand-sub">DOCUMENT INTELLIGENCE</span>
          </span>
        </Link>
        <div className="workspace-label">
          WORKSPACE <span>LOCAL</span>
        </div>
        <nav aria-label="Main navigation">
          {nav.map(([url, name, Icon]) => (
            <Link
              key={url}
              className={
                path === url ||
                (url === "/documents" && path.startsWith("/documents/"))
                  ? "nav-link active"
                  : "nav-link"
              }
              href={url}
            >
              <Icon size={19} />
              {name}
            </Link>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <ShieldCheck size={19} />
          <div>
            Private workspace<small>Authenticated document access</small>
          </div>
        </div>
        <div className="profile">
          <span className="avatar">{user.username[0].toUpperCase()}</span>
          <div>
            {user.username}
            <small>{label(user.role)}</small>
          </div>
          <button
            className="icon-button"
            aria-label="Sign out"
            onClick={() =>
              action(async () => {
                await api("/api/auth/logout", { method: "POST" });
                setUser(null);
              }, "Signed out")
            }
          >
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span> {title}
          </span>
          <div className="top-actions">
            <span className="local-label">Local environment</span>
            <button
              className="icon-button"
              aria-label="Refresh data"
              onClick={refresh}
            >
              <RefreshCw size={17} />
            </button>
            <span className="avatar small">
              {user.username[0].toUpperCase()}
            </span>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">FINANCIAL OPERATIONS</div>
              <h1>{title}</h1>
              <p>
                {path === "/"
                  ? "A clear view of your documents, processing, and exceptions."
                  : descriptions[path] ||
                    "Inspect the source, verify the details, and keep an audit trail."}
              </p>
            </div>
            {path !== "/upload" && (
              <Link href="/upload" className="button primary">
                <UploadCloud size={17} /> Upload documents
              </Link>
            )}
          </div>
          {config && (
            <div className="mode-banner">
              <ShieldCheck size={17} />
              <span>
                {config.extraction_mode === "deterministic_demo"
                  ? "Deterministic demonstration mode"
                  : config.extraction_mode === "gemini_auto"
                    ? "Deterministic first, Gemini when needed"
                    : "Configured AI extraction"}
                <span className="separator">·</span>
                {config.extraction_mode === "deterministic_demo"
                  ? "Local invoice parsing"
                  : config.ai_available
                    ? "AI credentials configured"
                    : "AI unavailable — no API credentials"}
                <span className="separator">·</span>
                {config.ocr_available ? "OCR available" : "OCR unavailable"}
              </span>
              <Link href="/settings">Configuration</Link>
            </div>
          )}
          {error && (
            <div role="alert" className="alert error">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {path === "/" ? (
            <Dashboard version={version} onError={setError} />
          ) : path === "/upload" ? (
            <Upload config={config} onComplete={refresh} />
          ) : path === "/documents" ||
            path === "/review" ||
            path === "/search" ? (
            <DocumentList
              mode={path}
              config={config}
              version={version}
              onError={setError}
            />
          ) : path.startsWith("/documents/") ? (
            <DocumentDetail
              id={path.split("/")[2]}
              version={version}
              action={action}
            />
          ) : path === "/jobs" ? (
            <Jobs version={version} action={action} />
          ) : path === "/comparison" ? (
            <ComparisonPage version={version} onError={setError} />
          ) : path === "/settings" ? (
            <SettingsPage config={config} />
          ) : path === "/evaluation" ? (
            <Evaluation version={version} />
          ) : (
            <Empty
              text="Page not found"
              sub="Choose a workspace page from the navigation."
            />
          )}
          <footer>
            <span>CareGuide Document Intelligence</span>
            <span>Private by default. Every correction is recorded.</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

const descriptions: Record<string, string> = {
  "/documents":
    "Your original files and extracted financial records, in one place.",
  "/upload":
    "Bring invoices, scans, and spreadsheets into a single review workflow.",
  "/jobs": "Follow each processing stage and recover failed documents.",
  "/review":
    "Resolve exceptions with source evidence and a complete audit trail.",
  "/comparison":
    "Verify financial fields across PDFs, spreadsheets, and receipts.",
  "/search": "Find the document behind every number.",
  "/evaluation": "Measured results from a labeled synthetic dataset.",
  "/settings":
    "Processing capabilities and configuration for this environment.",
};
