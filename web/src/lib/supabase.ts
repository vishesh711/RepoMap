import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

/** False until web/.env.local has real Supabase values. The pages still render, so the UI can be previewed. */
export const isConfigured = Boolean(url && anonKey && !url.includes("YOUR-PROJECT"));

export const supabase: SupabaseClient | null = isConfigured
  ? createClient(url!, anonKey!, {
      auth: {
        flowType: "pkce",          // OAuth, magic links and reset links come back with a one-time code
        detectSessionInUrl: true,  // exchange that code automatically on /auth/callback and /reset-password
        persistSession: true,
        autoRefreshToken: true,
      },
    })
  : null;

export class AuthNotConfiguredError extends Error {
  constructor() {
    super("Sign-in isn't connected yet. Add your Supabase URL and anon key to web/.env.local (see web/README.md).");
    this.name = "AuthNotConfiguredError";
  }
}

export function client(): SupabaseClient {
  if (!supabase) throw new AuthNotConfiguredError();
  return supabase;
}

/** Absolute URL on this site, for links Supabase sends people back to. */
export const siteUrl = (path: string) => `${window.location.origin}${path}`;
