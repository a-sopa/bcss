import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, type AccessToken, type Account } from "../lib/api";
import { Brand, Container, cx } from "../components/ui";
import { signOut, useMe } from "./AuthGate";
import { timeAgo } from "./badges";

const input =
  "h-10 w-full rounded-lg border border-line bg-navy-950/70 px-3 text-sm text-ink outline-none transition-colors placeholder:text-muted/50 focus:border-teal/50";
const smallButton = "h-8 rounded-full border border-line px-3 text-xs transition-colors";

function Card({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-navy-900/40 p-6 sm:p-7">
      <h2 className="font-display text-lg font-semibold tracking-[-0.01em]">{title}</h2>
      {description && <p className="mt-1.5 text-sm leading-relaxed text-muted">{description}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

function Message({ text, error }: { text: string | null; error?: boolean }) {
  if (!text) return null;
  return (
    <p role={error ? "alert" : "status"} className={cx("mt-3 text-xs", error ? "text-danger" : "text-teal")}>
      {text}
    </p>
  );
}

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const day = (ts: number) => new Date(ts * 1000).toLocaleDateString();

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [result, setResult] = useState<{ text: string; error: boolean } | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setResult({ text: "Password changed. Other browsers were signed out.", error: false });
    } catch (e) {
      setResult({ text: errorText(e), error: true });
    }
  };

  return (
    <Card title="Password" description="Changing it signs you out everywhere else.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <input type="password" autoComplete="current-password" placeholder="Current password" value={current}
          onChange={(e) => setCurrent(e.target.value)} className={input} maxLength={256} />
        <input type="password" autoComplete="new-password" placeholder="New password (12+ characters)" value={next}
          onChange={(e) => setNext(e.target.value)} className={input} maxLength={256} />
        <button type="submit" disabled={!current || next.length < 12}
          className="h-10 rounded-full bg-teal px-5 text-sm font-medium text-navy-950 hover:bg-teal-soft disabled:opacity-40">
          Change
        </button>
      </form>
      <Message text={result?.text ?? null} error={result?.error} />
    </Card>
  );
}

