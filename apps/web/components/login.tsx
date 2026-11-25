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

export function Login({
  onLogin,
}: {
  onLogin: (user: { username: string; role: string }) => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <main className="login">
      <div className="login-intro">
        <span className="brand-mark">
          <Files size={30} />
        </span>
        <h1>
          Your documents.
          <br />A clearer picture.
        </h1>
        <p>
          Extract financial information, verify the numbers,
          <br />
          and review every exception with confidence.
        </p>
        <div className="login-features">
          <span>
            <ShieldCheck /> Private document access
          </span>
          <span>
            <ClipboardCheck /> Traceable human review
          </span>
          <span>
            <Columns3 /> Cross-document verification
          </span>
        </div>
        <small>CAREGUIDE · DOCUMENT INTELLIGENCE</small>
      </div>
      <form
        className="login-form"
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          const data = new FormData(event.currentTarget);
          try {
            onLogin(
              await api("/api/auth/login", {
                method: "POST",
                body: JSON.stringify(Object.fromEntries(data)),
              }),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="eyebrow">PRIVATE WORKSPACE</div>
        <h2>Welcome back</h2>
        <p>Sign in with your configured local credentials.</p>
        <label>
          Username
          <input
            name="username"
            defaultValue="reviewer"
            autoComplete="username"
            required
          />
        </label>
        <label>
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <div role="alert" className="alert error">
            {error}
          </div>
        )}
        <button className="button primary" disabled={busy}>
          {busy ? "Signing in…" : "Sign in to workspace"}
        </button>
        <p className="small-note">
          Local credentials are configured in the project’s .env file. API
          secrets stay on the server.
        </p>
      </form>
    </main>
  );
}
