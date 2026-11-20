"""Run an AWS Lambda handler as an HTTP service, emulating API Gateway proxy events.

Copied into the app's build context by OwnCloud. The handler comes from OWNCLOUD_LAMBDA_HANDLER,
e.g. "app.lambda_handler" or "src/handlers/orders.handler", relative to the working directory.
"""

import base64
import importlib
import json
import os
import sys
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SPEC = os.environ["OWNCLOUD_LAMBDA_HANDLER"]
FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "owncloud-function")
TIMEOUT_MS = int(os.environ.get("AWS_LAMBDA_FUNCTION_TIMEOUT", "30")) * 1000
MEMORY_MB = os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE", "256")

module_path, function_name = SPEC.rsplit(".", 1)
sys.path.insert(0, os.getcwd())
handler = getattr(importlib.import_module(module_path.replace("/", ".")), function_name)


class Context:
    def __init__(self) -> None:
        self.function_name = FUNCTION_NAME
        self.function_version = "$LATEST"
        self.invoked_function_arn = f"arn:owncloud:lambda:local:function:{FUNCTION_NAME}"
        self.memory_limit_in_mb = MEMORY_MB
        self.aws_request_id = str(uuid.uuid4())
        self.log_group_name = f"/owncloud/{FUNCTION_NAME}"
        self.log_stream_name = self.aws_request_id
        self._deadline = time.monotonic() * 1000 + TIMEOUT_MS

    def get_remaining_time_in_millis(self) -> int:
        return max(0, int(self._deadline - time.monotonic() * 1000))


class Shim(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _event(self, request_id: str) -> dict:
        url = urlsplit(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body, encoded = raw.decode("utf-8"), False
        except UnicodeDecodeError:
            body, encoded = base64.b64encode(raw).decode(), True
        multi_query = parse_qs(url.query, keep_blank_values=True)
        headers = {k: v for k, v in self.headers.items()}
        multi_headers: dict[str, list[str]] = {}
        for key, value in self.headers.items():
            multi_headers.setdefault(key, []).append(value)
        source_ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        return {
            "resource": "/{proxy+}",
            "path": url.path,
            "httpMethod": self.command,
            "headers": headers,
            "multiValueHeaders": multi_headers,
            "queryStringParameters": {k: v[-1] for k, v in multi_query.items()} or None,
            "multiValueQueryStringParameters": multi_query or None,
            "pathParameters": {"proxy": url.path.lstrip("/")},
            "stageVariables": None,
            "requestContext": {
                "requestId": request_id,
                "stage": "owncloud",
                "httpMethod": self.command,
                "path": url.path,
                "identity": {"sourceIp": source_ip, "userAgent": self.headers.get("User-Agent")},
                "http": {"method": self.command, "path": url.path, "sourceIp": source_ip},
            },
            "rawPath": url.path,
            "rawQueryString": url.query,
            "body": body or None,
            "isBase64Encoded": encoded,
        }

    def _send(self, status: int, headers: list[tuple[str, str]], data: bytes) -> None:
        self.send_response(status)
        for key, value in headers:
            if key.lower() not in ("content-length", "connection", "transfer-encoding"):
                self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _handle(self) -> None:
        context = Context()
        try:
            result = handler(self._event(context.aws_request_id), context)
        except Exception:
            traceback.print_exc()
            self._send(502, [("Content-Type", "application/json")], b'{"message": "Internal server error"}')
            return

        if isinstance(result, dict) and "statusCode" in result:
            headers = [(str(k), str(v)) for k, v in (result.get("headers") or {}).items()]
            for key, values in (result.get("multiValueHeaders") or {}).items():
                headers += [(str(key), str(v)) for v in values]
            headers += [("Set-Cookie", str(c)) for c in result.get("cookies") or []]
            body = result.get("body") or ""
            if result.get("isBase64Encoded"):
                data = base64.b64decode(body)
            else:
                data = (body if isinstance(body, str) else json.dumps(body)).encode()
            self._send(int(result["statusCode"]), headers, data)
        else:
            self._send(200, [("Content-Type", "application/json")], json.dumps(result).encode())

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _handle


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"Lambda handler {SPEC} listening on port {port} (API Gateway proxy emulation)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Shim).serve_forever()
