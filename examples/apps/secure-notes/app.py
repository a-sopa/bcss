"""Demo app using quantum-resilient primitives (AES-256-GCM, SHA-512), standard library + cryptography."""

import hashlib
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY = AESGCM.generate_key(bit_length=256)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        nonce = os.urandom(12)
        sealed = AESGCM(KEY).encrypt(nonce, b"note", None)
        digest = hashlib.sha512(sealed).hexdigest()[:16]
        body = f"<h1>Secure notes</h1><p>Sealed with AES-256-GCM. Digest (SHA-512): {digest}</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
