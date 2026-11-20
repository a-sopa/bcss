"""Demo app with quantum-vulnerable cryptography (RSA-2048 signatures, SHA-1)."""

import hashlib
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

SIGNING_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        receipt = f"payment:{self.path}".encode()
        signature = SIGNING_KEY.sign(receipt, padding.PKCS1v15(), hashes.SHA256())
        fingerprint = hashlib.sha1(signature).hexdigest()
        body = f"<h1>Legacy payments</h1><p>Receipt signed with RSA-2048. Fingerprint (SHA-1): {fingerprint}</p>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())


HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
