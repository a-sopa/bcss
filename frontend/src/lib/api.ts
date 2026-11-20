/** Typed client for the OwnCloud control plane (proxied at /api). */

export type AppStatus =
  | "queued"
  | "scanning"
  | "building"
  | "starting"
  | "running"
  | "restarting"
  | "stopped"
  | "crashed"
  | "missing"
  | "blocked"
  | "failed";

export type Tier = "critical" | "medium" | "resilient" | "unknown";

export type ScanFinding = {
  algorithm: string;
  tier: Tier;
  quantum_status: string;
  usage: string;
  file: string | null;
  locator: string | null;
  rationale: string | null;
  recommendation: string | null;
};

export type ScanSummary = {
  status: "completed" | "partial" | "failed" | "skipped" | "unavailable";
  reason?: string;
  score?: number | null;
  files_scanned?: number;
  findings?: number;
  tiers?: Record<Tier, number>;
  quantum_vulnerable?: number;
  top?: ScanFinding[];
};

export type Effort = "none" | "config" | "code";

export type AwsService = {
  id: string;
  aws: string;
  replacement: string;
  effort: Effort;
  how: string;
  files: string[];
};

export type MigrationReport<Env = Record<string, string>> = {
  platform: string;
  runtime: string | null;
  runtime_label: string | null;
  compatibility: "ready" | "config" | "changes" | "unsupported";
  error: string | null;
  functions: string[];
  services: AwsService[];
  env: Env;
  env_sources: string[];
  access_keys: { file: string; line: number; key: string }[];
  notes: string[];
};

export type CloudApp = {
  id: string;
  name: string;
  runtime: string | null;
  status: AppStatus;
  detail: string | null;
  enforce_gate: boolean;
  url: string | null;
  scan_summary: ScanSummary | null;
  /** Stored report; env holds variable names only. */
  migration: MigrationReport<string[]> | null;
  env_keys: string[];
  created_at: number;
  updated_at: number;
};

export type CloudEvent = {
  id: number;
  ts: number;
  app_id: string | null;
  module: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  title: string;
  detail: string | null;
};

export type Health = { status: string; docker: boolean; quantumtrace: boolean };

export type Severity = "low" | "medium" | "high" | "critical";
export const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

export type CodeFix = { line: number; column: number; end_line: number; end_column: number; text: string };

export type CodeFinding = {
  id: string;
  file: string;
  line: number;
  column: number;
  end_line: number;
  end_column: number;
  severity: Severity;
  rule: string;
  title: string;
  message: string;
  suggestion: string;
  cwe: string | null;
  source: "security" | "quantum";
  fix: CodeFix | null;
};

export type SourceFile = { path: string; size: number; language: string };

export type ProjectAnalysis = {
  findings: CodeFinding[];
  files: Record<string, Severity | null>;
  counts: Record<Severity, number>;
  quantum: "ok" | "unavailable" | "skipped";
};

/** Thrown for 401 responses; the console then shows the sign-in screen. */
export class AuthError extends Error {}
export const UNAUTHORIZED_EVENT = "owncloud:unauthorized";

export type Stats = { cpu_percent: number; memory_bytes: number; memory_limit_bytes: number } | null;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    credentials: "same-origin",
    // Custom header required by the API for every state-changing request (CSRF protection).
    headers: { "X-OwnCloud-CSRF": "1", ...(init?.headers ?? {}) },
  });
  if (response.status === 401 && path !== "/auth/login") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new AuthError("Authentication required");
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* keep the HTTP status message */
    }
    throw new Error(message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

function appendFiles(form: FormData, files: File[]) {
  for (const file of files) form.append("files", file, file.webkitRelativePath || file.name);
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const file = (id: string, path: string) => `/apps/${id}/file?path=${encodeURIComponent(path)}`;

export const api = {
  login: (password: string) => request<{ authenticated: boolean }>("/auth/login", json("POST", { password })),
  logout: () => request<{ authenticated: boolean }>("/auth/logout", { method: "POST" }),
  me: () => request<{ authenticated: boolean }>("/auth/me"),
  health: () => request<Health>("/system"),
  app: (id: string) => request<CloudApp>(`/apps/${id}`),
  files: (id: string) => request<{ files: SourceFile[] }>(`/apps/${id}/files`),
  readFile: (id: string, path: string) => request<{ path: string; content: string; language: string }>(file(id, path)),
  saveFile: (id: string, path: string, content: string) => request<{ path: string }>(file(id, path), json("PUT", { content })),
  analysis: (id: string) => request<ProjectAnalysis>(`/apps/${id}/analysis`),
  analyzeBuffer: (id: string, path: string, content: string) =>
    request<{ findings: CodeFinding[]; quantum: string }>(`/apps/${id}/analysis/file`, json("POST", { path, content })),
  apps: () => request<CloudApp[]>("/apps"),
  events: (appId?: string) => request<CloudEvent[]>(`/events?limit=50${appId ? `&app_id=${appId}` : ""}`),
  logs: (id: string) => request<{ logs: string }>(`/apps/${id}/logs?tail=300`),
  stats: (id: string) => request<Stats>(`/apps/${id}/stats`),
  stop: (id: string) => request<CloudApp>(`/apps/${id}/stop`, { method: "POST" }),
  start: (id: string) => request<CloudApp>(`/apps/${id}/start`, { method: "POST" }),
  redeploy: (id: string) => request<CloudApp>(`/apps/${id}/redeploy`, { method: "POST" }),
  remove: (id: string) => request<void>(`/apps/${id}`, { method: "DELETE" }),
  deploy: (name: string, enforceGate: boolean, files: File[], env: Record<string, string>) => {
    const form = new FormData();
    form.append("name", name);
    form.append("enforce_gate", String(enforceGate));
    form.append("env", JSON.stringify(env));
    appendFiles(form, files);
    return request<CloudApp>("/apps", { method: "POST", body: form });
  },
  analyze: (files: File[]) => {
    const form = new FormData();
    appendFiles(form, files);
    return request<MigrationReport>("/migrations/analyze", { method: "POST", body: form });
  },
};
