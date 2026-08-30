"""
sandbox.py

Manages a disposable local Postgres container: spin up, apply a schema
(and later, a fix), run a query as a simulated Supabase role, tear down.

Role simulation matches how Supabase actually does it: connect as the
postgres superuser, SET ROLE to anon or authenticated, and set
request.jwt.claim.sub to fake the caller's identity, which is exactly
what auth.uid() reads. Every probe runs inside BEGIN...ROLLBACK, so
write probes (INSERT/UPDATE) never actually persist data.

This only ever touches a local, disposable container. Never point this
at a live, third-party, or production database.
"""

import subprocess
import time
from pathlib import Path

import psycopg2

CONTAINER_NAME = "rlsguard-sandbox"
IMAGE = "postgres:16"
HOST_PORT = 55432
DB_NAME = "sandbox"
DB_USER = "postgres"
DB_PASSWORD = "sandboxpw"

BOOTSTRAP_SQL_PATH = Path(__file__).parent / "sandbox_bootstrap.sql"


class Sandbox:
    def __init__(self):
        self._conn = None

    def start(self, timeout_seconds: int = 30):
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", CONTAINER_NAME,
                "-e", f"POSTGRES_PASSWORD={DB_PASSWORD}",
                "-e", f"POSTGRES_DB={DB_NAME}",
                "-p", f"{HOST_PORT}:5432",
                "-v", f"{BOOTSTRAP_SQL_PATH}:/docker-entrypoint-initdb.d/01_bootstrap.sql:ro",
                IMAGE,
            ],
            check=True,
            capture_output=True,
        )
        self._wait_ready(timeout_seconds)
        self._conn = psycopg2.connect(
            host="localhost", port=HOST_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        self._conn.autocommit = True

    def _wait_ready(self, timeout_seconds: int):
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            result = subprocess.run(
                ["docker", "exec", CONTAINER_NAME, "pg_isready", "-U", DB_USER],
                capture_output=True,
            )
            if result.returncode == 0:
                return
            time.sleep(1)
        raise TimeoutError("Postgres container did not become ready in time")

    def apply_sql(self, sql_text: str):
        with self._conn.cursor() as cur:
            cur.execute(sql_text)

    def apply_sql_fetch(self, sql_text: str):
        """Like apply_sql, but returns fetched rows (for INSERT ... RETURNING)."""
        with self._conn.cursor() as cur:
            cur.execute(sql_text)
            try:
                return cur.fetchall()
            except psycopg2.ProgrammingError:
                return None

    def execute_as(self, role: str, jwt_sub, query: str):
        """
        Run `query` inside BEGIN...ROLLBACK as `role` (anon or
        authenticated), with request.jwt.claim.sub set to jwt_sub
        (or left unset if jwt_sub is None, simulating anon with no
        identity at all). Returns fetched rows on success, raises
        psycopg2.Error if RLS or a grant denies it. Always rolls back.
        """
        conn = psycopg2.connect(
            host="localhost", port=HOST_PORT, dbname=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
        )
        conn.autocommit = False
        try:
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL ROLE {role}")
                if jwt_sub is not None:
                    cur.execute(f"SET LOCAL request.jwt.claim.sub = '{jwt_sub}'")
                cur.execute(query)
                try:
                    rows = cur.fetchall()
                except psycopg2.ProgrammingError:
                    rows = None
            return rows
        finally:
            conn.rollback()
            conn.close()

    def stop(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME], capture_output=True)


if __name__ == "__main__":
    sb = Sandbox()
    print("starting sandbox (first run pulls postgres:16, can take a minute)...")
    sb.start()
    print("sandbox is up")
    sb.apply_sql("create table public.smoke_test (id serial primary key);")
    print("applied a trivial schema successfully")
    rows = sb.execute_as("anon", None, "select 1")
    print("query as anon succeeded:", rows)
    sb.stop()
    print("sandbox torn down")