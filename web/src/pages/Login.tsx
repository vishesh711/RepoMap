import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { AuthLayout } from "../components/AuthLayout";
import { Alert, Button, Divider, OAuthButtons, PasswordField, TextField } from "../components/ui";
import { useAuth, type OAuthProvider } from "../lib/auth";
import { friendlyError, type FriendlyError } from "../lib/errors";
import { safeNext, validateEmail } from "../lib/validation";

type Mode = "password" | "link";

export function useOAuthSignIn(next: string) {
  const { signInWithProvider } = useAuth();
  const [busy, setBusy] = useState<OAuthProvider | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const start = async (p: OAuthProvider) => {
    setError(null);
    setBusy(p);
    try {
      await signInWithProvider(p, next);
    } catch (e) {
      setError(friendlyError(e));
      setBusy(null);
    }
  };
  return { busy, error, start };
}

export function CheckEmail({ email, what, onBack, onResend }: {
  email: string; what: string; onBack: () => void; onResend?: () => Promise<void>;
}) {
  const [state, setState] = useState<"idle" | "sending" | "sent" | FriendlyError>("idle");
  const resend = async () => {
    if (!onResend) return;
    setState("sending");
    try { await onResend(); setState("sent"); } catch (e) { setState(friendlyError(e)); }
  };
  return (
    <section className="check-email" aria-live="polite">
      <div className="envelope" aria-hidden="true">✉</div>
      <h2>Check your email</h2>
      <p>We sent {what} to <strong>{email}</strong>. It can take a minute to arrive; check spam if you don't see it.</p>
      {state === "sent" && <Alert tone="success">Sent again.</Alert>}
      {typeof state === "object" && <Alert>{state.message}</Alert>}
      <div className="row">
        {onResend && <Button variant="secondary" type="button" loading={state === "sending"} onClick={resend}>Send it again</Button>}
        <Button variant="ghost" type="button" onClick={onBack}>Use a different email</Button>
      </div>
    </section>
  );
}

export default function Login() {
  const { user, loading, signInWithPassword, sendMagicLink, resendConfirmation } = useAuth();
  const [params] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const oauth = useOAuthSignIn(next);

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? "");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(
    params.get("error") ? { kind: "other", message: params.get("error")! } : null);
  const [sentLink, setSentLink] = useState(false);

  if (!loading && user) return <Navigate to={next} replace />;

  const emailError = touched ? validateEmail(email) : null;
  const passwordError = touched && mode === "password" && !password ? "Enter your password." : null;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    setError(null);
    if (validateEmail(email) || (mode === "password" && !password)) return;
    setSubmitting(true);
    try {
      if (mode === "password") {
        await signInWithPassword(email, password);
        navigate(next, { replace: true });
      } else {
        await sendMagicLink(email, next);
        setSentLink(true);
      }
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (sentLink) {
    return (
      <AuthLayout>
        <CheckEmail email={email} what="a sign-in link" onBack={() => setSentLink(false)}
                    onResend={() => sendMagicLink(email, next)} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <header className="form-head">
        <h2>Sign in to repomap</h2>
        <p>Welcome back. Pick up where you left off.</p>
      </header>

      <OAuthButtons onPick={oauth.start} busy={oauth.busy} />
      {oauth.error && <Alert>{oauth.error.message}</Alert>}

      <Divider>or with email</Divider>

      <div className="segmented" role="tablist" aria-label="How to sign in with email">
        <button type="button" role="tab" aria-selected={mode === "password"} onClick={() => { setMode("password"); setError(null); }}>
          Password
        </button>
        <button type="button" role="tab" aria-selected={mode === "link"} onClick={() => { setMode("link"); setError(null); }}>
          Email me a link
        </button>
      </div>

      <form onSubmit={onSubmit} noValidate className="form">
        <TextField id="email" label="Email" type="email" autoComplete="email" inputMode="email"
                   value={email} onChange={(e) => setEmail(e.target.value)} error={emailError} autoFocus />
        {mode === "password" ? (
          <PasswordField id="password" label="Password" autoComplete="current-password"
                         value={password} onChange={(e) => setPassword(e.target.value)} error={passwordError}
                         hint={<Link to="/forgot-password" state={{ email }}>Forgot your password?</Link>} />
        ) : (
          <p className="muted small">We'll email you a link that signs you in. No password needed. New here? The link creates your account.</p>
        )}

        {error && (
          <Alert>
            {error.message}
            {error.kind === "email_not_confirmed" && (
              <> <button type="button" className="linklike" onClick={async () => {
                try { await resendConfirmation(email); setError({ kind: "other", message: "Confirmation email sent again." }); }
                catch (e) { setError(friendlyError(e)); }
              }}>Send the confirmation again</button></>
            )}
          </Alert>
        )}

        <Button type="submit" loading={submitting}>{mode === "password" ? "Sign in" : "Email me a sign-in link"}</Button>
      </form>

      <p className="switch">New to repomap? <Link to={`/signup${params.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`}>Create an account</Link></p>
    </AuthLayout>
  );
}
