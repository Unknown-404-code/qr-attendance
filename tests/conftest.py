import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import os  # noqa: E402
import secrets  # noqa: E402

import pytest  # noqa: E402

BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("GA_TEST_DATABASE_URL") else [])


@pytest.fixture(params=BACKENDS)
def db_url(request, tmp_path):
    """(target, schema) for a fresh database: a SQLite file, or a throwaway Postgres schema."""
    if request.param == "sqlite":
        yield str(tmp_path / "t.sqlite"), None
        return
    import psycopg
    url = os.environ["GA_TEST_DATABASE_URL"]
    schema = "t_" + secrets.token_hex(6)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {schema}")
    yield url, schema
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(f"DROP SCHEMA {schema} CASCADE")
