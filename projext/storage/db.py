"""
Database connection helper for the storage layer.

Reads connection details from environment variables so no password ever
lives in code or gets committed to the repo. Values are loaded from a
.env file at the repo root via python-dotenv (load_dotenv() below finds
it automatically by searching upward from this file's location).

Required environment variables:
    DB_HOST      e.g. "localhost"
    DB_PORT      e.g. "5432"
    DB_NAME      e.g. "healthsync"
    DB_USER      e.g. "postgres"
    DB_PASSWORD  your local Postgres password
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    """Opens and returns a new psycopg2 connection to the healthsync database."""
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "healthsync"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
    )


if __name__ == "__main__":
    # Quick manual test: run `python db.py` to confirm the connection works.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1;")
    result = cur.fetchone()
    print(f"Connected successfully. Test query returned: {result}")
    cur.close()
    conn.close()
