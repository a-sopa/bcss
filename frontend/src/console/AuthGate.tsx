import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, AuthError, UNAUTHORIZED_EVENT, type Me } from "../lib/api";
import { Brand, cx } from "../components/ui";

const UserContext = createContext<Me | null>(null);

/** The signed-in user (only inside <AuthGate>). */
export function useMe(): Me {
  const me = useContext(UserContext);
  if (!me) throw new Error("useMe() outside <AuthGate>");
  return me;
}

const field =
  "mt-2 h-11 w-full rounded-lg border border-line bg-navy-950/70 px-3 text-sm text-ink outline-none transition-colors focus:border-teal/50";

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [signupOpen, setSignupOpen] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.authConfig().then((c) => setSignupOpen(c.signup), () => setSignupOpen(false));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") await api.login(username, password);
      else await api.signup(username, password);
      setPassword("");
      onSignedIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const signup = mode === "signup";
  return (
    <div className="grid min-h-screen place-items-center px-5">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-navy-900/50 p-8">
        <Brand />
        <h1 className="mt-8 font-display text-2xl font-semibold tracking-[-0.02em]">
          {signup ? "Create your account" : "Sign in to the console"}
        </h1>
        <p className="mt-2 text-sm text-muted">
          {signup ? "Your apps are private to your account." : "Use your OwnCloud username and password."}
        </p>
        <label className="mt-6 block">
          <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Username</span>
          <input
            autoComplete="username"
            autoFocus
            value={username}
            maxLength={32}
            spellCheck={false}
            onChange={(e) => setUsername(e.target.value.toLowerCase())}
            className={field}
          />
        </label>
        <label className="mt-4 block">
          <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Password</span>
          <input
            type="password"
            autoComplete={signup ? "new-password" : "current-password"}
            value={password}
            maxLength={256}
            onChange={(e) => setPassword(e.target.value)}
            className={field}
          />
          {signup && <span className="mt-1.5 block text-xs text-muted">At least 12 characters, not containing your username.</span>}
        </label>
        {error && (
          <p className="mt-3 text-xs text-danger" role="alert">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={!username || !password || busy}
          className="mt-6 h-11 w-full rounded-full bg-teal text-sm font-medium text-navy-950 transition-[background-color,opacity] duration-300 hover:bg-teal-soft disabled:opacity-40"
        >
          {busy ? "Please wait…" : signup ? "Create account" : "Sign in"}
        </button>
        {signupOpen && (
          <button
            type="button"
            onClick={() => {
              setMode(signup ? "signin" : "signup");
              setError(null);
            }}
            className="mt-4 w-full text-center text-[13px] text-azure hover:underline"
          >
            {signup ? "I already have an account" : "Create an account"}
          </button>
        )}
        <a href="#top" className={cx("block text-center text-[13px] text-muted hover:text-ink", signupOpen ? "mt-3" : "mt-6")}>
          ← Back to the website
        </a>
      </form>
    </div>
  );
}

/** Renders its children only for a signed-in user; any 401 sends the user back here. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [state, setState] = useState<"checking" | "signed-out" | "signed-in">("checking");

  const load = () =>
    api.me().then(
      (user) => {
        setMe(user);
        setState("signed-in");
      },
      (e) => setState(e instanceof AuthError ? "signed-out" : "signed-in"),
    );

  useEffect(() => {
    void load();
    const onUnauthorized = () => {
      setMe(null);
      setState("signed-out");
    };
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized);
  }, []);

  if (state === "checking" || (state === "signed-in" && !me)) return <div className="min-h-screen" />;
  if (state === "signed-out") return <SignIn onSignedIn={() => void load()} />;
  return <UserContext.Provider value={me}>{children}</UserContext.Provider>;
}

export async function signOut() {
  try {
    await api.logout();
  } finally {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
}
