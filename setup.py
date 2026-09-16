#!/usr/bin/env python3
"""Azadexa local production setup — PostgreSQL + migrate + seed + verify.

Usage (from the project root):
    python setup.py

Requires: PostgreSQL running on localhost:5432, superuser postgres / 123.
Creates database `azadexa` if missing, runs Alembic migrations, seeds
realistic Arabic data, then verifies the app boots and the test-suite passes.
"""
import os
import subprocess
import sys

PROJECT_DIR = os.path.abspath(os.path.dirname(__file__))
os.chdir(PROJECT_DIR)

PG_SUPER_URL = "postgresql://postgres:123@localhost:5432/postgres"
APP_DB_URL = "postgresql://postgres:123@localhost:5432/azadexa"

FLASK = [sys.executable, "-m", "flask"]


def run(cmd, env=None):
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(r.stdout[-3000:])
        print(r.stderr[-3000:])
        return False
    tail = (r.stdout or "").strip().splitlines()[-3:]
    print("\n".join(tail) or "OK")
    return True


def ensure_database():
    from sqlalchemy import create_engine, text
    try:
        eng = create_engine(PG_SUPER_URL, isolation_level="AUTOCOMMIT")
        with eng.connect() as c:
            exists = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname='azadexa'")
            ).fetchone()
            if not exists:
                print("Creating database 'azadexa' ...")
                c.execute(text("CREATE DATABASE azadexa ENCODING 'UTF8'"))
                print("Database 'azadexa' created.")
            else:
                print("Database 'azadexa' already exists.")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"PostgreSQL unreachable: {e}")
        print("Start PostgreSQL on localhost:5432 (user postgres / password 123).")
        return False


def main():
    print("=" * 60)
    print("Azadexa local production setup  (PostgreSQL)")
    print("=" * 60)
    env = dict(os.environ, DATABASE_URL=APP_DB_URL, USE_CLOUD_DB="1",
                 AZADEXA_AUTO_CREATE="0")

    def stamp_if_unversioned():
        """If tables exist without alembic_version (e.g. a prior create_all
        ran first), stamp head so upgrade becomes a no-op instead of
        crashing on DuplicateTable. Fresh DBs are untouched."""
        from sqlalchemy import create_engine, text
        eng = create_engine(APP_DB_URL)
        with eng.connect() as c:
            has_version = c.execute(text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name='alembic_version'")).fetchone()
            if has_version:
                return True
            tables = c.execute(text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema='public' AND table_type='BASE TABLE'"))
            if tables.scalar():
                print("Tables exist without alembic history — stamping head.")
                return run(FLASK + ["db", "stamp", "head"], env)
        return True

    steps = [
        ("ensure database", ensure_database),
        ("align alembic history", stamp_if_unversioned),
        ("migrate", lambda: run(FLASK + ["db", "upgrade"], env)),
        ("seed", lambda: run([sys.executable, "seed.py"], env)),
        ("verify app boots",
         lambda: run([sys.executable, "-c",
                      "from app import create_app; "
                      "a=create_app(); print('boot OK:', a.name)"], env)),
        ("verify tests (35/35)", lambda: run(
            [sys.executable, "-m", "pytest", "-q"], None)),
    ]
    for name, fn in steps:
        print(f"\n--- {name} ---")
        if not fn():
            print(f"FAILED: {name}")
            sys.exit(1)

    print("\n" + "=" * 60)
    print("Setup complete.")
    print("  server : python -m flask run          (http://localhost:5000)")
    print("  login  : owner/owner123 | admin/admin123 | "
          "engineer/site123 | safety/safe123 | engineer2/site123")
    print("=" * 60)


if __name__ == "__main__":
    main()
