// Run an AWS Lambda handler (Node.js) as an HTTP service, emulating API Gateway proxy events.
// Copied into the app's build context by OwnCloud. The handler comes from OWNCLOUD_LAMBDA_HANDLER,
// e.g. "index.handler" or "src/handlers/orders.handler", relative to the working directory.

import http from "node:http";
import path from "node:path";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";

const SPEC = process.env.OWNCLOUD_LAMBDA_HANDLER;
const FUNCTION_NAME = process.env.AWS_LAMBDA_FUNCTION_NAME || "owncloud-function";
const TIMEOUT_MS = Number(process.env.AWS_LAMBDA_FUNCTION_TIMEOUT || 30) * 1000;
const require = createRequire(path.join(process.cwd(), "index.js"));

async function loadHandler() {
  const dot = SPEC.lastIndexOf(".");
  const base = path.resolve(process.cwd(), SPEC.slice(0, dot));
  const name = SPEC.slice(dot + 1);
  for (const ext of [".mjs", ".js", ".cjs"]) {
    const file = base + ext;
    if (!existsSync(file)) continue;
    let mod;
    if (ext === ".cjs") mod = require(file);
    else {
      try {
        mod = await import(pathToFileURL(file).href);
      } catch (error) {
        if (ext !== ".js") throw error;
        mod = require(file);
      }
    }
    const fn = mod[name] ?? mod.default?.[name];
    if (typeof fn !== "function") throw new Error(`${SPEC}: "${name}" is not exported from ${file}`);
    return fn;
  }
  throw new Error(`Cannot find the handler module for ${SPEC}`);
}

const handler = await loadHandler();

function context() {
  const deadline = Date.now() + TIMEOUT_MS;
  const awsRequestId = randomUUID();
  return {
    functionName: FUNCTION_NAME,
    functionVersion: "$LATEST",
    invokedFunctionArn: `arn:owncloud:lambda:local:function:${FUNCTION_NAME}`,
    memoryLimitInMB: process.env.AWS_LAMBDA_FUNCTION_MEMORY_SIZE || "256",
    awsRequestId,
    logGroupName: `/owncloud/${FUNCTION_NAME}`,
    logStreamName: awsRequestId,
    callbackWaitsForEmptyEventLoop: true,
    getRemainingTimeInMillis: () => Math.max(0, deadline - Date.now()),
  };
}

function toEvent(req, raw, requestId) {
  const url = new URL(req.url, "http://localhost");
  const text = raw.toString("utf8");
  const encoded = raw.length > 0 && Buffer.from(text, "utf8").compare(raw) !== 0;
  const multiQuery = {};
  for (const [key, value] of url.searchParams) (multiQuery[key] ??= []).push(value);
  const query = Object.fromEntries(Object.entries(multiQuery).map(([k, v]) => [k, v.at(-1)]));
  const multiHeaders = {};
  for (let i = 0; i < req.rawHeaders.length; i += 2) (multiHeaders[req.rawHeaders[i]] ??= []).push(req.rawHeaders[i + 1]);
  const headers = Object.fromEntries(Object.entries(multiHeaders).map(([k, v]) => [k, v.join(", ")]));
  const sourceIp = String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();
  return {
    resource: "/{proxy+}",
    path: url.pathname,
    httpMethod: req.method,
    headers,
    multiValueHeaders: multiHeaders,
    queryStringParameters: Object.keys(query).length ? query : null,
    multiValueQueryStringParameters: Object.keys(multiQuery).length ? multiQuery : null,
    pathParameters: { proxy: url.pathname.replace(/^\//, "") },
    stageVariables: null,
    requestContext: {
      requestId,
      stage: "owncloud",
      httpMethod: req.method,
      path: url.pathname,
      identity: { sourceIp, userAgent: req.headers["user-agent"] },
      http: { method: req.method, path: url.pathname, sourceIp },
    },
    rawPath: url.pathname,
    rawQueryString: url.search.replace(/^\?/, ""),
    body: raw.length ? (encoded ? raw.toString("base64") : text) : null,
    isBase64Encoded: encoded,
  };
}

function invoke(event, ctx) {
  if (handler.length >= 3) {
    return new Promise((resolve, reject) => {
      const result = handler(event, ctx, (error, value) => (error ? reject(error) : resolve(value)));
      if (result && typeof result.then === "function") result.then(resolve, reject);
    });
  }
  return Promise.resolve(handler(event, ctx));
}

function send(res, status, headers, data) {
  for (const [key, value] of headers) {
    if (!["content-length", "connection", "transfer-encoding"].includes(key.toLowerCase())) res.appendHeader(key, value);
  }
  res.writeHead(status, { "Content-Length": data.length });
  res.end(data);
}

const port = Number(process.env.PORT || 8080);
http
  .createServer((req, res) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", async () => {
      const ctx = context();
      try {
        const result = await invoke(toEvent(req, Buffer.concat(chunks), ctx.awsRequestId), ctx);
        if (result && typeof result === "object" && "statusCode" in result) {
          const headers = Object.entries(result.headers || {}).map(([k, v]) => [k, String(v)]);
          for (const [k, values] of Object.entries(result.multiValueHeaders || {})) for (const v of values) headers.push([k, String(v)]);
          for (const cookie of result.cookies || []) headers.push(["Set-Cookie", String(cookie)]);
          const body = result.body ?? "";
          const data = result.isBase64Encoded
            ? Buffer.from(body, "base64")
            : Buffer.from(typeof body === "string" ? body : JSON.stringify(body));
          send(res, Number(result.statusCode), headers, data);
        } else {
          send(res, 200, [["Content-Type", "application/json"]], Buffer.from(JSON.stringify(result ?? null)));
        }
      } catch (error) {
        console.error(error);
        send(res, 502, [["Content-Type", "application/json"]], Buffer.from('{"message":"Internal server error"}'));
      }
    });
  })
  .listen(port, () => console.log(`Lambda handler ${SPEC} listening on port ${port} (API Gateway proxy emulation)`));
