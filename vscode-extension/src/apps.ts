import * as path from "node:path";
import * as vscode from "vscode";
import { ApiError, type CloudApp } from "./api";
import type { Controller } from "./extension";
import { isSafeRelativePath, MAX_ANALYSED_BYTES } from "./findings";

const LINK_FILE = ".owncloud/app.json";
const PUSH_EXCLUDE = "{**/node_modules/**,**/.git/**,**/.owncloud/**,**/__pycache__/**,**/.venv/**,**/venv/**,**/Dockerfile.owncloud}";

type Link = { server: string; appId: string; name: string };

const STATUS_ICON: Record<string, string> = {
  running: "testing.iconPassed",
  failed: "testing.iconFailed",
  crashed: "testing.iconFailed",
  blocked: "list.warningForeground",
};

export class AppItem extends vscode.TreeItem {
  constructor(readonly app: CloudApp) {
    super(app.name, vscode.TreeItemCollapsibleState.None);
    this.description = [app.status, app.runtime, app.owner].filter(Boolean).join(" · ");
    this.tooltip = `${app.name} — ${app.status}${app.url ? `\n${app.url}` : ""}`;
    this.contextValue = app.status === "running" ? "app-running" : "app";
    this.iconPath = new vscode.ThemeIcon("circle-filled", new vscode.ThemeColor(STATUS_ICON[app.status] ?? "disabledForeground"));
  }
}

export class AppsProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
  private readonly changed = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData = this.changed.event;

  constructor(private readonly controller: Controller) {}

  refresh(): void {
    this.changed.fire();
  }

  getTreeItem(item: vscode.TreeItem): vscode.TreeItem {
    return item;
  }

  async getChildren(): Promise<vscode.TreeItem[]> {
    const client = this.controller.client;
    if (!client) return [];
    try {
      const apps = await client.apps();
      if (!apps.length) return [new vscode.TreeItem("No apps yet — deploy one from the console")];
      return apps.map((app) => new AppItem(app));
    } catch (error) {
      this.controller.handleError(error);
      return [new vscode.TreeItem("Could not load apps")];
    }
  }
}

async function pickApp(controller: Controller, item?: AppItem): Promise<CloudApp | undefined> {
  if (item) return item.app;
  const client = controller.client;
  if (!client) return undefined;
  const apps = await client.apps();
  const choice = await vscode.window.showQuickPick(
    apps.map((app) => ({ label: app.name, description: app.status, app })),
    { title: "OwnCloud: choose an app" },
  );
  return choice?.app;
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

/** Download an app's source into a folder and show it in VS Code. `target` is used by the tests. */
async function pull(controller: Controller, item?: AppItem, target?: vscode.Uri): Promise<vscode.Uri | undefined> {
  const client = controller.client;
  if (!client) {
    void vscode.window.showWarningMessage("Sign in to OwnCloud first.");
    return undefined;
  }
  const app = await pickApp(controller, item);
  if (!app) return undefined;
  if (!target) {
    const parent = await vscode.window.showOpenDialog({
      canSelectFolders: true, canSelectFiles: false, openLabel: `Download ${app.name} here`,
      title: "OwnCloud: choose where to download the app", defaultUri: vscode.workspace.workspaceFolders?.[0]?.uri,
    });
    if (!parent?.[0]) return undefined;
    target = vscode.Uri.joinPath(parent[0], app.name);
    if (await exists(target) && (await vscode.workspace.fs.readDirectory(target)).length) {
      const choice = await vscode.window.showWarningMessage(`${target.fsPath} already exists. Overwrite files in it?`, { modal: true }, "Overwrite");
      if (choice !== "Overwrite") return undefined;
    }
  }

  const folder = target;
  const unsafe: string[] = [];
  const result = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `OwnCloud: downloading ${app.name}` },
    async (progress) => {
      const archive = await client.archive(app.id); // one request for the whole project
      for (const [index, file] of archive.files.entries()) {
        // Defence in depth: never write outside the chosen folder, whatever the server says.
        if (!isSafeRelativePath(file.path)) {
          unsafe.push(file.path);
          continue;
        }
        await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(folder, ...file.path.split("/")), new TextEncoder().encode(file.content));
        progress.report({ message: `${index + 1}/${archive.files.length}`, increment: 100 / archive.files.length });
      }
      const link: Link = { server: client.origin, appId: app.id, name: app.name };
      await vscode.workspace.fs.writeFile(vscode.Uri.joinPath(folder, ...LINK_FILE.split("/")),
        new TextEncoder().encode(JSON.stringify(link, null, 2) + "\n"));
      return archive;
    },
  );

  const written = result.files.length - unsafe.length;
  const skipped = result.skipped.length + unsafe.length;
  void vscode.window.showInformationMessage(
    `Downloaded ${written} file(s) of ${app.name} to ${folder.fsPath}` + (skipped ? ` (${skipped} binary or unsafe file(s) skipped).` : "."),
  );
  // Show it right away: add it next to the open folders, or open it if the window is empty.
  const open = vscode.workspace.workspaceFolders ?? [];
  if (!open.some((f) => f.uri.toString() === folder.toString())) {
    if (open.length) vscode.workspace.updateWorkspaceFolders(open.length, 0, { uri: folder, name: app.name });
    else await vscode.commands.executeCommand("vscode.openFolder", folder, { forceNewWindow: false });
  }
  return folder;
}

