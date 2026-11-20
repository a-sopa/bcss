// Runs src/test/suite.ts inside a real VS Code with an isolated profile and only this extension.
//   VSCODE_CLI=/snap/bin/code  → use an installed VS Code through its launcher (e.g. the snap)
//   VSCODE_PATH=<electron>     → use a specific VS Code binary
//   (neither)                  → @vscode/test-electron downloads a stable build
// The suite writes its results to OWNCLOUD_TEST_RESULTS, which is checked here.
import { spawnSync } from "node:child_process";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { runTests } from "@vscode/test-electron";

async function main(): Promise<void> {
  const root = path.resolve(__dirname, "../..");
  const sandbox = fs.mkdtempSync(path.join(process.env.OWNCLOUD_TEST_TMP ?? os.tmpdir(), "owncloud-vscode-"));
  const workspace = path.join(sandbox, "workspace");
  const results = process.env.OWNCLOUD_TEST_RESULTS ?? path.join(sandbox, "results.txt");
  fs.cpSync(path.join(root, "test-fixtures/workspace"), workspace, { recursive: true });
  const extensionTestsPath = path.join(__dirname, "suite");
  const isolation = ["--disable-extensions", "--disable-workspace-trust", "--skip-welcome", "--skip-release-notes",
    "--user-data-dir", path.join(sandbox, "user"), "--extensions-dir", path.join(sandbox, "extensions")];
  const env = {
    OWNCLOUD_URL: process.env.OWNCLOUD_URL ?? "",
    OWNCLOUD_TEST_TOKEN: process.env.OWNCLOUD_TEST_TOKEN ?? "",
    OWNCLOUD_TEST_RESULTS: results,
    OWNCLOUD_TEST_APP: process.env.OWNCLOUD_TEST_APP ?? "",
    OWNCLOUD_TEST_APP_FILES: process.env.OWNCLOUD_TEST_APP_FILES ?? "",
  };

  if (process.env.VSCODE_CLI) {
    spawnSync(process.env.VSCODE_CLI, [
      "--wait", "--new-window", workspace, ...isolation,
      `--extensionDevelopmentPath=${root}`, `--extensionTestsPath=${extensionTestsPath}`,
    ], { stdio: "inherit", env: { ...process.env, ...env }, timeout: 240_000 });
  } else {
    await runTests({
      vscodeExecutablePath: process.env.VSCODE_PATH,
      extensionDevelopmentPath: root,
      extensionTestsPath,
      launchArgs: [workspace, ...isolation],
      extensionTestsEnv: env,
    });
  }

  const report = fs.existsSync(results) ? fs.readFileSync(results, "utf8") : "";
  console.log(report || "No results were written: the test suite did not run.");
  if (!report.includes("integration checks passed")) process.exit(1);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
