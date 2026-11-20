"""Managed PostgreSQL per app, with autonomous index tuning and query-rewrite advice.

The database runs on the app's private network (host name `db`); the app gets DATABASE_URL.
The optimizer reads pg_stat_statements, explains slow queries with EXPLAIN (GENERIC_PLAN), and for
sequential scans with filters on large tables creates an index, keeps it only if the planner uses it and
the cost drops, and later drops its own indexes that are never used. Rewrites are suggested, not applied.
Only single SELECT/WITH statements are explained, as the app's own (non-superuser) role.
"""

import json
import re
import secrets
import time
from typing import Any

from . import config

IMAGE = "postgres:16-alpine"
SLOW_MS = 10.0
MIN_CALLS = 3
MIN_ROWS = 1000
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SKIP_QUERY = re.compile(r"^\s*(explain|create|drop|alter|set|show|begin|commit|rollback|vacuum|analy[sz]e|copy|grant|reset|insert|update|delete)\b", re.I)

REWRITES: list[tuple[str, re.Pattern, str]] = [
    ("select-star", re.compile(r"^\s*select\s+\*\s+from", re.I),
     "SELECT * reads every column; list only the columns you use so more queries can be answered from an index."),
    ("offset", re.compile(r"\boffset\s+(\$\d+|\d{3,})", re.I),
     "Large OFFSETs read and discard rows. Use keyset pagination: WHERE id > $last_id ORDER BY id LIMIT $n."),
    ("not-in", re.compile(r"\bnot\s+in\s*\(\s*select\b", re.I),
     "NOT IN (SELECT …) is slow and returns nothing if the subquery yields a NULL. Use NOT EXISTS."),
    ("leading-wildcard", re.compile(r"like\s+'%|ilike\s+'%", re.I),
     "A pattern starting with % cannot use a normal index; use a trigram index (pg_trgm) or full-text search."),
    ("random-order", re.compile(r"order\s+by\s+random\(\)", re.I),
     "ORDER BY random() sorts the whole table; use TABLESAMPLE or pick random ids."),
    ("function-on-column", re.compile(r"where\s+.*\b(date|date_trunc|extract|to_char)\s*\(", re.I),
     "A function around a column in WHERE prevents index use; compare the raw column with a range instead."),
]


def container_name(app_id: str) -> str:
    return f"owncloud-db-{app_id}"


def _psql(runtime, app_id: str, sql: str, user: str = "app") -> tuple[int, str]:
    container = runtime.get(container_name(app_id))
    if container is None or container.status != "running":
        return 1, "database is not running"
    result = container.exec_run(["psql", "-U", user, "-d", "app", "-v", "ON_ERROR_STOP=1", "-AtX", "-c", sql])
    return result.exit_code, result.output.decode("utf-8", errors="replace").strip()


def _rows(runtime, app_id: str, sql: str, user: str = "postgres") -> list[dict[str, Any]]:
    code, output = _psql(runtime, app_id, f"SELECT coalesce(json_agg(t), '[]') FROM ({sql}) t", user)
    if code:
        return []
    try:
        return json.loads(output)
    except ValueError:
        return []


