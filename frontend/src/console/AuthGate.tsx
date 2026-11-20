import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, AuthError, UNAUTHORIZED_EVENT } from "../lib/api";
import { Brand } from "../components/ui";

type State = "checking" | "signed-out" | "signed-in";

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.login(password);
      setPassword("");
      onSignedIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center px-5">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-navy-900/50 p-8">
        <Brand />
        <h1 className="mt-8 font-display text-2xl font-semibold tracking-[-0.02em]">Sign in to the console</h1>
        <p className="mt-2 text-sm text-muted">Enter the OwnCloud admin password.</p>
        <label className="mt-6 block">
          <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Password</span>
          <input
            type="password"
            autoComplete="current-password"
            autoFocus
            value={password}
            maxLength={256}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-2 h-11 w-full rounded-lg border border-line bg-navy-950/70 px-3 text-sm text-ink outline-none transition-colors focus:border-teal/50"
          />
        </label>
        {error && <p className="mt-3 text-xs text-danger" role="alert">{error}</p>}
        <button
          type="submit"
          disabled={!password || busy}
          className="mt-6 h-11 w-full rounded-full bg-teal text-sm font-medium text-navy-950 transition-[background-color,opacity] duration-300 hover:bg-teal-soft disabled:opacity-40"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <a href="#top" className="mt-6 block text-center text-[13px] text-muted hover:text-ink">
          ← Back to the website
        </a>
      </form>
    </div>
  );
}

/** Renders its children only for an authenticated session; any 401 sends the user back here. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>("checking");

  useEffect(() => {
    api.me().then(
      () => setState("signed-in"),
      (e) => setState(e instanceof AuthError ? "signed-out" : "signed-in"),
    );
    const onUnauthorized = () => setState("signed-out");
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (state === "checking") return <div className="min-h-screen" />;
  if (state === "signed-out") return <SignIn onSignedIn={() => setState("signed-in")} />;
  return <>{children}</>;
}

export async function signOut() {
  try {
    await api.logout();
  } finally {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}
