"""Orders, stored in the managed PostgreSQL database (DATABASE_URL) when there is one."""

import os

URL = os.environ.get("DATABASE_URL")


def available() -> bool:
    return bool(URL)


def normalise_email(email: str) -> str:
    return email.strip().lower()


def _connect():
    import psycopg

    return psycopg.connect(URL, autocommit=True)


def prepare() -> None:
    """Create and fill the orders table once (500 000 rows, no index on customer_email)."""
    if not URL:
        return
    with _connect() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS orders (
            id bigserial PRIMARY KEY, customer_email text NOT NULL, total numeric(10,2) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""")
        if connection.execute("SELECT count(*) FROM orders").fetchone()[0] == 0:
            connection.execute("""INSERT INTO orders (customer_email, total, created_at)
                SELECT 'customer' || (g % 20000) || '@example.eu', (g % 9000) / 100.0, now() - (g || ' minutes')::interval
                FROM generate_series(1, 500000) g""")
            connection.execute("ANALYZE orders")


def for_customer(email: str) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            "SELECT id, total, created_at FROM orders WHERE customer_email = %s ORDER BY created_at DESC LIMIT 20",
            (normalise_email(email),),
        ).fetchall()
    return [{"id": r[0], "total": float(r[1]), "created_at": r[2].isoformat()} for r in rows]


def recent(page: int) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 20 OFFSET %s", (max(0, page) * 20,)).fetchall()
    return [{"id": r[0], "email": r[1], "total": float(r[2])} for r in rows]
