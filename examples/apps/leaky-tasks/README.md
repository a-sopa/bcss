# Leaky Tasks — deliberately vulnerable

A tiny Flask task board with a classic vulnerability in almost every route. **Demo only: never expose it.**
Deploy it on OwnCloud and open **Code** to see the editor light up, or turn on the QuantumTrace gate to watch it block the deploy.

| Severity | What is in here |
| --- | --- |
| Critical | SQL injection (`/tasks`), command injection (`/ping`), `eval` (`/calc`), `pickle.loads` (`/import`), leaked AWS key |
| High | reflected XSS (`/`), MD5 passwords, `yaml.load`, SSRF + `verify=False` (`/fetch`), path traversal (`/files`), hard-coded secret, `debug=True` |
| Medium | `DEBUG = True`, predictable token (`random`), AES-ECB, password in `config.ini` |
| Low | `http://` URL, request without timeout, `except: pass` |
| QuantumTrace | RSA-1024 (critical), AES-128 (medium), MD5 |

Its fixed twin is [`safe-tasks`](../safe-tasks).
