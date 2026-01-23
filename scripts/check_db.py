from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text


def main() -> int:
    database_url = os.getenv("DATABASE_URL") or os.getenv("database_url")
    if not database_url:
        print("DATABASE_URL is not set.")
        return 1

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("DB connection OK.")
        return 0
    except Exception as exc:
        print(f"DB connection failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
