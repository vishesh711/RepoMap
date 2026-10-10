import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Provider, Session, User } from "@supabase/supabase-js";
import { client, isConfigured, siteUrl, supabase } from "./supabase";

export type OAuthProvider = Extract<Provider, "github" | "google">;

interface AuthState {
  session: Session | null;
  user: User | null;
  /** True until the stored session (if any) has been read. */
  loading: boolean;
  /** True after arriving from a password-reset link, until the new password is saved. */
  recovering: boolean;
  configured: boolean;
}

interface AuthActions {
  signInWithPassword(email: string, password: string): Promise<void>;
  /** Returns true when the account needs email confirmation before it can sign in. */
  signUp(input: { name: string; email: string; password: string }): Promise<{ needsConfirmation: boolean }>;
  signInWithProvider(provider: OAuthProvider, next?: string): Promise<void>;
  sendMagicLink(email: string, next?: string): Promise<void>;
  resendConfirmation(email: string): Promise<void>;
  sendPasswordReset(email: string): Promise<void>;
  updatePassword(password: string): Promise<void>;
  signOut(): Promise<void>;
}

const AuthContext = createContext<(AuthState & AuthActions) | null>(null);

const callbackUrl = (next?: string) =>
  siteUrl(`/auth/callback${next ? `?next=${encodeURIComponent(next)}` : ""}`);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(isConfigured);
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });
    const { data } = supabase.auth.onAuthStateChange((event, next) => {
      setSession(next);
      if (event === "PASSWORD_RECOVERY") setRecovering(true);
      if (event === "SIGNED_OUT") setRecovering(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthState & AuthActions>(() => ({
    session,
    user: session?.user ?? null,
    loading,
    recovering,
    configured: isConfigured,

    async signInWithPassword(email, password) {
      const { error } = await client().auth.signInWithPassword({ email: email.trim(), password });
      if (error) throw error;
    },

    async signUp({ name, email, password }) {
      const { data, error } = await client().auth.signUp({
        email: email.trim(),
        password,
        options: { data: { full_name: name.trim() }, emailRedirectTo: callbackUrl() },
      });
      if (error) throw error;
      // With "Confirm email" on, Supabase returns a user without a session. If the email is
      // already registered it returns a user with no identities instead of an error.
      if (data.user && data.user.identities && data.user.identities.length === 0) {
        throw Object.assign(new Error("User already registered"), { code: "user_already_exists" });
      }
      return { needsConfirmation: !data.session };
    },

    async signInWithProvider(provider, next) {
      const { error } = await client().auth.signInWithOAuth({
        provider,
        options: {
          redirectTo: callbackUrl(next),
          scopes: provider === "github" ? "read:user user:email" : undefined,
        },
      });
      if (error) throw error;
      // The browser now navigates to the provider.
    },

    async sendMagicLink(email, next) {
      const { error } = await client().auth.signInWithOtp({
        email: email.trim(),
        options: { emailRedirectTo: callbackUrl(next), shouldCreateUser: true },
      });
      if (error) throw error;
    },

    async resendConfirmation(email) {
      const { error } = await client().auth.resend({
        type: "signup",
        email: email.trim(),
        options: { emailRedirectTo: callbackUrl() },
      });
      if (error) throw error;
    },

    async sendPasswordReset(email) {
      const { error } = await client().auth.resetPasswordForEmail(email.trim(), {
        redirectTo: siteUrl("/reset-password"),
      });
      if (error) throw error;
    },

    async updatePassword(password) {
      const { error } = await client().auth.updateUser({ password });
      if (error) throw error;
      setRecovering(false);
    },

    async signOut() {
      if (!supabase) return;
      await supabase.auth.signOut();
    },
  }), [session, loading, recovering]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** A readable name for the signed-in person. */
export function displayName(user: User | null): string {
  if (!user) return "";
  const m = user.user_metadata ?? {};
  return (m.full_name || m.name || m.user_name || user.email?.split("@")[0] || "there") as string;
}
