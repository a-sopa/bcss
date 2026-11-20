// Integration tests executed inside VS Code by runVsCode.ts.
import { strict as assert } from "node:assert";
import * as fs from "node:fs";
import * as path from "node:path";
import * as vscode from "vscode";
import type { OwnCloudExtensionApi } from "../extension";

async function waitFor<T>(what: string, probe: () => T | undefined | false, timeoutMs = 30_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = probe();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`Timed out waiting for ${what}`);
    await new Promise((r) => setTimeout(r, 250));
  }
}

const results: string[] = [];
async function check(name: string, body: () => Promise<void>): Promise<void> {
  try {
    await body();
    results.push(`✓ ${name}`);
  } catch (error) {
    results.push(`✗ ${name}: ${(error as Error).message}`);
    throw error;
  } finally {
    if (process.env.OWNCLOUD_TEST_RESULTS) fs.writeFileSync(process.env.OWNCLOUD_TEST_RESULTS, results.join("\n") + "\n");
  }
}

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension<OwnCloudExtensionApi>("owncloud-hackathon.owncloud-security");
  assert.ok(extension, "extension is installed");
  const api = await extension.activate();
  const folder = vscode.workspace.workspaceFolders![0].uri;
  const fileUri = vscode.Uri.file(path.join(folder.fsPath, "vulnerable.py"));

  await check("signs in with an access token", async () => {
    const me = await api.signInWithToken(process.env.OWNCLOUD_URL!, process.env.OWNCLOUD_TEST_TOKEN!);
    assert.equal(me.via, "token");
  });

  const document = await vscode.workspace.openTextDocument(fileUri);
  const editor = await vscode.window.showTextDocument(document);

  await check("reports findings in the Problems panel with severities", async () => {
    const diagnostics = await waitFor("diagnostics", () => {
      const list = vscode.languages.getDiagnostics(fileUri).filter((d) => d.source?.startsWith("OwnCloud"));
      return list.length >= 5 && list;
    });
    const findings = api.findings(fileUri);
    const severities = new Set(findings.map((f) => f.severity));
    for (const level of ["critical", "high", "medium", "low"]) assert.ok(severities.has(level as never), `has ${level}: ${[...severities]}`);
    const key = diagnostics.find((d) => d.message.startsWith("Hard-coded AWS access key"));
    assert.ok(key, "AWS key reported");
    assert.equal(key.severity, vscode.DiagnosticSeverity.Error);
    assert.equal(key.range.start.line, 6);
  });

  await check("explains a finding on hover", async () => {
    const line = document.getText().split("\n").findIndex((l) => l.includes("yaml.load("));
    const column = document.lineAt(line).text.indexOf("yaml.load") + 2;
    const hovers = await vscode.commands.executeCommand<vscode.Hover[]>("vscode.executeHoverProvider", fileUri, new vscode.Position(line, column));
    const text = hovers.flatMap((h) => h.contents.map((c) => (typeof c === "string" ? c : "value" in c ? c.value : ""))).join("\n");
    assert.match(text, /Unsafe YAML loading/);
    assert.match(text, /Suggestion/);
  });

  await check("applies a quick fix", async () => {
    const line = document.getText().split("\n").findIndex((l) => l.includes("yaml.load("));
    const range = new vscode.Range(line, 0, line, document.lineAt(line).text.length);
    const actions = await vscode.commands.executeCommand<vscode.CodeAction[]>("vscode.executeCodeActionProvider", fileUri, range);
    const fix = actions.find((a) => a.title.startsWith("OwnCloud:") && a.title.includes("yaml.safe_load"));
    assert.ok(fix?.edit, `quick fix offered: ${actions.map((a) => a.title).join(" | ")}`);
    assert.ok(await vscode.workspace.applyEdit(fix.edit));
    assert.match(editor.document.lineAt(line).text, /yaml\.safe_load\(text\)/);
  });

  await check("re-analyses after the edit (finding disappears)", async () => {
    await waitFor("re-analysis", () => !api.findings(fileUri).some((f) => f.title === "Unsafe YAML loading"));
  });

  await check("downloads a large app in one go and links the folder", async () => {
    const appId = process.env.OWNCLOUD_TEST_APP;
    assert.ok(appId, "OWNCLOUD_TEST_APP is set");
    const target = vscode.Uri.file(path.join(path.dirname(folder.fsPath), "download", "big-app"));
    const result = await vscode.commands.executeCommand<vscode.Uri | undefined>(
      "owncloud.pullApp", { app: { id: appId, name: "big-app" } }, target,
    );
    assert.ok(result, "download finished");
    const expected = Number(process.env.OWNCLOUD_TEST_APP_FILES);
    let count = 0;
    const walk = async (dir: vscode.Uri): Promise<void> => {
      for (const [name, type] of await vscode.workspace.fs.readDirectory(dir)) {
        if (name === ".owncloud") continue;
        if (type === vscode.FileType.Directory) await walk(vscode.Uri.joinPath(dir, name));
        else count++;
      }
    };
    await walk(target);
    assert.equal(count, expected, "every file was downloaded");
    const link = JSON.parse(new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(target, ".owncloud", "app.json"))));
    assert.equal(link.appId, appId);
    await waitFor("folder shown in the Explorer", () =>
      vscode.workspace.workspaceFolders?.some((f) => f.uri.fsPath === target.fsPath), 10_000);
  });

  await check("signs out and clears findings", async () => {
    await vscode.commands.executeCommand("owncloud.signOut");
    assert.equal(api.findings(fileUri).length, 0);
    assert.equal(vscode.languages.getDiagnostics(fileUri).filter((d) => d.source?.startsWith("OwnCloud")).length, 0);
  });

  results.push(`${results.length} VS Code integration checks passed`);
  if (process.env.OWNCLOUD_TEST_RESULTS) fs.writeFileSync(process.env.OWNCLOUD_TEST_RESULTS, results.join("\n") + "\n");
}