/** The linked app for the current file or workspace: nearest .owncloud/app.json. */
async function findLink(): Promise<{ folder: vscode.Uri; link: Link } | undefined> {
  const candidates: vscode.Uri[] = [];
  const active = vscode.window.activeTextEditor?.document.uri;
  if (active?.scheme === "file") {
    for (let dir = path.dirname(active.fsPath); dir !== path.dirname(dir); dir = path.dirname(dir)) candidates.push(vscode.Uri.file(dir));
  }
  for (const folder of vscode.workspace.workspaceFolders ?? []) candidates.push(folder.uri);
  for (const found of await vscode.workspace.findFiles("**/.owncloud/app.json", "**/node_modules/**", 20)) {
    candidates.push(vscode.Uri.file(path.dirname(path.dirname(found.fsPath))));
  }
  for (const folder of candidates) {
    try {
      const raw = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, ...LINK_FILE.split("/")));
      const link = JSON.parse(new TextDecoder().decode(raw)) as Link;
      if (typeof link.appId === "string" && /^[0-9a-f]{10}$/.test(link.appId) && typeof link.server === "string") {
        return { folder, link };
      }
    } catch {
      /* not linked */
    }
  }
  return undefined;
}

async function push(controller: Controller): Promise<void> {
  const client = controller.client;
  if (!client) return;
  if (!vscode.workspace.isTrusted) {
    return void vscode.window.showWarningMessage("Pushing deploys code: trust this workspace first.");
  }
  const linked = await findLink();
  if (!linked) {
    return void vscode.window.showInformationMessage("This workspace is not linked to an OwnCloud app. Use 'OwnCloud: Download app source' first.");
  }
  const { folder, link } = linked;
  if (link.server !== client.origin) {
    return void vscode.window.showErrorMessage(`This folder belongs to ${link.server}, but you are signed in to ${client.origin}.`);
  }

  const changes: { path: string; content: string }[] = [];
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `OwnCloud: comparing with ${link.name}` },
    async () => {
      const remote = new Map((await client.archive(link.appId)).files.map((f) => [f.path, f.content])); // one request
      const local = await vscode.workspace.findFiles(new vscode.RelativePattern(folder, "**/*"), PUSH_EXCLUDE, 2000);
      for (const uri of local) {
        const relative = path.relative(folder.fsPath, uri.fsPath).split(path.sep).join("/");
        if (!isSafeRelativePath(relative)) continue;
        if ((await vscode.workspace.fs.stat(uri)).size > MAX_ANALYSED_BYTES) continue;
        let content: string;
        try {
          content = new TextDecoder("utf-8", { fatal: true }).decode(await vscode.workspace.fs.readFile(uri));
        } catch {
          continue; // binary files are not pushed
        }
        if (remote.get(relative) === content) continue;
        changes.push({ path: relative, content });
      }
    },
  );
  if (!changes.length) {
    const again = await vscode.window.showInformationMessage(`No changes to push to ${link.name}.`, "Redeploy anyway");
    if (again) await client.redeploy(link.appId);
    return;
  }
  const list = changes.slice(0, 15).map((c) => `• ${c.path}`).join("\n") + (changes.length > 15 ? `\n… and ${changes.length - 15} more` : "");
  const choice = await vscode.window.showWarningMessage(
    `Push ${changes.length} file(s) to ${link.name} and redeploy it?`,
    { modal: true, detail: list },
    "Push and redeploy",
  );
  if (choice !== "Push and redeploy") return;
  try {
    for (const change of changes) await client.saveFile(link.appId, change.path, change.content);
    await client.redeploy(link.appId);
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      return void vscode.window.showErrorMessage("Your access token is read-only. Create a 'Read, save & redeploy' token in the console.");
    }
    throw error;
  }
  const open = await vscode.window.showInformationMessage(`Pushed ${changes.length} file(s); ${link.name} is redeploying.`, "Open console");
  if (open) await vscode.env.openExternal(vscode.Uri.parse(`${client.origin}/#/console`));
}

export function registerAppCommands(context: vscode.ExtensionContext, controller: Controller, apps: AppsProvider): void {
  const run = (action: (item?: AppItem) => Promise<void>) => async (item?: AppItem) => {
    try {
      await action(item);
    } catch (error) {
      controller.handleError(error);
    }
  };
  context.subscriptions.push(
    vscode.commands.registerCommand("owncloud.pullApp", async (item?: AppItem, target?: vscode.Uri) => {
      try {
        return await pull(controller, item, target);
      } catch (error) {
        controller.handleError(error);
        return undefined;
      }
    }),
    vscode.commands.registerCommand("owncloud.pushApp", run(() => push(controller))),
    vscode.commands.registerCommand("owncloud.redeployApp", run(async (item) => {
      const app = await pickApp(controller, item);
      if (!app || !controller.client) return;
      await controller.client.redeploy(app.id);
      apps.refresh();
      void vscode.window.showInformationMessage(`${app.name} is redeploying.`);
    })),
    vscode.commands.registerCommand("owncloud.openAppInConsole", run(async (item) => {
      const app = await pickApp(controller, item);
      if (app && controller.client) await vscode.env.openExternal(vscode.Uri.parse(`${controller.client.origin}/#/console/apps/${app.id}/editor`));
    })),
    vscode.commands.registerCommand("owncloud.openApp", run(async (item) => {
      const url = item?.app.url;
      if (url && /^https?:\/\//.test(url)) await vscode.env.openExternal(vscode.Uri.parse(url));
    })),
  );
}
