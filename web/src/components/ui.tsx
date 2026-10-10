import { useId, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { passwordChecks, passwordStrength, STRENGTH_LABEL } from "../lib/validation";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="logo-mark">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path d="M8.5 8.5h7v5h-7zM16.5 18.5h7v5h-7zM12 13.5v7.5h4.5" fill="none" stroke="#fff" strokeWidth="2.2" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="wordmark">
      <Logo /> <span>repomap</span>
    </span>
  );
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string | null;
  hint?: ReactNode;
  trailing?: ReactNode;
}

export function TextField({ label, error, hint, trailing, id, ...input }: FieldProps) {
  const auto = useId();
  const fid = id ?? auto;
  const describedBy = [error ? `${fid}-err` : "", hint ? `${fid}-hint` : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className={`field${error ? " has-error" : ""}`}>
      <label htmlFor={fid}>{label}</label>
      <div className="input-wrap">
        <input id={fid} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...input} />
        {trailing}
      </div>
      {hint && <div className="hint" id={`${fid}-hint`}>{hint}</div>}
      {error && <div className="error" id={`${fid}-err`} role="alert">{error}</div>}
    </div>
  );
}

export function PasswordField({ showRules = false, value, ...rest }: FieldProps & { showRules?: boolean; value: string }) {
  const [visible, setVisible] = useState(false);
  const strength = passwordStrength(value);
  const rules = showRules && value ? (
    <div className="pw-meta">
      <div className={`meter s${strength}`} aria-hidden="true"><span /><span /><span /><span /></div>
      <span className="meter-label">{STRENGTH_LABEL[strength]}</span>
      <ul className="rules">
        {passwordChecks(value).map((c) => (
          <li key={c.id} className={c.ok ? "ok" : ""}>
            <span aria-hidden="true">{c.ok ? "✓" : "·"}</span> {c.label}
            <span className="sr-only">{c.ok ? " (done)" : " (missing)"}</span>
          </li>
        ))}
      </ul>
    </div>
  ) : undefined;
  return (
    <TextField
      {...rest}
      value={value}
      type={visible ? "text" : "password"}
      hint={rules ?? rest.hint}
      trailing={
        <button type="button" className="reveal" onClick={() => setVisible((v) => !v)}
                aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible}>
          {visible ? "Hide" : "Show"}
        </button>
      }
    />
  );
}

export function Button({ loading, children, variant = "primary", ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; variant?: "primary" | "secondary" | "ghost" }) {
  return (
    <button {...rest} className={`btn ${variant} ${rest.className ?? ""}`} disabled={rest.disabled || loading} aria-busy={loading || undefined}>
      {loading && <span className="spinner" aria-hidden="true" />}
      <span>{children}</span>
    </button>
  );
}

export function Alert({ tone = "error", children }: { tone?: "error" | "success" | "info"; children: ReactNode }) {
  return <div className={`alert ${tone}`} role={tone === "error" ? "alert" : "status"}>{children}</div>;
}

const GitHubIcon = () => (
  <svg viewBox="0 0 16 16" width="18" height="18" aria-hidden="true">
    <path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8a8 8 0 0 0 5.47 7.59c.4.07.55-.17.55-.38v-1.33c-2.23.48-2.7-1.07-2.7-1.07-.36-.92-.89-1.17-.89-1.17-.73-.5.06-.49.06-.49.8.06 1.23.83 1.23.83.72 1.22 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2-3.65-.89-3.65-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 0 1 4 0c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48v2.2c0 .21.15.46.55.38A8 8 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
  </svg>
);

const GoogleIcon = () => (
  <svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true">
    <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92a8.78 8.78 0 0 0 2.68-6.62Z" />
    <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
    <path fill="#FBBC05" d="M3.97 10.72A5.4 5.4 0 0 1 3.68 9c0-.6.1-1.18.29-1.72V4.95H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.05l3.01-2.33Z" />
    <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
  </svg>
);

export function OAuthButtons({ onPick, busy }: { onPick: (p: "github" | "google") => void; busy: "github" | "google" | null }) {
  return (
    <div className="oauth">
      <Button type="button" variant="secondary" loading={busy === "github"} disabled={busy !== null} onClick={() => onPick("github")}>
        <GitHubIcon /> Continue with GitHub
      </Button>
      <Button type="button" variant="secondary" loading={busy === "google"} disabled={busy !== null} onClick={() => onPick("google")}>
        <GoogleIcon /> Continue with Google
      </Button>
    </div>
  );
}

export function Divider({ children }: { children: ReactNode }) {
  return <div className="divider" role="separator"><span>{children}</span></div>;
}
