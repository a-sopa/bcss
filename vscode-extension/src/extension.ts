import * as path from "node:path";
import * as vscode from "vscode";
import { ApiError, normalizeServerUrl, OwnCloudClient, type Finding, type Me, type Severity } from "./api";
import { AppsProvider, registerAppCommands } from "./apps";
import {
  ANALYSED_EXTENSIONS, EXTENSION_FOR_LANGUAGE, MAX_ANALYSED_BYTES, SEVERITIES, SEVERITY_LABEL, analysisPath, counts,
  cweUrl, escapeMarkdown, rank, severityByLine,
} from "./findings";

const TOKEN_SECRET = "owncloud.accessToken";
const SOURCE = "OwnCloud";
const EXCLUDE = "{**/node_modules/**,**/.git/**,**/.owncloud/**,**/__pycache__/**,**/.venv/**,**/venv/**,**/dist/**,**/build/**,**/out/**}";

const COLOR: Record<Severity, string> = { low: "#F2C94C", medium: "#FF9F43", high: "#FF4D5E", critical: "#000000" };
const LINE_DARK: Record<Severity, string> = {
  low: "rgba(242,201,76,0.10)", medium: "rgba(255,159,67,0.14)", high: "rgba(255,77,94,0.17)", critical: "rgba(0,0,0,0.65)",
};
const LINE_LIGHT: Record<Severity, string> = {
  low: "rgba(242,201,76,0.24)", medium: "rgba(255,159,67,0.22)", high: "rgba(255,77,94,0.16)", critical: "rgba(0,0,0,0.14)",
};
const DIAGNOSTIC: Record<Severity, vscode.DiagnosticSeverity> = {
  low: vscode.DiagnosticSeverity.Information,
  medium: vscode.DiagnosticSeverity.Warning,
  high: vscode.DiagnosticSeverity.Error,
  critical: vscode.DiagnosticSeverity.Error,
};

/** Returned from activate(); used by the integration tests. */
export interface OwnCloudExtensionApi {
  signInWithToken(server: string, token: string): Promise<Me>;
  analyze(document: vscode.TextDocument): Promise<void>;
  findings(uri: vscode.Uri): Finding[];
}

export async function activate(context: vscode.ExtensionContext): Promise<OwnCloudExtensionApi> {
  const controller = new Controller(context);
  await controller.restore();
  return {
    signInWithToken: (server, token) => controller.signInWithToken(server, token),
    analyze: (document) => controller.analyze(document),
    findings: (uri) => controller.findingsFor(uri),
  };
}

export function deactivate(): void {}

export class Controller {
  client: OwnCloudClient | undefined;
  me: Me | undefined;
  private readonly diagnostics = vscode.languages.createDiagnosticCollection("owncloud");
  private readonly results = new Map<string, Finding[]>();
  private readonly timers = new Map<string, NodeJS.Timeout>();
  private readonly lineDecorations: Record<Severity, vscode.TextEditorDecorationType>;
  private readonly criticalSpan: vscode.TextEditorDecorationType;
  private readonly status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
  private readonly apps: AppsProvider;
  private lastNetworkWarning = 0;

