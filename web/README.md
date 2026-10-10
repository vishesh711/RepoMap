# repomap web app

Sign-in and account creation for repomap: GitHub, Google, email + password, and magic links, on React + TypeScript + Supabase Auth.

| Page | Path |
|---|---|
| Sign in (password or email link) | `/login` |
| Create account | `/signup` |
| Forgot password | `/forgot-password` |
| Choose a new password (from the reset email) | `/reset-password` |
| Where GitHub, Google and email links return | `/auth/callback` |
| Signed-in home (protected) | `/app` |

Without Supabase keys the pages still render in **preview mode**, so you can work on the UI first.

## Run it

```bash
cd web
npm install
npm run dev          # http://localhost:5173
```

`npm test` runs the unit tests, `npm run typecheck` checks types, and `npm run build` makes a production build in `dist/`.

## Connect Supabase (about 10 minutes)

### 1. Create the project and add the keys

1. Create a project at [supabase.com](https://supabase.com).
2. Go to **Project Settings → API** and copy the **Project URL** and the **anon public** key.
3. Put them in `web/.env.local` (copy `.env.example`). This file is git-ignored:
   ```
   VITE_SUPABASE_URL=https://abcd1234.supabase.co
   VITE_SUPABASE_ANON_KEY=eyJ...
   ```
   Both are safe in the browser. Row-Level Security is what protects the data.

### 2. Create the profiles table

Open **SQL Editor → New query**, paste [`supabase/migrations/20261010000000_profiles.sql`](supabase/migrations/20261010000000_profiles.sql), and run it. Or, with the Supabase CLI, run `supabase db push`.

This creates one `profiles` row per account, with the name, avatar and GitHub username, whenever someone signs up. Row-Level Security limits everyone to reading and editing only their own row.

### 3. Tell Supabase where your site is

Go to **Authentication → URL Configuration**:

- **Site URL**: `http://localhost:5173` (your real domain later)
- **Redirect URLs**: add `http://localhost:5173/**`, and later `https://your-domain.com/**`

Every email link and OAuth sign-in comes back to `/auth/callback` or `/reset-password`. Supabase refuses to redirect anywhere not on this list.

### 4. Turn on the sign-in methods

**Email + password and magic links:** go to **Authentication → Providers → Email**. These are on by default. Keep **Confirm email** on, so new accounts verify their address first. The signup page already shows the "check your email" step.

**GitHub:**
1. GitHub → **Settings → Developer settings → OAuth Apps → New OAuth App**.
2. Set **Homepage URL** to `http://localhost:5173`.
3. Set **Authorization callback URL** to the callback shown in Supabase under **Authentication → Providers → GitHub**. It looks like `https://abcd1234.supabase.co/auth/v1/callback`.
4. Paste the **Client ID** and a new **Client secret** into that Supabase page and enable it.

**Google:**
1. Google Cloud Console → **APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Web application**. Set up the OAuth consent screen first if it asks.
2. Under **Authorized redirect URIs**, add the same Supabase callback URL.
3. Paste the **Client ID** and **Client secret** into **Authentication → Providers → Google** and enable it.

A provider you haven't enabled yet shows "This sign-in option isn't turned on yet" instead of failing silently.

### 5. Before real users sign up

Supabase's built-in email sender is rate-limited and meant for testing. Add your own SMTP provider under **Authentication → Emails → SMTP Settings**, and edit the email templates there so the confirmation, magic link and reset emails say "repomap".

## How it fits together

| File | Role |
|---|---|
| `src/lib/supabase.ts` | Client with the PKCE flow. One-time codes from OAuth and email links are exchanged automatically. |
| `src/lib/auth.tsx` | `AuthProvider` and `useAuth()`: session state plus sign in, sign up, OAuth, magic link, resend, reset, update password, sign out. |
| `src/lib/validation.ts` | Email, name and password rules, password strength, and `safeNext`, which only allows same-site redirects after sign-in. |
| `src/lib/errors.ts` | Turns Supabase and network errors into sentences that say what to do. |
| `src/pages/` | Login, Signup, Recovery (forgot and reset), AuthCallback, Dashboard |
| `src/components/` | Layout with the brand panel, plus form fields, buttons and alerts |

### Security notes

- **PKCE flow:** codes in redirect URLs are single-use and tied to the browser that started the sign-in.
- **No open redirects:** `?next=` only accepts paths on this site, so it can't send people to `https://evil.example`.
- **No account enumeration:** "Forgot password" shows the same message whether or not an account exists.
- **Email confirmation:** new email accounts must confirm before their first sign-in. Duplicate sign-ups are told to sign in instead.
- **Row-Level Security:** profiles are private to their owner, and rows are only created by the database trigger.
