// Helpers shared by the extension and its tests. No VS Code imports.
import type { Finding, Severity } from "./api";

export const SEVERITIES: Severity[] = ["low", "medium", "high", "critical"];

export const SEVERITY_LABEL: Record<Severity, string> = {
  low: "Low · minor weakness",
  medium: "Medium · weak",
  high: "High · vulnerable",
  critical: "Critical · severely vulnerable",
};

/** Files the OwnCloud analyzer understands (same list as the server). */
export const ANALYSED_EXTENSIONS = new Set([
  ".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".java", ".json", ".yaml", ".yml",
  ".env", ".ini", ".cfg", ".toml", ".config", ".conf", ".properties",
]);

/** Extension to use for unsaved (untitled) documents, by VS Code language id. */
export const EXTENSION_FOR_LANGUAGE: Record<string, string> = {
  python: ".py", javascript: ".js", javascriptreact: ".jsx", typescript: ".ts", typescriptreact: ".tsx",
  go: ".go", java: ".java", json: ".json", jsonc: ".json", yaml: ".yaml", ini: ".ini", properties: ".properties",
  dotenv: ".env",
};

export const MAX_ANALYSED_BYTES = 1024 * 1024;

export function rank(severity: Severity): number {
  return SEVERITIES.indexOf(severity);
}

export function worst(findings: Finding[]): Severity | null {
  let best = -1;
  for (const f of findings) best = Math.max(best, rank(f.severity));
  return best >= 0 ? SEVERITIES[best] : null;
}

/** Worst severity per 1-based line. */
export function severityByLine(findings: Finding[], lineCount: number): Map<number, Severity> {
  const lines = new Map<number, Severity>();
  for (const f of findings) {
    for (let line = Math.max(1, f.line); line <= Math.min(f.end_line, lineCount); line++) {
      const current = lines.get(line);
      if (!current || rank(f.severity) > rank(current)) lines.set(line, f.severity);
    }
  }
  return lines;
}

export function counts(findings: Finding[]): Record<Severity, number> {
  const result: Record<Severity, number> = { low: 0, medium: 0, high: 0, critical: 0 };
  for (const f of findings) result[f.severity]++;
  return result;
}

/** Escape Markdown so analysed code and messages are shown literally in hovers. */
export function escapeMarkdown(text: string): string {
  return text.replace(/[\\`*_{}[\]()#+\-.!|<>~]/g, "\\$&");
}

export function cweUrl(cwe: string | null): string | null {
  const match = cwe ? /^CWE-(\d{1,5})$/.exec(cwe) : null;
  return match ? `https://cwe.mitre.org/data/definitions/${match[1]}.html` : null;
}

/**
 * A path received from the server, safe to create under a local folder: relative, no "..", no
 * backslashes, drive letters or control characters.
 */
export function isSafeRelativePath(path: string): boolean {
  if (!path || path.length > 300 || /[\u0000-\u001f\u007f\\:]/.test(path)) return false;
  if (path.startsWith("/")) return false;
  const parts = path.split("/");
  return parts.length <= 32 && parts.every((part) => part !== "" && part !== "." && part !== "..");
}

/** The path sent to the analyzer: workspace-relative when possible, otherwise the file name. */
export function analysisPath(relative: string, fileName: string): string {
  const candidate = relative.replace(/\\/g, "/");
  return isSafeRelativePath(candidate) ? candidate : fileName.replace(/[\\/:]/g, "_") || "file";
}
