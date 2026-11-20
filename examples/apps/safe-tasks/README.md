# Safe Tasks — ready to deploy

The same task board as [`leaky-tasks`](../leaky-tasks), written securely. The OwnCloud analyzer reports no findings,
and QuantumTrace scores it 0 (only AES-256-GCM, which is quantum-resilient).

- Parameterised SQL, length-checked JSON input, no shell, no `eval`, no deserialisation of user data
- Passwords hashed with salted `scrypt`, compared in constant time; tokens from `secrets`
- Notes sealed with AES-256-GCM and a fresh nonce
- No secrets in the code (`SECRET_KEY` comes from the environment), debug off, security headers on every response
- The page renders tasks with `textContent`, so titles cannot inject HTML

Run locally:

```bash
pip install -r requirements.txt pytest
python -m pytest -q
PORT=8080 python app.py
```

On OwnCloud, upload the folder: it listens on `$PORT`, and the smart CI step runs `tests/` before each version goes live.
Optional environment variables: `SECRET_KEY`, `DATABASE_PATH`.