function TokensCard() {
  const [tokens, setTokens] = useState<AccessToken[]>([]);
  const [name, setName] = useState("VS Code");
  const [scope, setScope] = useState<"read" | "write">("read");
  const [days, setDays] = useState(90);
  const [created, setCreated] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => api.tokens().then(setTokens, (e) => setError(errorText(e)));
  useEffect(() => {
    void load();
  }, []);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      const token = await api.createToken(name, scope, days);
      setCreated(token.token);
      setCopied(false);
      void load();
    } catch (e) {
      setError(errorText(e));
    }
  };

  const copy = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created);
      setCopied(true);
    } catch {
      setError("Copy failed; select the token and copy it manually.");
    }
  };

  return (
    <Card
      title="Access tokens"
      description="Personal tokens let tools such as the OwnCloud VS Code extension use your account. A token can only read and analyse your code (read), or also save files and redeploy (write). It can never change your password, tokens or users."
    >
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto]">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Token name" maxLength={60} className={input} />
        <select value={scope} onChange={(e) => setScope(e.target.value as "read" | "write")} className={input} aria-label="Scope">
          <option value="read">Read & analyse</option>
          <option value="write">Read, save & redeploy</option>
        </select>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))} className={input} aria-label="Expires after">
          {[30, 90, 180, 365].map((d) => (
            <option key={d} value={d}>{d} days</option>
          ))}
        </select>
        <button type="submit" disabled={!name.trim()}
          className="h-10 rounded-full bg-teal px-5 text-sm font-medium text-navy-950 hover:bg-teal-soft disabled:opacity-40">
          Create
        </button>
      </form>
      <Message text={error} error />

      {created && (
        <div className="mt-5 rounded-xl border border-teal/30 bg-teal/[0.06] p-4">
          <p className="text-sm font-medium">Copy your token now — it will not be shown again.</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 break-all rounded-lg bg-navy-950/80 px-3 py-2 font-mono text-xs text-ink">{created}</code>
            <button type="button" onClick={copy} className={cx(smallButton, "text-teal hover:border-teal/40")}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            In VS Code: install the OwnCloud extension, run <span className="font-mono text-ink/85">OwnCloud: Sign in</span> from the
            Command Palette, enter <span className="font-mono text-ink/85">{window.location.origin}</span> and paste this token.
          </p>
        </div>
      )}

      <ul className="mt-6 divide-y divide-line border-y border-line">
        {tokens.length === 0 && <li className="py-4 text-sm text-muted">No tokens yet.</li>}
        {tokens.map((t) => (
          <li key={t.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3 text-sm">
            <span className="font-medium">{t.name}</span>
            <span className="rounded-full border border-line px-2 py-0.5 font-mono text-[10px] uppercase text-muted">{t.scope}</span>
            <span className="font-mono text-[11px] text-muted">
              expires {day(t.expires_at)} · {t.last_used_at ? `used ${timeAgo(t.last_used_at)}` : "never used"}
            </span>
            <button type="button" onClick={() => api.deleteToken(t.id).then(load, (e) => setError(errorText(e)))}
              className={cx(smallButton, "ml-auto text-muted hover:border-danger/40 hover:text-danger")}>
              Revoke
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function UsersCard({ selfId }: { selfId: string }) {
  const [users, setUsers] = useState<Account[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [error, setError] = useState<string | null>(null);

  const load = () => api.users().then(setUsers, (e) => setError(errorText(e)));
  useEffect(() => {
    void load();
  }, []);

  const run = (action: () => Promise<unknown>) => async () => {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(errorText(e));
    } finally {
      void load();
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    await run(async () => {
      await api.createUser(username, password, role);
      setUsername("");
      setPassword("");
    })();
  };

  return (
    <Card title="Users" description="Each user only sees and manages their own apps. Disabling a user signs them out and stops their apps.">
      <form onSubmit={create} className="grid gap-3 sm:grid-cols-[1fr_1fr_auto_auto]">
        <input value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())} placeholder="Username"
          autoComplete="off" spellCheck={false} maxLength={32} className={input} />
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Initial password (12+)"
          autoComplete="new-password" maxLength={256} className={input} />
        <select value={role} onChange={(e) => setRole(e.target.value as "user" | "admin")} className={input} aria-label="Role">
          <option value="user">User</option>
          <option value="admin">Admin</option>
        </select>
        <button type="submit" disabled={username.length < 3 || password.length < 12}
          className="h-10 rounded-full bg-teal px-5 text-sm font-medium text-navy-950 hover:bg-teal-soft disabled:opacity-40">
          Add
        </button>
      </form>
      <Message text={error} error />

      <div className="mt-6 overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.12em] text-muted">
              <th className="py-2 pr-4 font-normal">User</th>
              <th className="py-2 pr-4 font-normal">Role</th>
              <th className="py-2 pr-4 font-normal">Apps</th>
              <th className="py-2 pr-4 font-normal">Since</th>
              <th className="py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const self = u.id === selfId;
              return (
                <tr key={u.id} className="border-b border-line/60 last:border-0">
                  <td className="py-3 pr-4">
                    <span className={cx("font-medium", u.disabled && "text-muted line-through")}>{u.username}</span>
                    {self && <span className="ml-2 font-mono text-[10px] text-teal">you</span>}
                  </td>
                  <td className="py-3 pr-4 font-mono text-xs">{u.role}</td>
                  <td className="py-3 pr-4 font-mono text-xs">{u.app_count ?? 0}</td>
                  <td className="py-3 pr-4 font-mono text-xs text-muted">{day(u.created_at)}</td>
                  <td className="py-3">
                    {!self && (
                      <div className="flex justify-end gap-2">
                        <button type="button" className={cx(smallButton, "text-ink/85 hover:border-teal/40")}
                          onClick={run(() => api.updateUser(u.id, { role: u.role === "admin" ? "user" : "admin" }))}>
                          {u.role === "admin" ? "Make user" : "Make admin"}
                        </button>
                        <button type="button" className={cx(smallButton, "text-ink/85 hover:border-warn/40")}
                          onClick={run(() => api.updateUser(u.id, { disabled: !u.disabled }))}>
                          {u.disabled ? "Enable" : "Disable"}
                        </button>
                        <button type="button" className={cx(smallButton, "text-muted hover:border-danger/40 hover:text-danger")}
                          onClick={run(async () => {
                            if (window.confirm(`Delete ${u.username} and their ${u.app_count ?? 0} app(s)? This cannot be undone.`)) {
                              await api.deleteUser(u.id);
                            }
                          })}>
                          Delete
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function Settings() {
  const me = useMe();
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-navy-950/80 backdrop-blur-xl">
        <Container className="flex h-16 items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Brand />
            <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[11px] text-muted">Settings</span>
          </div>
          <div className="flex items-center gap-5 text-[13px]">
            <a href="#/console" className="text-muted hover:text-ink">← Console</a>
            <button type="button" onClick={signOut} className="text-muted hover:text-ink">Sign out</button>
          </div>
        </Container>
      </header>
      <Container className="space-y-6 py-10 sm:py-14">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-teal">Account</p>
          <h1 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em]">
            {me.username}
            <span className="ml-3 rounded-full border border-line px-2.5 py-0.5 align-middle font-mono text-xs text-muted">{me.role}</span>
          </h1>
        </div>
        <PasswordCard />
        <TokensCard />
        {me.role === "admin" && <UsersCard selfId={me.id} />}
      </Container>
    </div>
  );
}
