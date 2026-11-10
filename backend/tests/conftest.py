import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.config import BACKEND_DIR, PROJECT_DIR, Settings
from app.db import build_engine


def pytest_addoption(parser):
    parser.addoption(
        "--require-postgres",
        action="store_true",
        help="Fail instead of skipping integration tests when TEST_DATABASE_URL is absent",
    )


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://test:test@127.0.0.1:1/algomentor_test",
    )


@pytest.fixture
def postgres_engine(request):
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(PROJECT_DIR / ".env").get(
        "TEST_DATABASE_URL"
    )
    if not url:
        if request.config.getoption("--require-postgres"):
            pytest.fail("TEST_DATABASE_URL is required; use a disposable database ending in _test")
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL integration tests")
    parsed = make_url(url)
    if not parsed.database or not parsed.database.endswith("_test"):
        pytest.fail("Safety check: TEST_DATABASE_URL database name must end in _test")

    # No public tables are dropped: each test owns an unpredictable, isolated schema.
    schema = "test_" + uuid4().hex
    admin = build_engine(Settings(_env_file=None, database_url=url))
    engine = None
    with admin.begin() as connection:
        connection.execute(CreateSchema(schema))
    try:
        engine = create_engine(
            url,
            hide_parameters=True,
            connect_args={
                "connect_timeout": 5,
                "options": f"-c timezone=UTC -c search_path={schema} -c statement_timeout=5000",
            },
        )
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@pytest.fixture
def migrated_engine(postgres_engine):
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    with postgres_engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return postgres_engine


@pytest.fixture
def db_session(migrated_engine):
    with Session(migrated_engine, expire_on_commit=False) as session:
        yield session