  constructor(private readonly context: vscode.ExtensionContext) {
    this.lineDecorations = Object.fromEntries(
      SEVERITIES.map((severity) => [
        severity,
        vscode.window.createTextEditorDecorationType({
          isWholeLine: true,
          gutterIconPath: context.asAbsolutePath(`media/sev-${severity}.svg`),
          gutterIconSize: "70%",
          overviewRulerColor: severity === "critical" ? "#FFFFFF" : COLOR[severity],
          overviewRulerLane: vscode.OverviewRulerLane.Right,
          dark: { backgroundColor: LINE_DARK[severity] },
          light: { backgroundColor: LINE_LIGHT[severity] },
        }),
      ]),
    ) as Record<Severity, vscode.TextEditorDecorationType>;
    this.criticalSpan = vscode.window.createTextEditorDecorationType({
      dark: { backgroundColor: "#000000", color: "#FFFFFF", border: "1px solid rgba(255,255,255,0.55)", borderRadius: "2px" },
      light: { backgroundColor: "#000000", color: "#FFFFFF", borderRadius: "2px" },
    });

    this.apps = new AppsProvider(this);
    const subscriptions = context.subscriptions;
    subscriptions.push(
      this.diagnostics,
      this.status,
      this.criticalSpan,
      ...Object.values(this.lineDecorations),
      vscode.window.registerTreeDataProvider("owncloud.apps", this.apps),
      vscode.commands.registerCommand("owncloud.signIn", () => this.signIn()),
      vscode.commands.registerCommand("owncloud.signOut", () => this.signOut()),
      vscode.commands.registerCommand("owncloud.analyzeFile", () => this.analyzeActive()),
      vscode.commands.registerCommand("owncloud.analyzeWorkspace", () => this.analyzeWorkspace()),
      vscode.commands.registerCommand("owncloud.clearFindings", () => this.clear()),
      vscode.commands.registerCommand("owncloud.openConsole", () => this.openConsole()),
      vscode.commands.registerCommand("owncloud.refreshApps", () => this.apps.refresh()),
      vscode.languages.registerCodeActionsProvider({ scheme: "*" }, new FixProvider(this), {
        providedCodeActionKinds: [vscode.CodeActionKind.QuickFix],
      }),
      vscode.languages.registerHoverProvider({ scheme: "*" }, new FindingHover(this)),
      vscode.workspace.onDidOpenTextDocument((d) => this.schedule(d, 0)),
      vscode.workspace.onDidSaveTextDocument((d) => this.schedule(d, 0)),
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (e.contentChanges.length && this.setting("analyzeOnType", true)) {
          this.schedule(e.document, Math.max(200, this.setting("analyzeDelay", 800)));
        }
      }),
      vscode.workspace.onDidCloseTextDocument((d) => this.timers.delete(d.uri.toString())),
      vscode.window.onDidChangeVisibleTextEditors((editors) => editors.forEach((e) => this.decorate(e))),
      vscode.window.onDidChangeActiveTextEditor(() => this.updateStatus()),
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration("owncloud.serverUrl")) void this.restore();
        if (e.affectsConfiguration("owncloud.lineHighlights")) vscode.window.visibleTextEditors.forEach((ed) => this.decorate(ed));
      }),
      context.secrets.onDidChange((e) => {
        if (e.key === TOKEN_SECRET) void this.restore();
      }),
    );
    registerAppCommands(context, this, this.apps);
    this.status.command = "owncloud.signIn";
    this.status.show();
  }

  private setting<T>(key: string, fallback: T): T {
    return vscode.workspace.getConfiguration("owncloud").get<T>(key, fallback);
  }

  serverUrl(): string {
    return this.setting("serverUrl", "http://localhost:8088");
  }

  // ------------------------------------------------------------ account

  async restore(): Promise<void> {
    const token = await this.context.secrets.get(TOKEN_SECRET);
    if (!token) return this.setSignedIn(undefined, undefined);
    try {
      const client = new OwnCloudClient(this.serverUrl(), token);
      this.setSignedIn(client, await client.me());
      vscode.workspace.textDocuments.forEach((d) => this.schedule(d, 0));
    } catch (error) {
      this.setSignedIn(undefined, undefined);
      if (error instanceof ApiError && error.status === 401) {
        await this.context.secrets.delete(TOKEN_SECRET);
        void this.askToSignIn("Your OwnCloud access token has expired or was revoked.");
      }
    }
  }

  private setSignedIn(client: OwnCloudClient | undefined, me: Me | undefined): void {
    this.client = client;
    this.me = me;
    void vscode.commands.executeCommand("setContext", "owncloud.signedIn", Boolean(client));
    this.apps.refresh();
    this.updateStatus();
  }

  async signIn(): Promise<void> {
    const server = await vscode.window.showInputBox({
      title: "OwnCloud: Sign in (1/2)",
      prompt: "Address of your OwnCloud console",
      value: this.serverUrl(),
      ignoreFocusOut: true,
      validateInput: (value) => {
        try {
          normalizeServerUrl(value);
          return null;
        } catch (e) {
          return (e as Error).message;
        }
      },
    });
    if (!server) return;
    if (normalizeServerUrl(server).insecureRemote) {
      const choice = await vscode.window.showWarningMessage(
        "This address uses http:// to another machine, so your token and code would travel unencrypted.",
        { modal: true }, "Continue anyway",
      );
      if (choice !== "Continue anyway") return;
    }
    const token = await vscode.window.showInputBox({
      title: "OwnCloud: Sign in (2/2)",
      prompt: "Personal access token (console → Settings → Access tokens)",
      password: true,
      ignoreFocusOut: true,
      validateInput: (value) => (/^oc_[A-Za-z0-9_-]{20,120}$/.test(value.trim()) ? null : "Tokens start with oc_"),
    });
    if (!token) return;
    try {
      const me = await this.signInWithToken(server, token.trim());
      void vscode.window.showInformationMessage(
        `Signed in to OwnCloud as ${me.username} (${me.scope === "write" ? "read & write" : "read only"}).`,
      );
    } catch (error) {
      void vscode.window.showErrorMessage(`OwnCloud sign-in failed: ${(error as Error).message}`);
    }
  }

  async signInWithToken(server: string, token: string): Promise<Me> {
    const { origin } = normalizeServerUrl(server);
    const client = new OwnCloudClient(origin, token);
    const me = await client.me();
    await vscode.workspace.getConfiguration("owncloud").update("serverUrl", origin, vscode.ConfigurationTarget.Global);
    await this.context.secrets.store(TOKEN_SECRET, token);
    this.setSignedIn(client, me);
    vscode.workspace.textDocuments.forEach((d) => this.schedule(d, 0));
    return me;
  }

  async signOut(): Promise<void> {
    await this.context.secrets.delete(TOKEN_SECRET);
    this.clear();
    this.setSignedIn(undefined, undefined);
  }

  private async askToSignIn(message: string): Promise<void> {
    if ((await vscode.window.showWarningMessage(message, "Sign in")) === "Sign in") await this.signIn();
  }

  private openConsole(): void {
    try {
      void vscode.env.openExternal(vscode.Uri.parse(`${normalizeServerUrl(this.serverUrl()).origin}/#/console`));
    } catch (e) {
      void vscode.window.showErrorMessage((e as Error).message);
    }
  }

  /** Background work (live analysis) stays quiet on transient errors; commands always report them. */
  handleError(error: unknown, background = false): void {
    if (error instanceof ApiError) {
      if (error.status === 401) {
        this.setSignedIn(undefined, undefined);
        void this.askToSignIn("OwnCloud rejected your access token (expired or revoked).");
        return;
      }
      if (background && error.status === 429) return; // the next edit retries
      if (background && error.status === 0) {
        if (Date.now() - this.lastNetworkWarning < 60_000) return;
        this.lastNetworkWarning = Date.now();
      }
    }
    void vscode.window.showErrorMessage(`OwnCloud: ${(error as Error).message}`);
  }

  // ------------------------------------------------------------ analysis

  findingsFor(uri: vscode.Uri): Finding[] {
    return this.results.get(uri.toString()) ?? [];
  }

  private pathFor(document: vscode.TextDocument): string | null {
    if (document.uri.scheme === "untitled") {
      const ext = EXTENSION_FOR_LANGUAGE[document.languageId];
      return ext ? `untitled${ext}` : null;
    }
    if (document.uri.scheme !== "file") return null;
    const relative = vscode.workspace.asRelativePath(document.uri, false);
    if (/(^|[\\/])(node_modules|\.git|\.owncloud|\.venv|venv|__pycache__)([\\/]|$)/.test(relative)) return null;
    const base = path.basename(document.fileName);
    const ext = base === ".env" ? ".env" : path.extname(base).toLowerCase();
    if (!ANALYSED_EXTENSIONS.has(ext)) return null;
    return analysisPath(relative, base);
  }

  private schedule(document: vscode.TextDocument, delay: number): void {
    if (!this.client || !this.pathFor(document)) return;
    const key = document.uri.toString();
    clearTimeout(this.timers.get(key));
    this.timers.set(key, setTimeout(() => void this.analyze(document).catch((e) => this.handleError(e, true)), delay));
  }

  async analyze(document: vscode.TextDocument): Promise<void> {
    const client = this.client;
    const relative = this.pathFor(document);
    if (!client || !relative) return;
    const text = document.getText();
    if (Buffer.byteLength(text) > MAX_ANALYSED_BYTES) return;
    const version = document.version;
    const result = await client.analyze(relative, text);
    if (document.isClosed || document.version !== version) return; // a newer analysis is on its way
    this.publish(document.uri, result.findings, document);
  }

  private analyzeActive(): void {
    const document = vscode.window.activeTextEditor?.document;
    if (!this.client) return void this.askToSignIn("Sign in to OwnCloud first.");
    if (!document || !this.pathFor(document)) {
      return void vscode.window.showInformationMessage("OwnCloud analyses Python, JavaScript/TypeScript, Go, Java and configuration files.");
    }
    void this.analyze(document).catch((e) => this.handleError(e));
  }

  private async analyzeWorkspace(): Promise<void> {
    const client = this.client;
    if (!client) return void this.askToSignIn("Sign in to OwnCloud first.");
    const limit = this.setting("maxWorkspaceFiles", 500);
    const pattern = `**/*{${[...ANALYSED_EXTENSIONS].join(",")}}`;
    const uris = await vscode.workspace.findFiles(pattern, EXCLUDE, limit);
    let failures = 0;
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "OwnCloud: analysing workspace", cancellable: true },
      async (progress, cancel) => {
        let done = 0;
        const queue = [...uris];
        const worker = async () => {
          for (let uri = queue.shift(); uri && !cancel.isCancellationRequested; uri = queue.shift()) {
            try {
              const stat = await vscode.workspace.fs.stat(uri);
              if (stat.size <= MAX_ANALYSED_BYTES) {
                const text = new TextDecoder("utf-8", { fatal: true }).decode(await vscode.workspace.fs.readFile(uri));
                const relative = analysisPath(vscode.workspace.asRelativePath(uri, false), path.basename(uri.fsPath));
                const result = await client.analyze(relative, text);
                this.publish(uri, result.findings);
              }
            } catch (error) {
              failures++;
              if (error instanceof ApiError && error.status === 401) return this.handleError(error);
            }
            progress.report({ message: `${++done}/${uris.length}`, increment: 100 / Math.max(1, uris.length) });
          }
        };
        await Promise.all([worker(), worker(), worker(), worker()]);
      },
    );
    const total = [...this.results.values()].flat();
    const c = counts(total);
    void vscode.window.showInformationMessage(
      `OwnCloud: ${uris.length} file(s) analysed — ${c.critical} critical, ${c.high} high, ${c.medium} medium, ${c.low} low` +
        (failures ? ` (${failures} could not be analysed)` : "."),
      "Show problems",
    ).then((choice) => choice && vscode.commands.executeCommand("workbench.actions.view.problems"));
  }

  private clear(): void {
    this.results.clear();
    this.diagnostics.clear();
    vscode.window.visibleTextEditors.forEach((e) => this.decorate(e));
    this.updateStatus();
  }

  toRange(finding: { line: number; column: number; end_line: number; end_column: number }, document?: vscode.TextDocument): vscode.Range {
    const start = new vscode.Position(Math.max(0, finding.line - 1), Math.max(0, finding.column - 1));
    const end = new vscode.Position(Math.max(0, finding.end_line - 1), Math.max(0, finding.end_column - 1));
    const range = new vscode.Range(start, end.isBefore(start) ? start : end);
    return document ? document.validateRange(range) : range;
  }

  private publish(uri: vscode.Uri, findings: Finding[], document?: vscode.TextDocument): void {
    this.results.set(uri.toString(), findings);
    this.diagnostics.set(
      uri,
      findings.map((f) => {
        const diagnostic = new vscode.Diagnostic(this.toRange(f, document), `${f.title}: ${f.message}`, DIAGNOSTIC[f.severity]);
        diagnostic.source = f.source === "quantum" ? `${SOURCE} · QuantumTrace` : SOURCE;
        const link = cweUrl(f.cwe);
        diagnostic.code = link ? { value: `${f.cwe} · ${f.severity}`, target: vscode.Uri.parse(link) } : `${f.rule} · ${f.severity}`;
        return diagnostic;
      }),
    );
    vscode.window.visibleTextEditors.filter((e) => e.document.uri.toString() === uri.toString()).forEach((e) => this.decorate(e));
    this.updateStatus();
  }

  private decorate(editor: vscode.TextEditor): void {
    const enabled = this.setting("lineHighlights", true);
    const findings = enabled ? this.findingsFor(editor.document.uri) : [];
    const lines = severityByLine(findings, editor.document.lineCount);
    for (const severity of SEVERITIES) {
      const ranges = [...lines.entries()].filter(([, s]) => s === severity).map(([line]) => new vscode.Range(line - 1, 0, line - 1, 0));
      editor.setDecorations(this.lineDecorations[severity], ranges);
    }
    editor.setDecorations(
      this.criticalSpan,
      findings.filter((f) => f.severity === "critical").map((f) => this.toRange(f, editor.document)),
    );
  }

  private updateStatus(): void {
    if (!this.client || !this.me) {
      this.status.text = "$(shield) OwnCloud: Sign in";
      this.status.tooltip = "Connect VS Code to your OwnCloud account";
      this.status.command = "owncloud.signIn";
      this.status.backgroundColor = undefined;
      return;
    }
    const document = vscode.window.activeTextEditor?.document;
    const findings = document ? this.findingsFor(document.uri) : [];
    const c = counts(findings);
    const parts = SEVERITIES.slice().reverse().filter((s) => c[s]).map((s) => `${c[s]} ${s}`);
    this.status.text = `$(shield) ${parts.length ? parts.join(" · ") : "No issues"}`;
    this.status.tooltip = `OwnCloud · ${this.me.username} @ ${this.client.origin}\nClick to show problems`;
    this.status.command = "workbench.actions.view.problems";
    this.status.backgroundColor = c.critical || c.high ? new vscode.ThemeColor("statusBarItem.errorBackground")
      : c.medium ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
  }
}

