/** Typed client for the OwnCloud control plane (proxied at /api). */

export type AppStatus =
  | "queued"
  | "scanning"
  | "building"
  | "testing"
  | "canary"
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
  owner: string | null;
  version: number | null;
  canary_version: number | null;
  database: { enabled: boolean } | null;
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

export type Me = { id: string; username: string; role: "admin" | "user"; via: string };

export type AccessToken = {
  id: string;
  name: string;
  scope: "read" | "write";
  created_at: number;
  expires_at: number;
  last_used_at: number | null;
};

export type Account = {
  id: string;
  username: string;
  role: "admin" | "user";
  disabled: boolean;
  created_at: number;
  app_count?: number;
};

export type PipelineResult = {
  mode: "full" | "impacted" | "none";
  reason: string;
  status: "passed" | "failed" | "skipped";
  tests: string[];
  all_tests: string[];
  why?: Record<string, string>;
  duration: number;
  passed?: number;
  failed?: number;
  skipped_files?: number;
  estimated_saving?: number;
  output: string;
  changed: { added: string[]; modified: string[]; removed: string[] };
};

export type CanaryWindow = { requests: number; errors: number; error_rate: number; p95: number | null };

export type Deployment = {
  id: number;
  version: number;
  created_at: number;
  finished_at: number | null;
  status: "running" | "deployed" | "promoted" | "rolled_back" | "tests_failed" | "failed" | "blocked" | "manual_rollback";
  detail: { port?: number; runtime?: string; error?: string; reason?: string; from?: number } | null;
  pipeline: PipelineResult | null;
  canary: { anomalous: boolean; reason: string | null; canary: CanaryWindow; stable: CanaryWindow; percent: number; seconds: number; enough_data: boolean } | null;
};

export type IncidentReport = {
  kind: string;
  version: number;
  summary: string;
  onset: number | null;
  exception: { type: string; message: string } | null;
  culprit: { file: string; line: number; function: string; changed_in_this_version: boolean } | null;
  hint: string;
  meaning: string;
  changes: { file: string; lines: number[]; diff: string }[];
  suggested_fix: { file: string; current: string; revert: string } | null;
  log_excerpt: string;
};

export type Incident = { id: number; created_at: number; kind: string; title: string; report: IncidentReport };

export type TrafficPoint = { t: number; rps: number; error_rate: number; p95: number | null; probes: number; probe_errors: number };

export type Traffic =
  | { available: false }
  | {
      available: true;
      time: number;
      bucket_seconds: number;
      versions: Record<string, { series: TrafficPoint[]; weight: number; role: string | null }>;
      cache: {
        bytes: number;
        served_from_edge: number;
        requests: number;
        regions: Record<string, { entries: number; hits?: number; misses?: number; prefetched?: number; prefetch_hits?: number; hit_rate: number | null; visitors: number }>;
      };
      top_paths: { path: string; count: number }[];
      predictions: { region: string; from: string; to: string; count: number }[];
    };

export type DbAction = {
  id: number;
  created_at: number;
  kind: "index_created" | "index_rejected" | "index_dropped" | "index_failed" | "suggestion";
  statement: string;
  detail: Record<string, any>;
};

export type DatabaseStatus = {
  enabled: boolean;
  running?: boolean;
  slow_queries?: { id: string; query: string; calls: number; mean_ms: number; total_ms: number; rows: number }[];
  actions?: DbAction[];
  tables?: { name: string; rows: number }[];
  indexes?: { name: string; table: string; scans: number }[];
};

export type LoadStage = { users: number; seconds: number; requests: number; rps: number; error_rate: number; p50_ms: number | null; p95_ms: number | null; p99_ms: number | null };

export type LoadTest = {
  id: number;
  created_at: number;
  status: "running" | "finished" | "failed";
  plan: { stages: { users: number; seconds: number }[]; learned_from: number } | null;
  result: { stages?: LoadStage[]; verdict?: string; capacity_rps?: number; error?: string } | null;
};

export type TrafficModel = {
  requests: number;
  sessions: number;
  think_time_s: number;
  peak_rps: number;
  paths: { path: string; count: number }[];
  transitions: Record<string, Record<string, number>>;
  regions?: Record<string, number>;
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
  if (response.status === 401 && !path.startsWith("/auth/login") && !path.startsWith("/auth/signup")) {
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
  authConfig: () => request<{ signup: boolean }>("/auth/config"),
  login: (username: string, password: string) => request<Account>("/auth/login", json("POST", { username, password })),
  signup: (username: string, password: string) => request<Account>("/auth/signup", json("POST", { username, password })),
  logout: () => request<{ authenticated: boolean }>("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    request<{ changed: boolean }>("/auth/password", json("POST", { current_password, new_password })),
  tokens: () => request<AccessToken[]>("/tokens"),
  createToken: (name: string, scope: "read" | "write", days: number) =>
    request<AccessToken & { token: string }>("/tokens", json("POST", { name, scope, days })),
  deleteToken: (id: string) => request<void>(`/tokens/${id}`, { method: "DELETE" }),
  deployments: (id: string) => request<Deployment[]>(`/apps/${id}/deployments`),
  rollback: (id: string) => request<CloudApp>(`/apps/${id}/rollback`, { method: "POST" }),
  traffic: (id: string) => request<Traffic>(`/apps/${id}/traffic`),
  incidents: (id: string) => request<Incident[]>(`/apps/${id}/incidents`),
  database: (id: string) => request<DatabaseStatus>(`/apps/${id}/database`),
  enableDatabase: (id: string) => request<{ enabled: boolean }>(`/apps/${id}/database`, { method: "POST" }),
  optimiseDatabase: (id: string) => request<{ actions: DbAction[] }>(`/apps/${id}/database/optimize`, { method: "POST" }),
  loadModel: (id: string) => request<TrafficModel>(`/apps/${id}/loadtest/model`),
  loadTests: (id: string) => request<LoadTest[]>(`/apps/${id}/loadtests`),
  startLoadTest: (id: string, max_users: number) => request<{ id: number }>(`/apps/${id}/loadtests`, json("POST", { max_users })),
  k6Url: (id: string, maxUsers: number) => `/api/apps/${id}/loadtest/k6?max_users=${maxUsers}`,
  users: () => request<Account[]>("/users"),
  createUser: (username: string, password: string, role: "admin" | "user") =>
    request<Account>("/users", json("POST", { username, password, role })),
  updateUser: (id: string, changes: { role?: "admin" | "user"; disabled?: boolean }) =>
    request<Account>(`/users/${id}`, json("PATCH", changes)),
  deleteUser: (id: string) => request<void>(`/users/${id}`, { method: "DELETE" }),
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
