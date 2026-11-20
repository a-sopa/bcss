import { useEffect, useState } from "react";
import { api, type CloudApp } from "../lib/api";
import { usePolling } from "../hooks/usePolling";
import { Brand, Container, cx } from "../components/ui";
import { AppDetail } from "./AppDetail";
import { DeployPanel } from "./DeployPanel";
import { signOut, useMe } from "./AuthGate";
import { editorHref } from "../hooks/useHashRoute";
import { QuantumBadge, SeverityDot, StatusPill, timeAgo } from "./badges";

function HealthDot({ label, ok }: { label: string; ok: boolean | undefined }) {
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-[11px] text-muted">
      <span className={cx("size-1.5 rounded-full", ok === undefined ? "bg-muted/50" : ok ? "bg-teal" : "bg-danger")} />
      {label}
    </span>
  );
}

function ActionButton({ label, onClick, danger }: { label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={cx(
        "h-7 rounded-full border border-line px-3 text-xs transition-colors duration-300",
        danger ? "text-muted hover:border-danger/40 hover:text-danger" : "text-ink/85 hover:border-teal/40",
      )}
    >
      {label}
    </button>
  );
}

function AppRow({ app, open, onToggle, refresh, showOwner }: { app: CloudApp; open: boolean; onToggle: () => void; refresh: () => void; showOwner: boolean }) {
  const [error, setError] = useState<string | null>(null);
  const act = (action: () => Promise<unknown>) => async () => {
    try {
      setError(null);
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      refresh();
    }
  };

  return (
    <li className={cx("rounded-2xl border bg-navy-900/40 transition-colors duration-300", open ? "border-teal/25" : "border-line")}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={onToggle}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onToggle())}
        className="flex cursor-pointer flex-wrap items-center gap-x-5 gap-y-3 px-5 py-4 sm:px-6"
      >
        <div className="min-w-0 flex-1 basis-40">
          <p className="truncate font-display font-semibold">{app.name}</p>
          <p className="font-mono text-[11px] text-muted">
            {showOwner && app.owner && <span className="text-teal">{app.owner} · </span>}
            {app.runtime ?? "detecting"} · {timeAgo(app.created_at)}
            {app.migration?.platform.startsWith("AWS") && <span className="text-azure"> · from {app.migration.platform.replace(/ \(.*\)$/, "")}</span>}
          </p>
        </div>
        <StatusPill status={app.status} />
        <QuantumBadge summary={app.scan_summary} />
        <div className="flex flex-wrap items-center gap-2">
          {app.url && (
            <a
              href={app.url}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => e.stopPropagation()}
              className="h-7 rounded-full bg-teal/15 px-3 text-xs leading-7 text-teal transition-colors hover:bg-teal/25"
            >
              Open ↗
            </a>
          )}
          <a
            href={editorHref(app.id)}
            onClick={(e) => e.stopPropagation()}
            className="h-7 rounded-full border border-azure/30 px-3 text-xs leading-7 text-azure transition-colors hover:border-azure/60"
          >
            Code
          </a>
          {app.status === "running" && <ActionButton label="Stop" onClick={act(() => api.stop(app.id))} />}
          {(app.status === "stopped" || app.status === "crashed") && (
            <ActionButton label="Start" onClick={act(() => api.start(app.id))} />
          )}
          <ActionButton label="Redeploy" onClick={act(() => api.redeploy(app.id))} />
          <ActionButton
            label="Delete"
            danger
            onClick={act(async () => {
              if (window.confirm(`Delete ${app.name}? Its container, image and files will be removed.`)) {
                await api.remove(app.id);
              }
            })}
          />
        </div>
      </div>
      {error && <p className="px-6 pb-3 text-xs text-danger">{error}</p>}
      {open && <AppDetail app={app} />}
    </li>
  );
}

export function Console() {
  const me = useMe();
  const apps = usePolling(api.apps, 2000);
  const health = usePolling(api.health, 5000);
  const events = usePolling(() => api.events(), 3000);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  const names = new Map((apps.data ?? []).map((a) => [a.id, a.name]));
  const running = (apps.data ?? []).filter((a) => a.status === "running").length;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-navy-950/80 backdrop-blur-xl">
        <Container className="flex h-16 items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Brand />
            <span className="rounded-full border border-line px-2.5 py-0.5 font-mono text-[11px] text-muted">Console</span>
          </div>
          <div className="flex items-center gap-5">
            <div className="hidden items-center gap-4 sm:flex">
              <HealthDot label="Docker" ok={health.data?.docker} />
            </div>
            <a href="#/console/settings" className="flex items-center gap-2 text-[13px] text-muted transition-colors hover:text-ink">
              <span className="grid size-6 place-items-center rounded-full bg-azure/20 font-mono text-[11px] uppercase text-azure" aria-hidden="true">
                {me.username[0]}
              </span>
              {me.username}
              {me.role === "admin" && <span className="font-mono text-[10px] text-teal">admin</span>}
            </a>
            <button type="button" onClick={signOut} className="text-[13px] text-muted transition-colors hover:text-ink">
              Sign out
            </button>
          </div>
        </Container>
      </header>

      <Container className="py-10 sm:py-14">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-teal">Developed in Europe</p>
            <h1 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Your cloud</h1>
          </div>
          <p className="font-mono text-xs text-muted">
            {apps.data?.length ?? 0} app(s) · {running} running
          </p>
        </div>

        {(apps.error || health.data?.docker === false) && (
          <p className="mt-6 rounded-xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {apps.error ? `Cannot reach the control plane: ${apps.error}` : "The control plane cannot reach Docker."}
          </p>
        )}

        <div className="mt-10 grid items-start gap-8 lg:grid-cols-[380px_1fr]">
          <div className="space-y-8 lg:sticky lg:top-24">
            <DeployPanel onDeployed={apps.refresh} />

            <section aria-labelledby="activity-title">
              <h2 id="activity-title" className="font-mono text-[11px] uppercase tracking-[0.2em] text-muted">
                Activity
              </h2>
              <ul className="mt-4 max-h-[22rem] space-y-3 overflow-auto pr-1">
                {(events.data ?? []).slice(0, 25).map((e) => (
                  <li key={e.id} className="flex gap-3 text-[13px]">
                    <SeverityDot severity={e.severity} />
                    <div className="min-w-0">
                      <p className="truncate">{e.title}</p>
                      <p className="font-mono text-[11px] text-muted">
                        {(e.app_id && names.get(e.app_id)) || e.module} · {timeAgo(e.ts)}
                      </p>
                    </div>
                  </li>
                ))}
                {events.data?.length === 0 && <li className="text-sm text-muted">Nothing yet.</li>}
              </ul>
            </section>
          </div>

          <section aria-labelledby="apps-title">
            <h2 id="apps-title" className="sr-only">
              Applications
            </h2>
            {apps.data?.length === 0 ? (
              <div className="grid place-items-center rounded-2xl border border-dashed border-line px-6 py-20 text-center">
                <p className="font-display text-lg font-semibold">No applications yet</p>
                <p className="mt-2 max-w-sm text-sm text-muted">
                  Deploy your first app. Its code is analysed by QuantumTrace before it runs.
                </p>
              </div>
            ) : (
              <ul className="space-y-3">
                {(apps.data ?? []).map((app) => (
                  <AppRow
                    key={app.id}
                    app={app}
                    open={openId === app.id}
                    onToggle={() => setOpenId((id) => (id === app.id ? null : app.id))}
                    refresh={apps.refresh}
                    showOwner={me.role === "admin"}
                  />
                ))}
              </ul>
            )}
          </section>
        </div>
      </Container>
    </div>
  );
}
