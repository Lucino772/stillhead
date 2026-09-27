from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from stillhead import ValidatedModule, commands, use_schema
from stillhead.errors import InvalidSchemaName, SchemaNotSupported


def test_refuses_sqlite() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with (
        engine.connect() as connection,
        pytest.raises(SchemaNotSupported, match="orders"),
        use_schema(connection, "orders"),
    ):
        pass


def test_refuses_sqlite_before_touching_the_connection() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.connect() as connection:
        with pytest.raises(SchemaNotSupported), use_schema(connection, "orders"):
            pass

        # Still usable afterwards.
        assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1


def test_offline_sql_refuses_a_schema_on_sqlite(alpha: ValidatedModule) -> None:
    with pytest.raises(SchemaNotSupported):
        commands.emit_upgrade_sql(alpha, "sqlite:///unused.db", "head", "orders")


def test_offline_sql_refuses_a_schema_name_that_is_not_an_identifier(
    alpha: ValidatedModule,
) -> None:
    with pytest.raises(InvalidSchemaName):
        commands.emit_upgrade_sql(
            alpha, "postgresql+psycopg://unused/unused", "head", 'x"; DROP TABLE y; --'
        )
