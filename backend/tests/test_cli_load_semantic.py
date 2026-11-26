"""Comando ``load-semantic``: carga validada e idempotente de ``SEMANTIC_DIR``.

Fase 3: además de catálogo y series, esquemas SKOS (también los auxiliares de
``data/vocab-minimo.ttl``, uno por grafo), ontologías (todas las versiones) y externas.
Salvo en una prueba, el cálculo de métricas se sustituye por uno sin Pellet para no
lanzar Java en cada carga.
"""

import shutil
from collections import Counter
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import URIRef
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from typer.testing import CliRunner

from app import cli as cli_module
from app import ingest, owl_metrics, vocab_ingest
from app.config import get_settings
from app.models import AuditAction, AuditEvent, OntologyMetricsRecord
from app.storage import DiskStorage
from app.triplestore import MemoryStore
from app.uris import DCAT, DCT
from tests.conftest import BASE_URI, FIXTURE_DATA_DIR, user_graphs

runner = CliRunner()

SCHEMES = {
    f"{BASE_URI}vocab/{slug}"
    for slug in (
        "dominio",
        "tipo-dataset",
        "it",
        "ot",
        "pqc",
        "did",
        "ia",
        "corp/organizacion",
        "corp/financiacion",
        "corp/trl",
        "corp/sectores",
    )
}
ONTOLOGY_VERSIONS = {
    f"{BASE_URI}onto/{path}"
    for path in ("itot/1.0.0", "itot/1.1.0", "itot/1.2.0", "pqcm/0.4.0", "didx/1.0.0")
}
EXPECTED_GRAPHS = {
    *SCHEMES,
    *ONTOLOGY_VERSIONS,
    f"{BASE_URI}onto/externas",
    f"{BASE_URI}catalogo",
    f"{BASE_URI}catalogo/vocabularios-sinteticos",  # decisión 50
    f"{BASE_URI}dataset/modbus-tcp-testbed",
    f"{BASE_URI}dataset/hallazgos-auditorias-intrusion",
    f"{BASE_URI}dataset/ejemplos-adversarios-vision",
}


# Ficheros sintéticos de las fixtures (copia de semantic/data/sintetico/ficheros/).
SYNTHETIC_FILES = sorted(
    path for path in (FIXTURE_DATA_DIR / "sintetico" / "ficheros").rglob("*") if path.is_file()
)