class FixProvider implements vscode.CodeActionProvider {
  constructor(private readonly controller: Controller) {}

  provideCodeActions(document: vscode.TextDocument, range: vscode.Range): vscode.CodeAction[] {
    return this.controller
      .findingsFor(document.uri)
      .filter((f) => f.fix && this.controller.toRange(f, document).intersection(range) !== undefined)
      .sort((a, b) => rank(b.severity) - rank(a.severity))
      .map((f) => {
        const action = new vscode.CodeAction(`OwnCloud: ${f.title} → ${f.fix!.text.trim()}`, vscode.CodeActionKind.QuickFix);
        action.edit = new vscode.WorkspaceEdit();
        action.edit.replace(document.uri, this.controller.toRange(f.fix!, document), f.fix!.text);
        action.isPreferred = true;
        return action;
      });
  }
}

class FindingHover implements vscode.HoverProvider {
  constructor(private readonly controller: Controller) {}

  provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
    const findings = this.controller.findingsFor(document.uri).filter((f) => this.controller.toRange(f, document).contains(position)
      || (f.line - 1 === position.line && f.end_line - 1 === position.line && position.character >= f.column - 1));
    if (!findings.length) return undefined;
    const markdown = new vscode.MarkdownString(undefined, true);
    markdown.isTrusted = false; // content comes from analysed code: no command links
    markdown.supportHtml = false;
    for (const f of findings.sort((a, b) => rank(b.severity) - rank(a.severity))) {
      markdown.appendMarkdown(`**$(shield) ${escapeMarkdown(f.title)}** — ${SEVERITY_LABEL[f.severity]}\n\n`);
      markdown.appendMarkdown(`${escapeMarkdown(f.message)}\n\n`);
      if (f.suggestion) markdown.appendMarkdown(`**Suggestion:** ${escapeMarkdown(f.suggestion)}\n\n`);
      if (f.fix) markdown.appendMarkdown(`_Quick fix available (Ctrl+.)_\n\n`);
      const link = cweUrl(f.cwe);
      if (link) markdown.appendMarkdown(`[${f.cwe}](${link}) · `);
      markdown.appendMarkdown(`${f.source === "quantum" ? "QuantumTrace" : escapeMarkdown(f.rule)}\n\n---\n\n`);
    }
    return new vscode.Hover(markdown);
  }
}
