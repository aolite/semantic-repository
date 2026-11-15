"""Comando ``load-semantic``: carga validada e idempotente de ``SEMANTIC_DIR/data``."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app import ingest
from app.config import get_settings
from app.models import AuditAction, AuditEvent
from app.triplestore import MemoryStore
from tests.conftest import BASE_URI

runner = CliRunner()

EXPECTED_GRAPHS = {
    f"{BASE_URI}vocab/",
    f"{BASE_URI}catalogo",
    f"{BASE_URI}dataset/modbus-tcp-testbed",
    f"{BASE_URI}dataset/hallazgos-auditorias-intrusion",
    f"{BASE_URI}dataset/ejemplos-adversarios-vision",
}


@pytest.fixture(autouse=True)
def _cli_uses_test_doubles(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    store: MemoryStore,
) -> None:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)


def _use_semantic_dir(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("SEMANTIC_DIR", str(path))
    get_settings.cache_clear()
    ingest.clear_caches()


def test_load_semantic_loads_everything(
    store: MemoryStore, session_factory: sessionmaker[Session]
) -> None:
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert store.graph_names() == EXPECTED_GRAPHS
    assert "modbus-tcp-testbed.ttl" in result.output
    assert "versiones 1.0.0, 2.0.0, 2.1.0" in result.output
    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))
    assert {e.action for e in events} == {AuditAction.DATASET_PUBLISHED}
    assert len(events) == 3
    assert {e.actor_username for e in events} == {"cli"}
    assert {e.details["via"] for e in events} == {"cli"}


def test_load_semantic_is_idempotent(store: MemoryStore) -> None:
    runner.invoke(cli_module.cli, ["load-semantic"])
    snapshot = {name: len(store.get_graph(name)) for name in store.graph_names()}
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert result.output.count("sin cambios") == 5
    assert {name: len(store.get_graph(name)) for name in store.graph_names()} == snapshot


def test_loaded_data_is_served_by_the_api(client: TestClient) -> None:
    runner.invoke(cli_module.cli, ["load-semantic"])
    body = client.get("/datasets").json()
    assert body["total"] == 3
    assert {c["domain"]["slug"] for c in body["items"]} == {"ot", "it", "ia"}


def test_invalid_file_aborts_without_loading(
    store: MemoryStore,
    semantic_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = tmp_path / "semantic"
    shutil.copytree(semantic_dir, broken)
    bad = broken / "data" / "sintetico" / "zz-roto.ttl"
    bad.write_text(
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .\n<dataset/roto> a dcat:DatasetSeries .\n",
        encoding="utf-8",
    )
    _use_semantic_dir(monkeypatch, broken)
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 1
    assert "zz-roto.ttl" in result.output
    assert "no se ha cargado nada" in result.output
    assert store.graph_names() == set()


def test_missing_data_dir_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "shapes").mkdir()
    _use_semantic_dir(monkeypatch, tmp_path)
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 2
    assert "vocab-minimo.ttl" in result.output


@pytest.fixture(autouse=True)
def _restore_semantic_dir(semantic_dir: Path):
    yield
    import os

    os.environ["SEMANTIC_DIR"] = str(semantic_dir)
    get_settings.cache_clear()
    ingest.clear_caches()
