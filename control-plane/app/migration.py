"""Migration assistant: what an app needs to move from AWS to OwnCloud.

Deterministic analysis of the uploaded source: where it came from (Lambda, Elastic Beanstalk, …), how it
will run here, which AWS services its code calls and their open-source replacements, the environment
variables its AWS configuration declares, and hard-coded AWS access keys.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import aws_sources
from .runtime import DeployError, detect

# service id → (AWS name, open-source replacement, effort, how to migrate)
# effort: "none" (works as is), "config" (same SDK code, new endpoint), "code" (calls must change)
SERVICES: dict[str, tuple[str, str, str, str]] = {
    "s3": ("Amazon S3", "MinIO", "config",
           "S3-compatible API: keep your SDK code and set AWS_ENDPOINT_URL to the MinIO endpoint."),
    "dynamodb": ("Amazon DynamoDB", "ScyllaDB Alternator", "config",
                 "DynamoDB-compatible API: keep your SDK code and point its endpoint at Alternator."),
    "sqs": ("Amazon SQS", "ElasticMQ", "config",
            "SQS-compatible API: keep your SDK code and point its endpoint at ElasticMQ."),
    "sns": ("Amazon SNS", "NATS or RabbitMQ", "code", "Replace publish/subscribe calls with a NATS or RabbitMQ client."),
    "secretsmanager": ("AWS Secrets Manager", "OwnCloud environment variables", "code",
                       "Move secrets into the app's environment variables (or OpenBao if you need rotation)."),
    "ssm": ("AWS Systems Manager Parameter Store", "OwnCloud environment variables", "code",
            "Read configuration from environment variables instead of Parameter Store."),
    "kms": ("AWS KMS", "OpenBao Transit", "code", "Use OpenBao's Transit engine for encryption keys."),
    "rds": ("Amazon RDS", "PostgreSQL / MySQL container", "config",
            "Database drivers are unchanged; point the connection string at the new database."),
    "rds-data": ("Aurora Data API", "PostgreSQL with a standard driver", "code",
                 "Replace Data API calls with a regular PostgreSQL or MySQL driver."),
    "lambda": ("AWS Lambda (invoke)", "OwnCloud app endpoint", "code",
               "Call the other function's OwnCloud URL over HTTP instead of invoking it."),
    "ses": ("Amazon SES", "Any SMTP server (e.g. Postal)", "code", "Send email through SMTP instead of the SES API."),
    "logs": ("Amazon CloudWatch Logs", "OwnCloud logs", "none",
             "Standard output is collected automatically; CloudWatch calls can be removed."),
    "cloudwatch": ("Amazon CloudWatch", "OwnCloud monitoring", "none",
                   "Container metrics are collected automatically; custom metric calls can be removed."),
    "kinesis": ("Amazon Kinesis", "Redpanda (Kafka API)", "code", "Use a Kafka client against Redpanda."),
    "events": ("Amazon EventBridge", "Scheduled jobs / message broker", "code",
               "Replace event rules with a scheduler or broker subscription."),
    "cognito-idp": ("Amazon Cognito", "Keycloak", "code", "Use Keycloak's OpenID Connect endpoints for sign-in."),
    "stepfunctions": ("AWS Step Functions", "Temporal", "code", "Model the workflow with Temporal."),
    "sts": ("AWS STS", "Not needed", "none", "OwnCloud does not use IAM roles; STS calls can be removed."),
}

ALIASES = {
    "secrets-manager": "secretsmanager", "cloudwatch-logs": "logs", "cloudwatchlogs": "logs",
    "cognito-identity-provider": "cognito-idp", "cognitoidentityserviceprovider": "cognito-idp",
    "lib-dynamodb": "dynamodb", "dynamodbstreams": "dynamodb", "sfn": "stepfunctions",
    "eventbridge": "events", "cloudwatchevents": "events", "sesv2": "ses", "rdsdata": "rds-data",
    "rdsdataservice": "rds-data",
}

SDK_PATTERNS = [
    re.compile(r"""boto3\.(?:client|resource)\(\s*['"]([a-z0-9-]+)['"]"""),  # Python
    re.compile(r"""@aws-sdk/(?:client|lib)-([a-z0-9-]+)"""),  # JavaScript SDK v3
    re.compile(r"""new\s+AWS\.([A-Za-z]+)"""),  # JavaScript SDK v2
    re.compile(r"""github\.com/aws/aws-sdk-go(?:-v2)?/service/([a-z0-9]+)"""),  # Go
    re.compile(r"""(?:software\.amazon\.awssdk\.services|com\.amazonaws\.services)\.([a-z0-9]+)"""),  # Java
]
CODE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".java"}
ACCESS_KEY = re.compile(r"\b((?:AKIA|ASIA)[0-9A-Z]{16})\b")
HTTP_TRIGGERS = {"Api", "HttpApi", "http", "httpApi"}


