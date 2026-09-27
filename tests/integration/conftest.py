from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from docker.errors import DockerException
from sqlalchemy import create_engine, event, inspect, text
from testcontainers.community.postgres import PostgresContainer

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy import Engine

POSTGRES_IMAGE = "postgres:18-alpine"

NO_DOCKER = (
    "Docker is not reachable, so the tiers that need a real Postgres cannot "
    "run. The static guards and the SQLite tiers still did — those are the "
    "ones that catch the data-destroying case. Start Docker to run this tier."
)


@pytest.fixture(scope="session")
def postgres() -> Iterator[Engine]:
    """A Postgres container. Skips the test when Docker is not available."""
    try:
        container = PostgresContainer(POSTGRES_IMAGE, driver="psycopg")
        container.start()
    except (DockerException, OSError) as error:
        pytest.skip(f"{NO_DOCKER} ({error})")

    started = create_engine(container.get_connection_url())
    try:
        yield started
    finally:
        started.dispose()
        container.stop()


def enforcing_foreign_keys(engine: Engine) -> Engine:
    """Turn SQLite foreign key checks on for each connection, as an application does."""

    @event.listens_for(engine, "connect")
    def _enable(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


@pytest.fixture
def sqlite_engine(tmp_path: Path) -> Iterator[Engine]:
    """An engine on a new SQLite file."""
    started = create_engine(f"sqlite+pysqlite:///{tmp_path / 'local.db'}")
    try:
        yield started
    finally:
        started.dispose()


@pytest.fixture(params=["sqlite", "postgres"])
def prefix_engine(request: pytest.FixtureRequest) -> Iterator[Engine]:
    """An engine on the default schema, of SQLite or of Postgres."""
    if request.param == "sqlite":
        yield request.getfixturevalue("sqlite_engine")
        return

    engine: Engine = request.getfixturevalue("postgres")
    _empty_the_default_schema(engine)
    try:
        yield engine
    finally:
        _empty_the_default_schema(engine)


@pytest.fixture
def schema_engine(postgres: Engine) -> Engine:
    """An engine on Postgres."""
    return postgres


def _empty_the_default_schema(engine: Engine) -> None:
    """Drop each table in the public schema."""
    with engine.connect() as connection:
        for table in inspect(connection).get_table_names(schema="public"):
            connection.execute(text(f'DROP TABLE IF EXISTS public."{table}" CASCADE'))
        connection.commit()
