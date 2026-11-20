// Plain Node tests (node --test): helpers, and the API client against a running OwnCloud
// when OWNCLOUD_URL and OWNCLOUD_TEST_TOKEN are set.
import { strict as assert } from "node:assert";
import { test } from "node:test";
import { ApiError, normalizeServerUrl, OwnCloudClient } from "../api";
import { analysisPath, cweUrl, escapeMarkdown, isSafeRelativePath, severityByLine, worst } from "../findings";

test("server addresses are normalised and checked", () => {
  assert.equal(normalizeServerUrl("http://localhost:8088/console/#x").origin, "http://localhost:8088");
  assert.equal(normalizeServerUrl("http://localhost:8088").insecureRemote, false);
  assert.equal(normalizeServerUrl("http://cloud.example.eu").insecureRemote, true);
  assert.equal(normalizeServerUrl("https://cloud.example.eu").insecureRemote, false);
  assert.throws(() => normalizeServerUrl("file:///etc/passwd"));
  assert.throws(() => normalizeServerUrl("javascript:alert(1)"));
  assert.throws(() => normalizeServerUrl("https://user:pass@cloud.example.eu"));
  assert.throws(() => normalizeServerUrl("not a url"));
});

test("paths from the server cannot escape the download folder", () => {
  for (const ok of ["app.py", "src/handlers/orders.py", ".env", "static/app.js"]) assert.ok(isSafeRelativePath(ok), ok);
  for (const bad of ["../x", "a/../../x", "/etc/passwd", "C:/win.ini", "a\\..\\b", "a//b", "./a", "a\u0000b", "", "x".repeat(301)]) {
    assert.ok(!isSafeRelativePath(bad), JSON.stringify(bad));
  }
  assert.equal(analysisPath("../outside/file.py", "file.py"), "file.py");
  assert.equal(analysisPath("src\\app.py", "app.py"), "src/app.py");
});

test("markdown from analysed code is shown literally", () => {
  assert.equal(escapeMarkdown("[click](command:evil)"), "\\[click\\]\\(command:evil\\)");
  assert.equal(escapeMarkdown("<img src=x onerror=alert(1)>"), "\\<img src=x onerror=alert\\(1\\)\\>");
  assert.equal(cweUrl("CWE-89"), "https://cwe.mitre.org/data/definitions/89.html");
  assert.equal(cweUrl("CWE-89](javascript:x)"), null);
});

test("the worst severity wins on each line", () => {
  const base = { id: "", file: "a.py", column: 1, end_column: 2, rule: "", title: "", message: "", suggestion: "", cwe: null, source: "security" as const, fix: null };
  const findings = [
    { ...base, line: 1, end_line: 1, severity: "low" as const },
    { ...base, line: 1, end_line: 2, severity: "critical" as const },
    { ...base, line: 3, end_line: 3, severity: "medium" as const },
  ];
  const lines = severityByLine(findings, 10);
  assert.equal(lines.get(1), "critical");
  assert.equal(lines.get(2), "critical");
  assert.equal(lines.get(3), "medium");
  assert.equal(worst(findings), "critical");
});

const url = process.env.OWNCLOUD_URL;
const token = process.env.OWNCLOUD_TEST_TOKEN;

test("the client talks to a real OwnCloud", { skip: !url || !token }, async () => {
  const client = new OwnCloudClient(url!, token!);
  const me = await client.me();
  assert.equal(me.via, "token");
  const result = await client.analyze("demo.py", "import yaml\nyaml.load(data)\neval(input())\n");
  const severities = result.findings.map((f) => f.severity);
  assert.ok(severities.includes("critical") && severities.includes("high"), JSON.stringify(severities));
  assert.ok(result.findings.some((f) => f.fix?.text === "yaml.safe_load"));
  assert.ok(Array.isArray(await client.apps()));
});

test("bad and revoked tokens are rejected", { skip: !url }, async () => {
  const client = new OwnCloudClient(url!, "oc_not-a-real-token-but-long-enough-123");
  await assert.rejects(client.me(), (e: unknown) => e instanceof ApiError && e.status === 401);
});

test("redirects are never followed with the token", { skip: !url }, async () => {
  // 127.0.0.1:8088 redirects to localhost: the client must refuse instead of re-sending the token.
  const client = new OwnCloudClient("http://127.0.0.1:8088", token ?? "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");
  await assert.rejects(client.me(), (e: unknown) => e instanceof ApiError && e.status === 0);
});
