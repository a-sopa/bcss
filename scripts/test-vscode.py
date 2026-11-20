"""Run the VS Code extension's tests against the running stack (docker compose up).

    control-plane/.venv/bin/python scripts/test-vscode.py [--vscode-cli /snap/bin/code]

Creates a temporary account, a 150-file app and an access token, runs the Node unit tests and the
integration tests inside a real VS Code (isolated profile), then removes everything it created.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "security-tests"))
from conftest import browser, cli  # noqa: E402

FILES = 150


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vscode-cli", default=os.environ.get("VSCODE_CLI", "/snap/bin/code"))
    args = parser.parse_args()

    user = "vscode-test"
    cli("delete", user, check=False)
    client = browser(user, cli("create", user))
    files = [("files", ("big-app/index.html", b"<h1>big</h1>"))] + [
        ("files", (f"big-app/src/module_{i:03}.js", f"export const v{i} = {i};\n".encode())) for i in range(FILES - 1)
    ]
    app = client.post("/api/apps", data={"name": "big-app"}, files=files).json()["id"]
    token = client.post("/api/tokens", json={"name": "vscode tests", "scope": "read", "days": 1}).json()["token"]
    env = {
        **os.environ, "OWNCLOUD_URL": "http://localhost:8088", "OWNCLOUD_TEST_TOKEN": token,
        "VSCODE_CLI": args.vscode_cli, "OWNCLOUD_TEST_TMP": tempfile.gettempdir(),
        "OWNCLOUD_TEST_APP": app, "OWNCLOUD_TEST_APP_FILES": str(FILES),
    }
    extension = ROOT / "vscode-extension"
    try:
        unit = subprocess.run(["node", "--test", "out/test/unit.test.js"], cwd=extension, env=env, capture_output=True, text=True)
        print("\n".join(line for line in unit.stdout.splitlines() if line.startswith(("ok", "not ok", "# pass", "# fail"))))
        ide = subprocess.run(["node", "out/test/runVsCode.js"], cwd=extension, env=env, capture_output=True, text=True, timeout=300)
        print(ide.stdout.strip())
        return unit.returncode or ide.returncode
    finally:
        client.delete(f"/api/apps/{app}")
        client.close()
        cli("delete", user, check=False)


if __name__ == "__main__":
    sys.exit(main())
