import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { AuthLayout } from "../components/AuthLayout";
import { Alert, Button, Divider, OAuthButtons, PasswordField, TextField } from "../components/ui";
import { useAuth } from "../lib/auth";
import { friendlyError, type FriendlyError } from "../lib/errors";
import { safeNext, validateConfirm, validateEmail, validateName, validateNewPassword } from "../lib/validation";
import { CheckEmail, useOAuthSignIn } from "./Login";

export default function Signup() {
  const { user, loading, signUp, resendConfirmation } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const oauth = useOAuthSignIn(next);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [needsConfirmation, setNeedsConfirmation] = useState(false);

  if (!loading && user && !needsConfirmation) return <Navigate to={next} replace />;

  const show = (f: string) => submitted || touched[f];
  const errors = {
    name: validateName(name),
    email: validateEmail(email),
    password: validateNewPassword(password),
    confirm: validateConfirm(password, confirm),
  };
  const blur = (f: string) => () => setTouched((t) => ({ ...t, [f]: true }));

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    const first = (Object.keys(errors) as (keyof typeof errors)[]).find((k) => errors[k]);
    if (first) {
      document.getElementById(`su-${first}`)?.focus();
      return;
    }
    setSubmitting(true);
    try {
      const res = await signUp({ name, email, password });
      if (res.needsConfirmation) setNeedsConfirmation(true);
      else navigate(next, { replace: true });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (needsConfirmation) {
    return (
      <AuthLayout>
        <CheckEmail email={email} what="a link to confirm your account"
                    onBack={() => setNeedsConfirmation(false)} onResend={() => resendConfirmation(email)} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <header className="form-head">
        <h2>Create your account</h2>
        <p>Map your repos and review every change. Free while repomap is in beta.</p>
      </header>

      <OAuthButtons onPick={oauth.start} busy={oauth.busy} />
      {oauth.error && <Alert>{oauth.error.message}</Alert>}

      <Divider>or sign up with email</Divider>

      <form onSubmit={onSubmit} noValidate className="form">
        <TextField id="su-name" label="Name" autoComplete="name" value={name}
                   onChange={(e) => setName(e.target.value)} onBlur={blur("name")}
                   error={show("name") ? errors.name : null} autoFocus />
        <TextField id="su-email" label="Email" type="email" autoComplete="email" inputMode="email" value={email}
                   onChange={(e) => setEmail(e.target.value)} onBlur={blur("email")}
                   error={show("email") ? errors.email : null} />
        <PasswordField id="su-password" label="Password" autoComplete="new-password" value={password} showRules
                       onChange={(e) => setPassword(e.target.value)} onBlur={blur("password")}
                       error={show("password") ? errors.password : null} />
        <PasswordField id="su-confirm" label="Confirm password" autoComplete="new-password" value={confirm}
                       onChange={(e) => setConfirm(e.target.value)} onBlur={blur("confirm")}
                       error={show("confirm") ? errors.confirm : null} />

        {error && (
          <Alert>
            {error.message}
            {error.kind === "already_registered" && (
              <> <Link to="/login" state={{ email }}>Sign in</Link></>
            )}
          </Alert>
        )}

        <Button type="submit" loading={submitting}>Create account</Button>
        <p className="muted small fine">We'll send a confirmation link to your email before your first sign-in.</p>
      </form>

      <p className="switch">Already have an account? <Link to={`/login${params.get("next") ? `?next=${encodeURIComponent(next)}` : ""}`}>Sign in</Link></p>
    </AuthLayout>
  );
}