def _service_id(raw: str) -> str:
    name = raw.lower().split(".")[0]
    return ALIASES.get(name, name)


def _aws_services(root: Path) -> list[dict[str, Any]]:
    files: dict[str, set[str]] = defaultdict(set)
    for name, text in aws_sources.iter_text_files(root, CODE_SUFFIXES):
        for pattern in SDK_PATTERNS:
            for raw in pattern.findall(text):
                files[_service_id(raw)].add(name)
    services = []
    for service_id, used_in in sorted(files.items()):
        aws_name, replacement, effort, how = SERVICES.get(
            service_id, (f"AWS {service_id}", "No mapped equivalent", "code", "Review this dependency manually.")
        )
        services.append({
            "id": service_id, "aws": aws_name, "replacement": replacement,
            "effort": effort, "how": how, "files": sorted(used_in),
        })
    return services


def _access_keys(root: Path) -> list[dict[str, Any]]:
    found = []
    for name, text in aws_sources.iter_text_files(root):
        for number, line in enumerate(text.splitlines(), start=1):
            for key in ACCESS_KEY.findall(line):
                found.append({"file": name, "line": number, "key": f"{key[:4]}…{key[-4:]}"})
    return found


def _platform(root: Path, function: aws_sources.LambdaFunction | None, runtime: str | None) -> str:
    if function is not None:
        if function.source.startswith("serverless"):
            return "AWS Lambda (Serverless Framework)"
        if function.source.startswith("template"):
            return "AWS Lambda (SAM / CloudFormation)"
        return "AWS Lambda"
    if aws_sources.is_beanstalk(root) or runtime == "procfile-python" and (root / "application.py").is_file():
        return "AWS Elastic Beanstalk"
    return {
        "docker": "Container (Dockerfile)",
        "procfile-python": "Procfile app",
        "procfile-node": "Procfile app",
        "node": "Node.js app",
        "python": "Python app",
        "static": "Static site",
    }.get(runtime or "", "Unknown")


def analyze(root: Path) -> dict[str, Any]:
    functions = aws_sources.lambda_functions(root)
    function = functions[0] if functions else None
    try:
        spec = detect(root)
        runtime, runtime_label, error = spec.name, spec.label, None
    except DeployError as exc:
        runtime, runtime_label, error = None, None, str(exc)

    services = _aws_services(root)
    keys = _access_keys(root)
    env, env_sources = aws_sources.environment(root, function)

    efforts = {s["effort"] for s in services}
    if error:
        compatibility = "unsupported"
    elif "code" in efforts:
        compatibility = "changes"
    elif "config" in efforts:
        compatibility = "config"
    else:
        compatibility = "ready"

    notes = []
    if function is not None and runtime:
        notes.append("The function runs unchanged as an always-on HTTP service; API Gateway proxy events are emulated.")
        other = sorted({t for t in function.triggers if t not in HTTP_TRIGGERS})
        if other:
            notes.append(f"Non-HTTP triggers are not emulated: {', '.join(other)}. Call the app's URL from a scheduler or worker instead.")
        if len(functions) > 1:
            names = ", ".join(f.name for f in functions[1:])
            notes.append(f"{len(functions)} functions found; {function.name} is deployed. Deploy {names} as separate apps.")
    if runtime and runtime.startswith("procfile") and runtime_label and "8000" in runtime_label:
        notes.append("The Procfile binds port 8000, as on Elastic Beanstalk; OwnCloud routes traffic to it.")
    if any(s["effort"] == "config" for s in services):
        notes.append("Compatible services only need an endpoint: set AWS_ENDPOINT_URL (supported by recent AWS SDKs).")
    if env:
        notes.append(f"{len(env)} environment variable(s) imported from {', '.join(env_sources)}.")
    if keys:
        notes.append("Remove the hard-coded AWS access keys and rotate them in AWS IAM; use environment variables instead.")

    return {
        "platform": _platform(root, function, runtime),
        "runtime": runtime,
        "runtime_label": runtime_label,
        "compatibility": compatibility,
        "error": error,
        "functions": [f.name for f in functions],
        "services": services,
        "env": env,
        "env_sources": env_sources,
        "access_keys": keys,
        "notes": notes,
    }
