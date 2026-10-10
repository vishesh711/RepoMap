import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AuthLayout } from "../components/AuthLayout";
import { useAuth } from "../lib/auth";
import { friendlyError } from "../lib/errors";
import { safeNext } from "../lib/validation";

/**
 * Where GitHub, Google, magic links and confirmation emails send people back.
 * supabase-js exchanges the one-time code in the URL on load; this page waits for
 * the session, then continues to `next`.
 */
export default function AuthCallback() {
  const { session, loading } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = safeNext(params.get("next"));
  const providerError = params.get("error_description") || params.get("error");
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (session) navigate(next, { replace: true });
  }, [session, next, navigate]);

  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), 8000);
    return () => clearTimeout(t);
  }, []);

  const failed = providerError || (!loading && timedOut && !session);
  if (failed) {
    const message = providerError
      ? friendlyError({ message: providerError.replace(/\+/g, " ") }).message
      : "We couldn't finish signing you in. The link may have expired or been opened in a different browser.";
    return (
      <AuthLayout>
        <header className="form-head">
          <h2>Sign-in didn't finish</h2>
          <p>{message}</p>
        </header>
        <Link className="btn primary" to="/login"><span>Back to sign in</span></Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout>
      <p className="muted" role="status"><span className="spinner dark" aria-hidden="true" /> Signing you in…</p>
    </AuthLayout>
  );
}
