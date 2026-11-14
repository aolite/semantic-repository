"""Las migraciones de Alembic aplican, revierten y coinciden con los modelos.

Por defecto se ejecutan sobre un fichero SQLite temporal. Con ``TEST_DATABASE_URL``
apuntando a un PostgreSQL vacío se ejecutan también contra él.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import Base

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _urls(tmp_path: Path) -> list[str]:
    urls = [f"sqlite:///{tmp_path / 'migrations.db'}"]
    if os.environ.get("TEST_DATABASE_URL"):
        urls.append(os.environ["TEST_DATABASE_URL"])
    return urls


@pytest.fixture
def database_urls(tmp_path: Path) -> Iterator[list[str]]:
    yield _urls(tmp_path)


def _config(url: str) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False
    return config


def test_upgrade_matches_models_and_downgrade(database_urls: list[str]) -> None:
    for url in database_urls:
        engine = create_engine(url)
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
        config = _config(url)

        command.upgrade(config, "head")
        tables = set(inspect(engine).get_table_names())
        assert {"users", "audit_events", "alembic_version"} <= tables

        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            diff = compare_metadata(context, Base.metadata)
        assert diff == [], f"Los modelos y las migraciones difieren en {url}: {diff}"

        command.downgrade(config, "base")
        assert not {"users", "audit_events"} & set(inspect(engine).get_table_names())
        engine.dispose()
