import { AuthNotConfiguredError } from "./supabase";

export type ErrorKind =
  | "invalid_credentials"
  | "email_not_confirmed"
  | "already_registered"
  | "rate_limited"
  | "weak_password"
  | "network"
  | "not_configured"
  | "provider_disabled"
  | "expired_link"
  | "other";

export interface FriendlyError {
  kind: ErrorKind;
  message: string;
}

/** Turn Supabase / network errors into sentences that say what happened and what to do. */
export function friendlyError(err: unknown): FriendlyError {
  if (err instanceof AuthNotConfiguredError) return { kind: "not_configured", message: err.message };
  const e = (err ?? {}) as { message?: string; status?: number; code?: string };
  const msg = (e.message || String(err || "")).trim();
  const code = e.code || "";
  const low = msg.toLowerCase();

  if (code === "invalid_credentials" || low.includes("invalid login credentials"))
    return { kind: "invalid_credentials", message: "That email and password don't match an account. Check them, or reset your password." };
  if (code === "email_not_confirmed" || low.includes("email not confirmed"))
    return { kind: "email_not_confirmed", message: "Confirm your email first: open the link we sent you. You can send it again below." };
  if (code === "user_already_exists" || low.includes("already registered") || low.includes("already been registered"))
    return { kind: "already_registered", message: "An account with this email already exists. Sign in instead, or reset your password." };
  if (e.status === 429 || code === "over_email_send_rate_limit" || code === "over_request_rate_limit" ||
      low.includes("rate limit") || low.includes("for security purposes"))
    return { kind: "rate_limited", message: "Too many attempts for now. Wait a minute, then try again." };
  if (code === "weak_password" || low.includes("password should"))
    return { kind: "weak_password", message: msg.endsWith(".") ? msg : `${msg}.` };
  if (code === "provider_disabled" || low.includes("provider is not enabled") || low.includes("unsupported provider"))
    return { kind: "provider_disabled", message: "This sign-in option isn't turned on yet. Use another option, or enable it in Supabase (see web/README.md)." };
  if (code === "otp_expired" || low.includes("expired") || low.includes("invalid flow state") || low.includes("code verifier"))
    return { kind: "expired_link", message: "This link has expired or was already used. Request a new one." };
  if (low.includes("failed to fetch") || low.includes("networkerror") || low.includes("load failed"))
    return { kind: "network", message: "Can't reach the sign-in service. Check your connection and try again." };
  return { kind: "other", message: msg ? (msg.endsWith(".") ? msg : `${msg}.`) : "Something went wrong. Try again." };
}