@pytest.fixture(autouse=True)
def _cli_uses_test_doubles(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
    store: MemoryStore,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(cli_module, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(cli_module, "get_store", lambda _settings: store)
    # Las fixtures traen los ficheros sintéticos (fase 4): se suben a una carpeta temporal.
    storage = DiskStorage(tmp_path / "distribuciones")
    monkeypatch.setattr(cli_module, "get_file_storage", lambda _settings: storage)
    # La app se importa (y cachea la configuración) antes de que la fixture ``semantic_dir``
    # fije SEMANTIC_DIR: sin esto, la CLI leería el semantic/ del repositorio.
    get_settings.cache_clear()
    ingest.clear_caches()


@pytest.fixture
def metric_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Métricas sin Pellet; registra cada versión calculada."""
    calls: list[str] = []

    def fake(prepared: vocab_ingest.PreparedOntology, _settings: object) -> tuple[dict, dict]:
        calls.append(prepared.version_iri)
        metrics = owl_metrics.compute_metrics(prepared.graph, prepared.uri)
        return metrics.to_dict(), owl_metrics.Consistency(detail="prueba").to_dict()

    monkeypatch.setattr(vocab_ingest, "compute_ontology_metrics", fake)
    return calls


def _use_semantic_dir(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setenv("SEMANTIC_DIR", str(path))
    get_settings.cache_clear()
    ingest.clear_caches()


def test_load_semantic_loads_everything(
    store: MemoryStore, session_factory: sessionmaker[Session], metric_calls: list[str]
) -> None:
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    assert user_graphs(store) == EXPECTED_GRAPHS
    assert f"{BASE_URI}vocab/" not in user_graphs(store)  # cada esquema en su grafo
    # Decisión 49: el catálogo «sintetico» sale de data/catalogos/sintetico.ttl, con sus
    # tres series, y el raíz lo agrupa sin listar series.
    sintetico = f"{BASE_URI}catalogo/sintetico"
    catalog = store.get_graph(sintetico)
    titles = {str(t) for t in catalog.objects(URIRef(sintetico), DCT.title)}
    assert titles == {"Datasets sintéticos de demostración"}
    assert len(set(catalog.objects(URIRef(sintetico), DCAT.dataset))) == 3
    root = store.get_graph(f"{BASE_URI}catalogo")
    vocab_catalog = f"{BASE_URI}catalogo/vocabularios-sinteticos"
    assert set(root.objects(URIRef(f"{BASE_URI}catalogo"), DCAT.catalog)) == {
        URIRef(sintetico),
        URIRef(vocab_catalog),
    }
    assert not list(root.objects(URIRef(f"{BASE_URI}catalogo"), DCAT.dataset))
    # Decisión 50: los nueve esquemas y las tres ontologías, en «vocabularios-sinteticos»
    # (en el grafo del catálogo, no en el del esquema ni en el de la versión).
    resources = {
        str(r) for r in store.get_graph(vocab_catalog).objects(URIRef(vocab_catalog), DCAT.resource)
    }
    expected_resources = {
        uri for uri in SCHEMES if not uri.endswith(("/vocab/dominio", "/vocab/tipo-dataset"))
    } | {uri.rsplit("/", 1)[0] for uri in ONTOLOGY_VERSIONS}
    assert resources == expected_resources
    assert len(resources) == 12
    for graph_uri in (*SCHEMES, *ONTOLOGY_VERSIONS):
        assert not list(store.get_graph(graph_uri).triples((None, DCAT.resource, None)))
    assert "modbus-tcp-testbed.ttl" in result.output
    assert "versiones 1.0.0, 2.0.0, 2.1.0" in result.output
    assert "data/vocab-minimo.ttl (dominio)" in result.output
    assert sorted(metric_calls) == sorted(ONTOLOGY_VERSIONS)
    with session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))
        records = {r.version_iri: r for r in session.scalars(select(OntologyMetricsRecord))}
    actions = Counter(e.action for e in events)
    assert actions == {
        AuditAction.DATASET_PUBLISHED: 3,
        AuditAction.SCHEME_PUBLISHED: len(SCHEMES),
        AuditAction.ONTOLOGY_PUBLISHED: len(ONTOLOGY_VERSIONS),
        AuditAction.DISTRIBUTION_UPLOADED: len(SYNTHETIC_FILES),
    }
    assert {e.actor_username for e in events} == {"cli"}
    assert {e.details["via"] for e in events} == {"cli"}
    assert set(records) == ONTOLOGY_VERSIONS
    assert records[f"{BASE_URI}onto/itot/1.2.0"].metrics["classes"] > 0


def test_load_semantic_is_idempotent(store: MemoryStore, metric_calls: list[str]) -> None:
    runner.invoke(cli_module.cli, ["load-semantic"])
    snapshot = {name: len(store.get_graph(name)) for name in user_graphs(store)}
    metric_calls.clear()
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    # + 1: el catálogo «sintetico» (decisión 49), que user_graphs no cuenta porque la
    # fixture ``store`` lo siembra.
    assert result.output.count("sin cambios") == len(EXPECTED_GRAPHS) + 1 + len(SYNTHETIC_FILES)
    assert result.output.count("métricas al día") == len(ONTOLOGY_VERSIONS)
    assert metric_calls == []  # el contenido no ha cambiado: no se recalcula
    assert {name: len(store.get_graph(name)) for name in user_graphs(store)} == snapshot


@pytest.mark.skipif(not owl_metrics.java_available(), reason="Pellet necesita Java")
def test_load_semantic_runs_pellet(session_factory: sessionmaker[Session]) -> None:
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 0, result.output
    with session_factory() as session:
        records = list(session.scalars(select(OntologyMetricsRecord)))
    assert len(records) == len(ONTOLOGY_VERSIONS)
    assert {r.consistency["reasoner"] for r in records} == {"Pellet"}
    assert {r.consistency["consistent"] for r in records} == {True}


@pytest.mark.usefixtures("metric_calls")
def test_loaded_data_is_served_by_the_api(client: TestClient) -> None:
    runner.invoke(cli_module.cli, ["load-semantic"])
    body = client.get("/datasets").json()
    assert body["total"] == 3
    assert {c["domain"]["slug"] for c in body["items"]} == {"ot", "it", "ia"}
    assert {c["domain"]["label"] for c in body["items"]} == {
        "OT / ICS",
        "Seguridad IT",
        "IA adversaria",
    }
    counts = client.get("/vocabularies").json()["counts"]
    assert counts == {"own": 3, "external": 3, "skos_corp": 4, "skos_domain": 5}
    assert client.get("/ontologies/itot").json()["metrics"]["classes"] > 0


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("ontologias/itot/1.2.0.ttl", "ontologias/itot/9.9.9.ttl"),
        ("ontologias/itot/1.2.0.ttl", "ontologias/otra/1.2.0.ttl"),
        ("vocabularios/ot.ttl", "vocabularios/otro.ttl"),
        ("vocabularios/ot.ttl", "vocabularios/corp/ot.ttl"),
    ],
)
def test_file_path_must_match_uri(
    store: MemoryStore,
    semantic_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    target: str,
) -> None:
    broken = tmp_path / "semantic"
    shutil.copytree(semantic_dir, broken)
    (broken / target).parent.mkdir(parents=True, exist_ok=True)
    (broken / source).rename(broken / target)
    _use_semantic_dir(monkeypatch, broken)
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 1
    assert target in result.output
    assert user_graphs(store) == set()


def test_duplicate_scheme_aborts(
    store: MemoryStore, semantic_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vocabularios/dominio.ttl repetiría un esquema que ya está en data/vocab-minimo.ttl."""
    broken = tmp_path / "semantic"
    shutil.copytree(semantic_dir, broken)
    text = (broken / "data" / "vocab-minimo.ttl").read_text(encoding="utf-8")
    (broken / "vocabularios" / "dominio.ttl").write_text(text, encoding="utf-8")
    _use_semantic_dir(monkeypatch, broken)
    result = runner.invoke(cli_module.cli, ["load-semantic"])
    assert result.exit_code == 1
    assert user_graphs(store) == set()


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
    assert user_graphs(store) == set()


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
