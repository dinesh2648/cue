"""One-off: copy all data from the SQLite dev DB into the target Postgres DB.

Usage (run from backend/, with DATABASE_URL pointing at Postgres):
    .venv/bin/python -m scripts.migrate_sqlite_to_postgres [sqlite_path]

- Source defaults to ./copilot.db (override with the first arg).
- Target is settings.database_url (must be Postgres).
- Creates the schema on the target (Base.metadata.create_all), then copies every
  table in foreign-key dependency order. Idempotent-ish: it refuses to run if the
  target already has users (so you don't double-import).
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, func, insert, select

from app.config import settings
from app.db import Base
from app import models  # noqa: F401 — register all tables on Base.metadata


def main() -> int:
    src_path = sys.argv[1] if len(sys.argv) > 1 else "./copilot.db"
    src_url = f"sqlite:///{src_path}"
    dst_url = settings.database_url

    if not dst_url.startswith(("postgresql", "postgres")):
        print(f"✗ DATABASE_URL is not Postgres ({dst_url!r}). Set it first.")
        return 1

    src = create_engine(src_url, connect_args={"check_same_thread": False}, future=True)
    dst = create_engine(dst_url, pool_pre_ping=True, future=True)

    # Build schema on the target.
    Base.metadata.create_all(bind=dst)
    print(f"✓ schema ready on target ({dst.url.render_as_string(hide_password=True)})")

    # Safety: don't double-import.
    with dst.connect() as c:
        existing = c.execute(select(func.count()).select_from(models.User.__table__)).scalar() or 0
    if existing:
        print(f"✗ target already has {existing} users — aborting to avoid duplicates.")
        print("  (Drop/recreate the DB if you want a clean re-import.)")
        return 2

    total = 0
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:  # FK-safe order
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            if not rows:
                print(f"  · {table.name}: 0")
                continue
            d.execute(insert(table), rows)
            total += len(rows)
            print(f"  ✓ {table.name}: {len(rows)}")

    print(f"\n✓ migrated {total} rows from {src_path} → Postgres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
