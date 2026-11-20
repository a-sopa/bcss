# OwnCloud Security for VS Code

OwnCloud's code security analysis inside VS Code — the same analysis and colours as the OwnCloud web editor.

- **Colour-coded lines** in every Python, JavaScript/TypeScript, Go, Java and configuration file:
  yellow (low), orange (medium), red (high), black (critical) — plus gutter markers and Problems-panel entries.
- **Explanations** on hover: what is wrong, why, the CWE, and how to fix it.
- **Quick fixes** (`Ctrl+.`) such as `yaml.load` → `yaml.safe_load` or a hard-coded secret → `os.environ[...]`.
- **Live**: re-analysed as you type, or run *OwnCloud: Analyse workspace* for every file.
- **Post-quantum readiness** findings from QuantumTrace (RSA, ECC, weak hashes…).
- **Your apps**: the OwnCloud view lists your apps; download an app's source, edit it, and *Push changes and redeploy*.

## Sign in

1. In the OwnCloud console: **Settings → Access tokens → Create** (choose *Read & analyse*, or *Read, save & redeploy* to push).
2. In VS Code: **OwnCloud: Sign in** (Command Palette), enter the console address (e.g. `http://localhost:8088`) and paste the token.

## Security

- The token is kept in VS Code's encrypted secret storage, sent only to the configured server, and never with a redirect.
- Use `https://` for any server other than this machine (you are warned otherwise).
- Tokens can only read/analyse code (and, with write scope, save files and redeploy); they cannot change your account.
- Analysed code is sent to your OwnCloud server only. Pushing (which deploys code) needs a trusted workspace.
