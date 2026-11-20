// OwnCloud API client. No VS Code imports, so it can be tested with plain Node.

export type Severity = "low" | "medium" | "high" | "critical";

export interface Fix {
  line: number;
  column: number;
  end_line: number;
  end_column: number;
  text: string;
}

export interface Finding {
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
  fix: Fix | null;
}

export interface Analysis {
  findings: Finding[];
  quantum: string;
}

export interface CloudApp {
  id: string;
  name: string;
  status: string;
  runtime: string | null;
  url: string | null;
  owner: string | null;
}

export interface Me {
  id: string;
  username: string;
  role: string;
  via: string;
  scope: "read" | "write" | null;
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const APP_ID = /^[0-9a-f]{10}$/;

/** The server origin to use, and whether the connection is unencrypted to another machine. */
export function normalizeServerUrl(input: string): { origin: string; insecureRemote: boolean } {
  let url: URL;
  try {
    url = new URL(input.trim());
  } catch {
    throw new Error("Enter a full address, for example http://localhost:8088");
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("Use an http:// or https:// address");
  if (url.username || url.password) throw new Error("Do not put credentials in the address");
  return { origin: url.origin, insecureRemote: url.protocol === "http:" && !LOCAL_HOSTS.has(url.hostname) };
}

export class OwnCloudClient {
  readonly origin: string;

  constructor(server: string, private readonly token: string, private readonly timeoutMs = 30_000) {
    this.origin = normalizeServerUrl(server).origin;
  }

  private async request<T>(method: string, path: string, body?: unknown, attempt = 0): Promise<T> {
    let response: Response;
    try {
      response = await fetch(new URL(path, this.origin), {
        method,
        // Never follow redirects: the token must only ever go to the configured server.
        redirect: "error",
        headers: {
          Authorization: `Bearer ${this.token}`,
          Accept: "application/json",
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (error) {
      throw new ApiError(`Cannot reach OwnCloud at ${this.origin}`, 0);
    }
    if (response.status === 429 && attempt < 4) {
      // Rate-limited by the server: wait as asked (bounded) and try again.
      const wait = Math.min(10, Number(response.headers.get("retry-after")) || 1 + attempt) * 1000;
      await new Promise((resolve) => setTimeout(resolve, wait));
      return this.request<T>(method, path, body, attempt + 1);
    }
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const detail = (await response.json()) as { detail?: unknown };
        if (typeof detail.detail === "string") message = detail.detail;
      } catch {
        /* keep the status text */
      }
      throw new ApiError(message, response.status);
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  private static app(id: string): string {
    if (!APP_ID.test(id)) throw new Error("Invalid app id");
    return `/api/apps/${id}`;
  }

  me(): Promise<Me> {
    return this.request("GET", "/api/auth/me");
  }

  apps(): Promise<CloudApp[]> {
    return this.request("GET", "/api/apps");
  }

  files(appId: string): Promise<{ files: { path: string; size: number }[] }> {
    return this.request("GET", `${OwnCloudClient.app(appId)}/files`);
  }

  /** Every text file of an app in one request. */
  archive(appId: string): Promise<{ files: { path: string; content: string }[]; skipped: string[] }> {
    return this.request("GET", `${OwnCloudClient.app(appId)}/archive`);
  }

  readFile(appId: string, path: string): Promise<{ path: string; content: string }> {
    return this.request("GET", `${OwnCloudClient.app(appId)}/file?path=${encodeURIComponent(path)}`);
  }

  saveFile(appId: string, path: string, content: string): Promise<{ path: string }> {
    return this.request("PUT", `${OwnCloudClient.app(appId)}/file?path=${encodeURIComponent(path)}`, { content });
  }

  redeploy(appId: string): Promise<CloudApp> {
    return this.request("POST", `${OwnCloudClient.app(appId)}/redeploy`);
  }

  /** Security and QuantumTrace findings for one file's content. */
  analyze(path: string, content: string): Promise<Analysis> {
    return this.request("POST", "/api/analysis/file", { path, content });
  }
}
