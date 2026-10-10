import { useLocation, useNavigate } from "react-router-dom";
import { Alert, Button, Wordmark } from "../components/ui";
import { displayName, useAuth } from "../lib/auth";

const PROVIDER_LABEL: Record<string, string> = { github: "GitHub", google: "Google", email: "email" };

export default function Dashboard() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  const notice = (useLocation().state as { notice?: string } | null)?.notice;
  if (!user) return null;
  const providers = (user.app_metadata?.providers as string[] | undefined) ?? [user.app_metadata?.provider ?? "email"];
  const avatar = user.user_metadata?.avatar_url as string | undefined;
  const name = displayName(user);

  return (
    <div className="app">
      <header className="app-top">
        <Wordmark />
        <div className="who">
          {avatar ? <img src={avatar} alt="" className="avatar" /> : <span className="avatar initials" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>}
          <span className="who-name">{name}</span>
          <Button variant="ghost" type="button" onClick={async () => { await signOut(); navigate("/login", { replace: true }); }}>Sign out</Button>
        </div>
      </header>
      <main className="app-main">
        {notice && <Alert tone="success">{notice}</Alert>}
        <h1>Welcome, {name}</h1>
        <p className="muted">
          Signed in as <strong>{user.email}</strong> with {providers.map((p) => PROVIDER_LABEL[p] ?? p).join(" and ")}.
        </p>
        <section className="card next">
          <h2>Next: map a repository</h2>
          <p>Connecting repos and saving maps to your account is coming next. Until then, the command line works on any repo:</p>
          <pre><code>pipx install git+https://github.com/vishesh711/repomap{"\n"}repomap owner/repo{"\n"}repomap --diff main</code></pre>
        </section>
      </main>
    </div>
  );
}