def enable(runtime, app_id: str) -> str:
    """Start the database (idempotent) and return the DATABASE_URL for the app."""
    from .runtime import LABEL, ROLE  # avoid an import cycle

    password = secrets.token_hex(16)
    name = container_name(app_id)
    existing = runtime.get(name)
    if existing is not None:
        existing.remove(force=True)
    network = runtime.ensure_network(app_id)
    runtime.client.volumes.create(f"owncloud-db-{app_id}", labels={LABEL: app_id})
    runtime.client.containers.run(
        IMAGE, detach=True, name=name,
        command=["postgres", "-c", "shared_preload_libraries=pg_stat_statements", "-c", "pg_stat_statements.track=top",
                 "-c", "max_connections=60"],
        environment={"POSTGRES_PASSWORD": secrets.token_hex(16), "POSTGRES_DB": "postgres"},
        labels={LABEL: app_id, ROLE: "database"},
        volumes={f"owncloud-db-{app_id}": {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=network, mem_limit="512m", pids_limit=256, security_opt=["no-new-privileges"],
        cap_drop=["NET_RAW", "MKNOD", "AUDIT_WRITE", "SYS_CHROOT", "SETFCAP"],
        restart_policy={"Name": "unless-stopped"},
    )
    runtime.client.networks.get(network).disconnect(name)
    runtime.client.networks.get(network).connect(name, aliases=["db"])
    deadline = time.time() + 90
    while time.time() < deadline:
        container = runtime.get(name)
        if container and container.exec_run(["pg_isready", "-U", "postgres", "-h", "127.0.0.1"]).exit_code == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("The database did not start")
    container = runtime.get(name)
    setup = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app') THEN CREATE ROLE app LOGIN; END IF; END $$;"
        f"ALTER ROLE app PASSWORD '{password}';"
    )
    for command in (
        ["psql", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-c", setup],
        ["sh", "-c", "psql -U postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='app'\" | grep -q 1 || createdb -U postgres -O app app"],
        ["psql", "-U", "postgres", "-d", "app", "-v", "ON_ERROR_STOP=1", "-c", "CREATE EXTENSION IF NOT EXISTS pg_stat_statements"],
    ):
        result = container.exec_run(command)
        if result.exit_code:
            raise RuntimeError(f"Database setup failed: {result.output.decode(errors='replace')[-300:]}")
    return f"postgresql://app:{password}@db:5432/app"


def running(runtime, app_id: str) -> bool:
    container = runtime.get(container_name(app_id))
    return container is not None and container.status == "running"


# ---------------------------------------------------------------- optimizer


def slow_queries(runtime, app_id: str) -> list[dict[str, Any]]:
    return _rows(runtime, app_id, r"""
        SELECT queryid::text AS id, query, calls, round(mean_exec_time::numeric, 2) AS mean_ms,
               round(total_exec_time::numeric, 1) AS total_ms, rows
        FROM pg_stat_statements
        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = 'app') AND toplevel
          AND query !~* '^\s*(explain|create|drop|alter|set|show|begin|commit|rollback|vacuum|analy[sz]e)'
          AND query !~* 'pg_stat_statements|pg_catalog|json_agg'
        ORDER BY mean_exec_time DESC LIMIT 15""")


def _explain(runtime, app_id: str, query: str) -> dict | None:
    if ";" in query.rstrip().rstrip(";") or SKIP_QUERY.match(query) or not re.match(r"^\s*(select|with)\b", query, re.I):
        return None  # only single read statements are explained
    code, output = _psql(runtime, app_id, f"EXPLAIN (FORMAT JSON, GENERIC_PLAN) {query.rstrip().rstrip(';')}")
    if code:
        return None
    try:
        return json.loads(output)[0]["Plan"]
    except (ValueError, KeyError, IndexError):
        return None


def _nodes(plan: dict):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


def _uses_index(plan: dict, index: str) -> bool:
    return any(n.get("Index Name") == index for n in _nodes(plan))


def _candidates(plan: dict) -> list[dict[str, Any]]:
    """Index proposals from sequential scans with filters (equality first, then one range column)."""
    proposals = []
    for node in _nodes(plan):
        if node.get("Node Type") != "Seq Scan" or "Filter" not in node:
            continue
        table, condition = node.get("Relation Name", ""), node["Filter"]
        if not IDENTIFIER.match(table):
            continue
        expressions: list[str] = []
        for column in re.findall(r"lower\(\(?(\w+)\)?(?:::text)?\)\s*=", condition):
            expressions.append(f"lower({column})")
        for column in re.findall(r"\(?(\w+)\)?(?:::\w+(?: \w+)?)?\s*=\s*(?:\$\d+|'[^']*'|\d+)", condition):
            if column not in ("lower",) and column not in expressions and f"lower({column})" not in expressions:
                expressions.append(column)
        for column in re.findall(r"\(?(\w+)\)?(?:::\w+)?\s*(?:>=|<=|>|<)\s*(?:\$\d+|'[^']*'|\d+)", condition):
            if column not in expressions:
                expressions.append(column)
                break
        columns = [e for e in expressions if IDENTIFIER.match(e.removeprefix("lower(").removesuffix(")"))][:3]
        if columns:
            proposals.append({"table": table, "columns": columns, "rows": node.get("Plan Rows", 0)})
    return proposals


def _quote(expression: str) -> str:
    if expression.startswith("lower("):
        return f'lower("{expression[6:-1]}")'
    return f'"{expression}"'


def optimise(runtime, store, app_id: str) -> list[dict[str, Any]]:
    """One optimisation pass; returns the actions taken (also stored)."""
    if not running(runtime, app_id):
        return []
    actions = []
    known = {a["statement"] for a in store.rows("db_actions", app_id, 500)}
    for query in slow_queries(runtime, app_id):
        if query["mean_ms"] < SLOW_MS or query["calls"] < MIN_CALLS:
            continue
        for name, pattern, advice in REWRITES:
            key = f"suggest:{name}:{query['id']}"
            if pattern.search(query["query"]) and key not in known:
                store.insert("db_actions", app_id=app_id, kind="suggestion", statement=key,
                             detail={"rule": name, "advice": advice, "query": query["query"], "mean_ms": query["mean_ms"]})
                known.add(key)
        plan = _explain(runtime, app_id, query["query"])
        if plan is None:
            continue
        for proposal in _candidates(plan):
            reltuples = _rows(runtime, app_id, f"SELECT reltuples::bigint AS n FROM pg_class WHERE relname = '{proposal['table']}'")
            if not reltuples or reltuples[0]["n"] < MIN_ROWS:
                continue
            existing = _rows(runtime, app_id, f"SELECT indexdef FROM pg_indexes WHERE tablename = '{proposal['table']}'")
            leading = proposal["columns"][0]
            if any(re.search(rf"\(\s*{re.escape(leading)}\b|\(\s*{re.escape(leading.removeprefix('lower(').removesuffix(')'))}\s*[,)]", e["indexdef"])
                   for e in existing):
                continue
            label = "_".join(c.replace("lower(", "lower_").rstrip(")") for c in proposal["columns"])
            index = f"oc_{proposal['table']}_{label}_idx"[:63]
            statement = f'CREATE INDEX CONCURRENTLY IF NOT EXISTS "{index}" ON "{proposal["table"]}" ({", ".join(_quote(c) for c in proposal["columns"])})'
            if statement in known:
                continue
            before = plan.get("Total Cost", 0)
            code, output = _psql(runtime, app_id, statement)
            if code:
                store.insert("db_actions", app_id=app_id, kind="index_failed", statement=statement, detail={"error": output[-300:]})
                known.add(statement)
                continue
            _psql(runtime, app_id, f'ANALYZE "{proposal["table"]}"')
            after_plan = _explain(runtime, app_id, query["query"]) or {}
            after = after_plan.get("Total Cost", before)
            kept = _uses_index(after_plan, index) and after < before * 0.5
            if kept:
                _psql(runtime, app_id, f"SELECT pg_stat_statements_reset(0, 0, {int(query['id'])})", user="postgres")
            else:
                _psql(runtime, app_id, f'DROP INDEX CONCURRENTLY IF EXISTS "{index}"')
            action = {"kind": "index_created" if kept else "index_rejected", "statement": statement,
                      "detail": {"index": index, "table": proposal["table"], "columns": proposal["columns"], "query": query["query"],
                                 "query_id": query["id"], "mean_ms_before": query["mean_ms"], "cost_before": before, "cost_after": after}}
            store.insert("db_actions", app_id=app_id, **action)
            actions.append(action)
            known.add(statement)

    # Drop our own indexes that have not been used for a long time.
    created = {a["detail"]["index"]: a["created_at"] for a in store.rows("db_actions", app_id, 500) if a["kind"] == "index_created"}
    for index in _rows(runtime, app_id, "SELECT indexrelname AS name, idx_scan FROM pg_stat_user_indexes WHERE indexrelname LIKE 'oc\\_%'"):
        age_hours = (time.time() - created.get(index["name"], time.time())) / 3600
        if index["idx_scan"] == 0 and age_hours >= config.INDEX_UNUSED_HOURS and IDENTIFIER.match(index["name"]):
            _psql(runtime, app_id, f'DROP INDEX CONCURRENTLY IF EXISTS "{index["name"]}"')
            store.insert("db_actions", app_id=app_id, kind="index_dropped", statement=f'DROP INDEX "{index["name"]}"',
                         detail={"index": index["name"], "reason": f"unused for {age_hours:.0f} h"})
    return actions


def status(runtime, store, app_id: str) -> dict[str, Any]:
    queries = slow_queries(runtime, app_id) if running(runtime, app_id) else []
    by_id = {q["id"]: q for q in queries}
    actions = store.rows("db_actions", app_id, 100)
    for action in actions:
        query_id = (action.get("detail") or {}).get("query_id")
        if query_id in by_id:
            action["detail"]["mean_ms_now"] = by_id[query_id]["mean_ms"]
    tables = _rows(runtime, app_id, "SELECT relname AS name, n_live_tup AS rows FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20") \
        if running(runtime, app_id) else []
    indexes = _rows(runtime, app_id, "SELECT indexrelname AS name, relname AS table, idx_scan AS scans FROM pg_stat_user_indexes ORDER BY relname") \
        if running(runtime, app_id) else []
    return {"running": running(runtime, app_id), "slow_queries": queries, "actions": actions, "tables": tables, "indexes": indexes}
