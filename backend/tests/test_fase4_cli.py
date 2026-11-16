"""Fase 4 en ``load-semantic``: ficheros sintéticos, inmutabilidad, catálogo y FAIR."""

import hashlib
import shutil
from pathlib import Path

import pytest
from rdflib import URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app import ingest, owl_metrics, vocab_ingest
from app.config import get_settings
from app.models import AuditAction, AuditEvent, DistributionFile, FairEvaluation
from app.storage import DiskStorage
from app.triplestore import MemoryStore
from app.uris import DCAT, Uris
from tests.conftest import BASE_URI

runner = CliRunner()
CSV = b"# SINTETICO\r\na,b\r\n1,2\r\n"


@pytest.fixture
def semantic_copy(
    tmp_path: Path, semantic_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    root = tmp_path / "semantic"
    shutil.copytree(semantic_dir, root)
    # Parte de cero: ``semantic/`` ya trae ficheros sintéticos reales.
    shutil.rmtree(root / "data" / "sintetico" / "ficheros", ignore_errors=True)
    files = root / "data" / "sintetico" / "ficheros" / "modbus-tcp-testbed"
    (files / "2.1.0").mkdir(parents=True)
    (files / "1.0.0").mkdir(parents=True)
    (files / "2.1.0" / "csv.csv").write_bytes(CSV)
    (files / "1.0.0" / "pcap.pcap").write_bytes(b"\xd4\xc3\xb2\xa1")
    # Falta a propósito el Parquet de la 2.1.0: queda «unavailable», no es un error.
    monkeypatch.setenv("SEMANTIC_DIR", str(root))
    get_settings.cache_clear()
    ingest.clear_caches()
    yield root
    get_settings.cache_clear()
    ingest.clear_caches()


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    store: MemoryStore,
    tmp_path: Path,
) -> DiskStorage:
    storage = DiskStorage(tmp_path / "distribuciones")
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: storage)

    def fake(prepared: vocab_ingest.PreparedOntology, _settings: object) -> tuple[dict, dict]:
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
        return metrics.to_dict(), owl_metrics.Consistency(detail="sin Pellet").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)
    return storage


def _load() -> object:
    return runner.invoke(cli_module.cli, ["load-semantic"])


def test_load_uploads_files_and_enqueues_fair(
    semantic_copy: Path, cli_env: DiskStorage, session_factory: sessionmaker[Session]
) -> None:
    result = _load()
    assert result.exit_code == 0, result.output
    assert "modbus-tcp-testbed/2.1.0/csv: subido" in result.output
    assert cli_env.exists("modbus-tcp-testbed/2.1.0/csv")
    assert not cli_env.exists("modbus-tcp-testbed/2.1.0/parquet")
    with session_factory() as session:
        record = session.get(DistributionFile, "modbus-tcp-testbed/2.1.0/csv")
        assert record is not None
        assert record.sha256 == hashlib.sha256(CSV).hexdigest()  # bytes tal cual (CRLF)
        assert record.media_type == "text/csv"
        assert record.uploaded_by is None
        event = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.DISTRIBUTION_UPLOADED.value
            )
        ).first()
        assert event is not None and event.actor_username == "cli"
        versions = set(session.scalars(select(FairEvaluation.version_uri)))
    assert f"{BASE_URI}dataset/modbus-tcp-testbed/2.1.0" in versions

    again = _load()
    assert again.exit_code == 0, again.output
    assert "modbus-tcp-testbed/2.1.0/csv: sin cambios" in again.output
    with session_factory() as session:
        assert len(session.scalars(select(FairEvaluation)).all()) == len(versions)


def test_changed_file_fails_before_writing(
    semantic_copy: Path, cli_env: DiskStorage, store: MemoryStore
) -> None:
    assert _load().exit_code == 0
    path = semantic_copy / "data" / "sintetico" / "ficheros" / "modbus-tcp-testbed"
    (path / "2.1.0" / "csv.csv").write_bytes(b"otro contenido")
    result = _load()
    assert result.exit_code == 1
    assert "otro contenido (inmutable)" in result.output


def test_file_for_unknown_distribution_fails(semantic_copy: Path, cli_env: DiskStorage) -> None:
    extra = semantic_copy / "data" / "sintetico" / "ficheros" / "modbus-tcp-testbed" / "2.1.0"
    (extra / "no-existe.csv").write_bytes(CSV)
    result = _load()
    assert result.exit_code == 1
    assert "no está descrita" in result.output
    assert not cli_env.exists("modbus-tcp-testbed/2.1.0/csv")


def test_changed_published_version_fails_without_writing(
    semantic_copy: Path, cli_env: DiskStorage, store: MemoryStore
) -> None:
    assert _load().exit_code == 0
    series = semantic_copy / "data" / "sintetico" / "modbus-tcp-testbed.ttl"
    text = series.read_text(encoding="utf-8")
    series.write_text(
        text.replace(
            "Publicación inicial con capturas PCAP y características en CSV.",
            "Publicación inicial retocada.",
        ),
        encoding="utf-8",
    )
    before = len(store.get_graph(f"{BASE_URI}dataset/modbus-tcp-testbed"))
    result = _load()
    assert result.exit_code == 1, result.output
    assert "inmutables" in result.output
    assert len(store.get_graph(f"{BASE_URI}dataset/modbus-tcp-testbed")) == before


def test_catalog_keeps_series_published_by_api(
    semantic_copy: Path, cli_env: DiskStorage, store: MemoryStore, uris: Uris
) -> None:
    ingest.ensure_in_catalog(store, uris.catalog, uris.series("prueba"))
    assert _load().exit_code == 0
    catalog = store.get_graph(uris.catalog)
    assert (URIRef(uris.catalog), DCAT.dataset, URIRef(uris.series("prueba"))) in catalog
