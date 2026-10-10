import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { AuthLayout } from "../components/AuthLayout";
import { Alert, Button, PasswordField, TextField } from "../components/ui";
import { useAuth } from "../lib/auth";
import { friendlyError, type FriendlyError } from "../lib/errors";
import { validateConfirm, validateEmail, validateNewPassword } from "../lib/validation";
import { CheckEmail } from "./Login";

export function ForgotPassword() {
  const { sendPasswordReset } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState((location.state as { email?: string } | null)?.email ?? "");
  const [touched, setTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    setError(null);
    if (validateEmail(email)) return;
    setSubmitting(true);
    try {
      await sendPasswordReset(email);
      setSent(true);
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <AuthLayout>
        {/* Same message whether or not the account exists, so this page can't be used to find accounts. */}
        <CheckEmail email={email} what="a password reset link, if an account uses this address,"
                    onBack={() => setSent(false)} onResend={() => sendPasswordReset(email)} />
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <header className="form-head">
        <h2>Reset your password</h2>
        <p>Enter the email you signed up with and we'll send you a link to choose a new password.</p>
      </header>
      <form onSubmit={onSubmit} noValidate className="form">
        <TextField id="fp-email" label="Email" type="email" autoComplete="email" inputMode="email" value={email}
                   onChange={(e) => setEmail(e.target.value)} error={touched ? validateEmail(email) : null} autoFocus />
        {error && <Alert>{error.message}</Alert>}
        <Button type="submit" loading={submitting}>Send reset link</Button>
      </form>
      <p className="switch"><Link to="/login" state={{ email }}>Back to sign in</Link></p>
    </AuthLayout>
  );
}

export function ResetPassword() {
  const { session, loading, recovering, updatePassword } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [waited, setWaited] = useState(false);

  // The reset link signs the person in first; give that exchange a moment before saying the link is bad.
  useEffect(() => {
    const t = setTimeout(() => setWaited(true), 2500);
    return () => clearTimeout(t);
  }, []);

  const errors = { password: validateNewPassword(password), confirm: validateConfirm(password, confirm) };

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setError(null);
    if (errors.password || errors.confirm) return;
    setSubmitting(true);
    try {
      await updatePassword(password);
      navigate("/app", { replace: true, state: { notice: "Your password was updated." } });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (!session && (loading || !waited)) {
    return <AuthLayout><p className="muted" role="status"><span className="spinner dark" aria-hidden="true" /> Checking your reset link…</p></AuthLayout>;
  }
  if (!session) {
    return (
      <AuthLayout>
        <header className="form-head">
          <h2>This link doesn't work anymore</h2>
          <p>Reset links can be used once and expire after a while. Request a fresh one.</p>
        </header>
        <Link className="btn primary" to="/forgot-password"><span>Send a new reset link</span></Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <header className="form-head">
        <h2>Choose a new password</h2>
        <p>{recovering ? "You're almost done." : "Set a new password for your account."}</p>
      </header>
      <form onSubmit={onSubmit} noValidate className="form">
        <PasswordField id="rp-password" label="New password" autoComplete="new-password" value={password} showRules
                       onChange={(e) => setPassword(e.target.value)} error={submitted ? errors.password : null} autoFocus />
        <PasswordField id="rp-confirm" label="Confirm new password" autoComplete="new-password" value={confirm}
                       onChange={(e) => setConfirm(e.target.value)} error={submitted ? errors.confirm : null} />
        {error && <Alert>{error.message}</Alert>}
        <Button type="submit" loading={submitting}>Save new password</Button>
      </form>
    </AuthLayout>
  );
}
