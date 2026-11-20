import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, UNAUTHORIZED_EVENT, type Me } from "../lib/api";
import { BrandMark, cx } from "../components/ui";
import { BinaryField } from "../components/BinaryField";

const UserContext = createContext<Me | null>(null);

/** The signed-in user (only inside <AuthGate>). */
export function useMe(): Me {
  const me = useContext(UserContext);
  if (!me) throw new Error("useMe() outside <AuthGate>");
  return me;
}

const field =
  "mt-2 h-12 w-full rounded-lg border border-line bg-navy-950/80 px-4 font-code text-base text-ink outline-none transition-colors focus:border-teal/60";

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
    <div className="relative isolate min-h-screen">
      <div className="signin-atmosphere absolute inset-0 -z-10" aria-hidden="true" />
      <BinaryField />

      <div className="relative z-10 mx-auto grid min-h-screen max-w-6xl items-center gap-10 px-6 py-12 md:grid-cols-[1fr_auto_1fr] md:gap-16">
        {/* Brand side — first on small screens, right of the bar on wide ones */}
        <div className="flex flex-col items-center gap-6 text-center md:order-3">
          <BrandMark className="w-[min(60vw,300px)] text-teal drop-shadow-[0_0_40px_rgb(66_214_197/0.35)]" />
          <span className="font-code text-5xl tracking-[0.2em] text-ink sm:text-6xl">BCSS</span>
        </div>

        <span aria-hidden="true" className="signin-divider mx-auto h-px w-40 md:order-2 md:h-[60vh] md:w-px" />

        <form onSubmit={submit} className="mx-auto w-full max-w-sm md:order-1">
          <h1 className="font-code text-4xl text-ink">{signup ? "Create account" : "Sign in"}</h1>
          <p className="mt-3 text-sm text-muted">
            {signup ? "Your apps are private to your account." : "Use your BCSS username and password."}
          </p>
          <label className="mt-8 block">
            <span className="font-code text-xs uppercase tracking-[0.2em] text-muted">Username</span>
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
          <label className="mt-5 block">
            <span className="font-code text-xs uppercase tracking-[0.2em] text-muted">Password</span>
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
            className="mt-8 h-12 w-full rounded-full bg-teal font-code text-base tracking-[0.12em] text-navy-950 uppercase shadow-[0_10px_30px_-12px_rgb(66_214_197/0.8)] transition-[background-color,opacity] duration-300 hover:bg-teal-soft disabled:opacity-40"
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
              className="mt-5 w-full text-center font-code text-sm text-teal hover:underline"
            >
              {signup ? "I already have an account" : "Create an account"}
            </button>
          )}
          <a
            href="#top"
            className={cx("block text-center font-code text-sm text-muted hover:text-ink", signupOpen ? "mt-3" : "mt-6")}
          >
            ← Back to the website
          </a>
        </form>
      </div>
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
      () => setState("signed-out"),
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
