import { useEffect, useRef, useState, type DragEvent } from "react";
import { api, type MigrationReport as Report } from "../lib/api";
import { cx } from "../components/ui";
import { MigrationReport } from "./MigrationReport";

type Mode = "new" | "migrate";

const IGNORED = /(^|\/)(node_modules|\.git|__pycache__|\.venv|venv|\.aws-sam|\.serverless)(\/|$)/;
const ENV_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/\.[a-z0-9]+$/, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

function suggestName(files: File[]) {
  const first = files[0];
  if (!first) return "";
  const folder = first.webkitRelativePath.split("/")[0];
  return slugify(folder || first.name);
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const toEnvText = (env: Record<string, string>) =>
  Object.entries(env)
    .map(([k, v]) => `${k}=${v}`)
    .join("\n");

function parseEnv(text: string): { env: Record<string, string>; error: string | null } {
  const env: Record<string, string> = {};
  for (const [i, raw] of text.split("\n").entries()) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    const key = eq === -1 ? line : line.slice(0, eq).trim();
    if (eq === -1 || !ENV_KEY.test(key)) return { env, error: `Line ${i + 1}: use KEY=value` };
    env[key] = line.slice(eq + 1);
  }
  return { env, error: null };
}

export function DeployPanel({ onDeployed }: { onDeployed: () => void }) {
  const [mode, setMode] = useState<Mode>(() => (window.location.hash.includes("migrate") ? "migrate" : "new"));
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState("");
  const [enforce, setEnforce] = useState(true);
  const [envText, setEnvText] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const filesInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  const choose = async (list: FileList | null) => {
    const picked = Array.from(list ?? []).filter((f) => !IGNORED.test(f.webkitRelativePath || f.name));
    setFiles(picked);
    setError(null);
    setReport(null);
    setEnvText("");
    if (!picked.length) return;
    setName(suggestName(picked));
    setAnalyzing(true);
    try {
      const result = await api.analyze(picked);
      setReport(result);
      setEnvText(toEnvText(result.env));
      if (result.platform.startsWith("AWS")) setMode("migrate");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAnalyzing(false);
    }
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files);
  };

  const parsedEnv = parseEnv(envText);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.deploy(name, enforce, files, parsedEnv.env);
      setFiles([]);
      setName("");
      setEnvText("");
      setReport(null);
      if (folderInput.current) folderInput.current.value = "";
      if (filesInput.current) filesInput.current.value = "";
      onDeployed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  };

  const total = files.reduce((sum, f) => sum + f.size, 0);
  const canDeploy =
    files.length > 0 &&
    /^[a-z0-9][a-z0-9-]{0,39}$/.test(name) &&
    !parsedEnv.error &&
    !submitting &&
    !analyzing &&
    report?.compatibility !== "unsupported";
  const migrate = mode === "migrate";

  return (
    <section aria-labelledby="deploy-title" className="rounded-2xl border border-line bg-navy-900/50 p-6">
      <div role="tablist" aria-label="Deployment type" className="mb-5 grid grid-cols-2 gap-1 rounded-full border border-line p-1">
        {(
          [
            ["new", "New app"],
            ["migrate", "Migrate from AWS"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={mode === id}
            onClick={() => setMode(id)}
            className={cx(
              "rounded-full py-1.5 text-xs transition-colors duration-300",
              mode === id ? "bg-white/[0.08] text-ink" : "text-muted hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <h2 id="deploy-title" className="font-display text-lg font-semibold tracking-[-0.01em]">
        {migrate ? "Bring your app from AWS" : "Deploy an application"}
      </h2>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">
        {migrate
          ? "Upload a Lambda function (SAM, Serverless Framework or a plain handler) or an Elastic Beanstalk bundle. It runs as it is, with its configuration imported."
          : "Upload a folder or a .zip. Python, Node, static sites and Dockerfiles are detected automatically."}
      </p>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          "mt-5 rounded-xl border border-dashed p-5 text-center transition-colors duration-300",
          dragging ? "border-teal/60 bg-teal/5" : "border-line",
        )}
      >
        {files.length ? (
          <div className="text-left">
            <p className="font-mono text-xs text-teal">
              {files.length} file{files.length === 1 ? "" : "s"} · {formatBytes(total)}
            </p>
            <ul className="mt-2 max-h-24 space-y-0.5 overflow-auto font-mono text-[11px] text-muted">
              {files.slice(0, 12).map((f) => (
                <li key={f.webkitRelativePath || f.name} className="truncate">
                  {f.webkitRelativePath || f.name}
                </li>
              ))}
              {files.length > 12 && <li>… and {files.length - 12} more</li>}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-muted">{migrate ? "Drop your exported project or .zip here" : "Drop files or a .zip here"}</p>
        )}
        <div className="mt-4 flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => folderInput.current?.click()}
            className="h-8 rounded-full border border-line px-3.5 text-xs text-ink transition-colors hover:border-teal/40"
          >
            Choose folder
          </button>
          <button
            type="button"
            onClick={() => filesInput.current?.click()}
            className="h-8 rounded-full border border-line px-3.5 text-xs text-ink transition-colors hover:border-teal/40"
          >
            Choose files or .zip
          </button>
        </div>
        <input ref={folderInput} type="file" multiple hidden onChange={(e) => choose(e.target.files)} />
        <input ref={filesInput} type="file" multiple hidden onChange={(e) => choose(e.target.files)} />
      </div>

      {analyzing && <p className="mt-4 font-mono text-[11px] text-azure">Analysing…</p>}
      {report && !migrate && (
        <p className="mt-4 font-mono text-[11px] text-muted">
          Detected: <span className="text-ink/85">{report.runtime_label ?? report.error}</span>
        </p>
      )}
      {report && migrate && (
        <div className="mt-5 rounded-xl border border-line bg-navy-950/50 p-4">
          <MigrationReport report={report} compact />
        </div>
      )}

      <label className="mt-5 block">
        <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">App name</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value.toLowerCase())}
          placeholder="my-app"
          spellCheck={false}
          className="mt-2 h-10 w-full rounded-lg border border-line bg-navy-950/70 px-3 font-mono text-sm text-ink outline-none transition-colors placeholder:text-muted/50 focus:border-teal/50"
        />
      </label>

      <label className="mt-5 block">
        <span className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-muted">Environment variables</span>
          {report && report.env_sources.length > 0 && (
            <span className="truncate font-mono text-[10px] text-teal">from {report.env_sources.join(", ")}</span>
          )}
        </span>
        <textarea
          value={envText}
          onChange={(e) => setEnvText(e.target.value)}
          placeholder="KEY=value"
          rows={Math.min(6, Math.max(2, envText.split("\n").length))}
          spellCheck={false}
          className="mt-2 w-full resize-y rounded-lg border border-line bg-navy-950/70 px-3 py-2 font-mono text-xs leading-relaxed text-ink outline-none transition-colors placeholder:text-muted/50 focus:border-teal/50"
        />
        {parsedEnv.error && <span className="mt-1 block text-xs text-danger">{parsedEnv.error}</span>}
      </label>

      <label className="mt-5 flex cursor-pointer items-start gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={enforce}
          onClick={() => setEnforce((v) => !v)}
          className={cx(
            "relative mt-0.5 h-5 w-9 shrink-0 rounded-full border transition-colors duration-300",
            enforce ? "border-teal/50 bg-teal/25" : "border-line bg-white/[0.04]",
          )}
        >
          <span
            className={cx(
              "absolute top-1/2 size-3.5 -translate-y-1/2 rounded-full transition-[left,background-color] duration-300",
              enforce ? "left-[18px] bg-teal" : "left-[2px] bg-muted",
            )}
          />
        </button>
        <span>
          <span className="block text-sm font-medium">Quantum gate</span>
          <span className="mt-0.5 block text-xs leading-relaxed text-muted">
            Block the deployment if QuantumTrace finds quantum-vulnerable cryptography.
          </span>
        </span>
      </label>

      {error && <p className="mt-4 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</p>}

      <button
        type="button"
        disabled={!canDeploy}
        onClick={submit}
        className="mt-6 h-11 w-full rounded-full bg-teal text-sm font-medium text-navy-950 transition-[background-color,opacity] duration-300 hover:bg-teal-soft disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitting ? "Uploading…" : migrate ? "Migrate & deploy" : "Scan & deploy"}
      </button>
    </section>
  );
}
