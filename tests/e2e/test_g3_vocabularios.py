"""Puerta G3 · «vocabularios cargados», de extremo a extremo sobre Docker Compose.

Recorre el criterio de la puerta con el Compose real: ``load-semantic`` carga los 22
ficheros de ``semantic/`` (esquemas SKOS, ontologías propias con todas sus versiones,
ontologías externas, catálogo y series); ``/vocabularies`` da los recuentos y filtra; la
ficha de ``itot`` trae métricas de owlready2 y la consistencia de Pellet (el de verdad: la
imagen lleva Java); las versiones antiguas, el árbol SKOS y los conceptos con sus usos se
sirven; las URIs persistentes redirigen (303) al frontend; un editor publica una ontología
y un esquema, y lo que no cumple las formas SHACL se rechaza; el dominio de los datasets
sale del ``dct:subject`` del esquema de sus temas, y las descargas llevan
``Content-Disposition``.

Comparte el entorno de ``conftest.py`` con G1 y G2 y se ejecuta después de ellas. Crea sus
propias cuentas. Cómo lanzarla: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import json
import re
import secrets
import urllib.parse

import pytest
from conftest import (
    E2E_CATALOG,
    REPO_ROOT,
    Account,
    Response,
    Stack,
    create_account,
    fuseki_logged,
    fuseki_probe_url,
    http,
    wait_for_http,
)

SEMANTIC = REPO_ROOT / "semantic"
INVALID_DIR = SEMANTIC / "examples" / "invalid" / "ontologias-vocabularios"
TURTLE = {"Content-Type": "text/turtle"}
JSONLD = {"Content-Type": "application/ld+json"}
HTML = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}  # un navegador

DOMAIN_SCHEMES = {"it": "it", "ot": "ot", "pqc": "pqc", "did": "pqc", "ia": "ia"}
CORP_SCHEMES = ["financiacion", "organizacion", "sectores", "trl"]
ONTOLOGY_VERSIONS = {
    "itot": ["1.2.0", "1.1.0", "1.0.0"],
    "pqcm": ["0.4.0"],
    "didx": ["1.0.0"],
}
EXTERNAL = {
    "https://saref.etsi.org/core/",
    "http://www.w3.org/ns/sosa/",
    "http://d3fend.mitre.org/ontologies/d3fend.owl",
}
DOMAIN_LABELS = {
    "it": "Seguridad IT",
    "ot": "OT / ICS",
    "pqc": "PQC e identidad",
    "ia": "IA adversaria",
}
# Muestras inválidas que la API rechaza con 403 not_managed y no con 422 (decisión 50).
NOT_MANAGED_SAMPLES = {"esquema-auxiliar-en-catalogo.ttl"}
SAFE_DISPOSITION = r'attachment; filename="[a-z0-9]+(?:[.-][a-z0-9]+)*\.(?:ttl|jsonld|rdf)"'


# --- Utilidades ------------------------------------------------------------------------


def _base(stack: Stack) -> str:
    return stack.env["BASE_URI"]


def _sparql(stack: Stack, query: str) -> list[dict]:
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/sparql",
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return response.json()["results"]["bindings"]  # type: ignore[index]


def _graphs(stack: Stack) -> dict[str, int]:
    rows = _sparql(stack, "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")
    return {row["g"]["value"]: int(row["n"]["value"]) for row in rows}


def _load_semantic(stack: Stack) -> tuple[int, str]:
    result = stack.compose(
        "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=900
    )
    return result.returncode, result.stdout + result.stderr


def _events(stack: Stack, *actions: str) -> list[dict]:
    # Los nombres de acción son constantes de la propia prueba, no entrada externa.
    assert all(re.fullmatch(r"[a-z_]+", action) for action in actions)
    quoted = ", ".join(f"'{action}'" for action in actions)
    sql = "select row_to_json(a) from audit_events a where a.action in (%s) order by a.id"
    return [json.loads(line) for line in stack.psql(sql % quoted)]


def _metric_rows(stack: Stack) -> dict[str, dict]:
    rows = [
        json.loads(line)
        for line in stack.psql(
            "select row_to_json(m) from ontology_metrics m order by m.version_iri"
        )
    ]
    return {row["version_iri"]: row for row in rows}


def _get(stack: Stack, path: str, **kwargs: object) -> Response:
    return http("GET", f"{stack.api}{path}", **kwargs)  # type: ignore[arg-type]


def _json(stack: Stack, path: str) -> dict:
    response = _get(stack, path)
    assert response.status == 200, f"{path}: {response.status} {response.text[:300]}"
    return response.json()  # type: ignore[return-value]


def _vocabularies(stack: Stack, **params: str) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    return _json(stack, f"/vocabularies{query}")


def _post(
    stack: Stack,
    path: str,
    body: str | bytes,
    token: str | None,
    headers: dict[str, str] = TURTLE,
    *,
    catalog: bool = True,
) -> Response:
    """``POST`` de RDF. Desde la decisión 50, un esquema o una ontología pertenece a un
    catálogo: por defecto se publica en el de las pruebas (``?catalog=``); con
    ``catalog=False`` el RDF se envía tal cual."""
    raw = body.encode() if isinstance(body, str) else body
    if catalog and path in ("/schemes", "/ontologies"):
        path = f"{path}?catalog={E2E_CATALOG}"
    return http("POST", f"{stack.api}{path}", raw_body=raw, headers=headers, token=token)


def _ontology_ttl(slug: str, version: str = "1.0.0", *, body: str = "", prior: str = "") -> str:
    """Versión mínima de ontología que cumple las formas, marcada como sintética.

    Los textos son de relleno de la prueba, no datos del prototipo ni reales."""
    previous = f"owl:priorVersion <onto/{slug}/{prior}> ;" if prior else ""
    return f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
@prefix : <onto/{slug}#> .
<onto/{slug}> a owl:Ontology ;
    owl:versionIRI <onto/{slug}/{version}> ; owl:versionInfo "{version}" ; {previous}
    dct:type <vocab/tipo-dataset/sintetico> ;
    adms:status <http://purl.org/adms/status/UnderDevelopment> ;
    dct:title "Ontología de la prueba {slug}"@es ;
    dct:description "Ontología creada por la prueba de extremo a extremo de G3."@es ;
    vann:preferredNamespacePrefix "{slug}" ; vann:preferredNamespaceUri <onto/{slug}#> .
:Activo a owl:Class ; rdfs:comment "Clase de relleno de la prueba."@es .
:Sensor a owl:Class ; rdfs:subClassOf :Activo .
:mide a owl:ObjectProperty ; rdfs:domain :Sensor ; rdfs:range :Activo .
{body}
"""


def _scheme_ttl(uri: str, *, prefix: str, domain: str | None = None, body: str = "") -> str:
    """Esquema SKOS mínimo que cumple las formas, marcado como sintético."""
    subject = f"dct:subject <vocab/dominio/{domain}> ;" if domain else ""
    return f"""
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
<{uri}> a skos:ConceptScheme ; {subject}
    dct:type <vocab/tipo-dataset/sintetico> ;
    skos:prefLabel "Esquema de la prueba {prefix}"@es ;
    dct:title "Esquema de la prueba {prefix}"@es ;
    dct:description "Esquema creado por la prueba de extremo a extremo de G3."@es ;
    owl:versionInfo "1.0" ; adms:status <http://purl.org/adms/status/Completed> ;
    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <{uri}/> ;
    skos:hasTopConcept <{uri}/raiz> .
<{uri}/raiz> a skos:Concept ; skos:inScheme <{uri}> ; skos:topConceptOf <{uri}> ;
    skos:prefLabel "Raíz"@es , "Root"@en ; skos:altLabel "Tronco"@es .
<{uri}/hoja> a skos:Concept ; skos:inScheme <{uri}> ; skos:broader <{uri}/raiz> ;
    skos:prefLabel "Hoja"@es .
{body}
"""


def _series_ttl(slug: str, theme: str) -> str:
    return f"""
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
<catalogo/e2e-pruebas> dcat:dataset <dataset/{slug}> .
<dataset/{slug}> a dcat:DatasetSeries ;
    dct:type <vocab/tipo-dataset/sintetico> ;
    dct:title "Serie de la prueba {slug}"@es ;
    dct:description "Serie creada por la prueba de extremo a extremo de G3."@es ;
    dcat:last <dataset/{slug}/1.0.0> .
<dataset/{slug}/1.0.0> a dcat:Dataset ;
    dct:type <vocab/tipo-dataset/sintetico> ;
    dct:title "Serie de la prueba {slug}"@es ;
    dct:description "Serie creada por la prueba de extremo a extremo de G3."@es ;
    dcat:version "1.0.0" ;
    dcat:inSeries <dataset/{slug}> ;
    dct:accessRights <http://publications.europa.eu/resource/authority/access-right/PUBLIC> ;
    dcat:theme <{theme}> ;
    dcat:distribution <dataset/{slug}/1.0.0/csv> .
<dataset/{slug}/1.0.0/csv> a dcat:Distribution ;
    dct:title "CSV"@es ;
    dcat:mediaType <http://www.iana.org/assignments/media-types/text/csv> ;
    dcat:accessURL <dataset/{slug}/1.0.0/csv> .
"""


def _walk(nodes: list[dict]) -> list[dict]:
    found = []
    for node in nodes:
        found.append(node)
        found.extend(_walk(node["children"]))
    return found


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def g3_editor(stack: Stack, admin: Account, e2e_catalog: str) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def g3_member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def loaded(stack: Stack) -> str:
    """Ejecuta ``load-semantic`` y devuelve su salida. Si G2 ya lo ha ejecutado, todo sale
    «sin cambios»; las líneas ``fichero -> <grafo>`` son las mismas."""
    code, output = _load_semantic(stack)
    assert code == 0, f"load-semantic falló:\n{output}"
    return output


@pytest.fixture(scope="module")
def baseline(stack: Stack, loaded: str) -> dict:
    """Recuentos de ``/vocabularies`` antes de que esta prueba publique nada."""
    return _vocabularies(stack)


@pytest.fixture(scope="module")
def published_ontology(stack: Stack, baseline: dict, g3_editor: Account) -> dict:
    """Un editor publica una ontología con ``owl:imports`` que apunta al Fuseki del propio
    entorno: si el backend o Pellet lo descargaran, quedaría en el log de Fuseki."""
    slug = f"e2e{secrets.token_hex(4)}"
    probe = f"qa-g3-import-{secrets.token_hex(6)}"
    remote = fuseki_probe_url(stack, probe)
    body = _ontology_ttl(slug, body=f"<onto/{slug}> owl:imports <{remote}> .")
    response = _post(stack, "/ontologies", body, g3_editor.token)
    assert response.status == 201, response.text
    return {
        "slug": slug,
        "probe": probe,
        "remote": remote,
        "body": body,
        "result": response.json(),
    }


@pytest.fixture(scope="module")
def published_scheme(stack: Stack, baseline: dict, g3_editor: Account) -> dict:
    slug = f"e2e{secrets.token_hex(4)}"
    body = _scheme_ttl(f"vocab/{slug}", prefix=slug, domain="it")
    response = _post(stack, "/schemes", body, g3_editor.token)
    assert response.status == 201, response.text
    return {"slug": slug, "body": body, "result": response.json()}


# --- 1. Entorno de la fase 3 -----------------------------------------------------------


def test_la_imagen_del_backend_lleva_java_para_pellet(stack: Stack) -> None:
    result = stack.compose("exec", "-T", "backend", "java", "-version")
    assert result.returncode == 0, result.stderr
    version = re.search(r'version "(\d+)', result.stdout + result.stderr)
    assert version and int(version.group(1)) >= 25, result.stderr
    # El backend (y por tanto el proceso Java de Pellet) no se ejecuta como root.
    uid = stack.compose("exec", "-T", "backend", "id", "-u")
    assert uid.returncode == 0 and uid.stdout.strip() != "0"
    check = stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "from app import owl_metrics; print(owl_metrics.java_available())",
    )
    assert check.stdout.strip() == "True", check.stdout + check.stderr


def test_las_variables_del_razonador_son_opcionales(stack: Stack) -> None:
    """``.env.example`` las deja comentadas: el backend arranca con sus valores por defecto."""
    assert "REASONER_TIMEOUT_SECONDS" not in stack.env
    assert "REASONER_JAVA_MEMORY_MB" not in stack.env
    result = stack.compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        "from app.config import get_settings as g; s = g(); "
        "print(s.reasoner_timeout_seconds, s.reasoner_java_memory_mb)",
    )
    assert result.stdout.split() == ["120.0", "1024"], result.stdout + result.stderr


def test_la_migracion_ha_creado_la_tabla_de_metricas(stack: Stack) -> None:
    tables = stack.psql("select tablename from pg_tables where schemaname = 'public'")
    assert "ontology_metrics" in tables
    # La 0004 es de la decisión 50 (prefijos VANN de esquemas y ontologías dados de baja);
    # la 0003 era de la fase 4 (ficheros, FAIR, consultas guardadas, login y SPARQL).
    assert stack.psql("select version_num from alembic_version") == ["0004"]
    assert "withdrawn_prefixes" in tables


# --- 2. load-semantic ------------------------------------------------------------------


def _expected_graphs(base: str) -> dict[str, str]:
    """``fichero (relativo a semantic/) -> grafo`` de los 22 ficheros (23 grafos)."""
    expected = {
        **{f"vocabularios/{slug}.ttl": f"{base}vocab/{slug}" for slug in DOMAIN_SCHEMES},
        **{f"vocabularios/corp/{slug}.ttl": f"{base}vocab/corp/{slug}" for slug in CORP_SCHEMES},
        "data/vocab-minimo.ttl (dominio)": f"{base}vocab/dominio",
        "data/vocab-minimo.ttl (tipo-dataset)": f"{base}vocab/tipo-dataset",
        "ontologias/externas.ttl": f"{base}onto/externas",
        "data/catalogo.ttl": f"{base}catalogo",
        "data/catalogos/sintetico.ttl": f"{base}catalogo/sintetico",  # decisión 49
        # decisión 50: el catálogo de los esquemas y las ontologías sintéticos
        "data/catalogos/vocabularios-sinteticos.ttl": f"{base}catalogo/vocabularios-sinteticos",
    }
    for slug, versions in ONTOLOGY_VERSIONS.items():
        for version in versions:
            expected[f"ontologias/{slug}/{version}.ttl"] = f"{base}onto/{slug}/{version}"
    for path in sorted((SEMANTIC / "data" / "sintetico").glob("*.ttl")):
        expected[f"data/sintetico/{path.name}"] = f"{base}dataset/{path.stem}"
    return expected


def test_load_semantic_carga_las_veintidos_piezas(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    expected = _expected_graphs(base)
    assert len(expected) == 23
    assert len({name.split(" (")[0] for name in expected}) == 22
    # Los 22 ficheros existen en semantic/ (lo que se monta en el backend).
    for name in expected:
        assert (SEMANTIC / name.split(" (")[0]).is_file(), name
    lines = [line for line in loaded.splitlines() if " -> <" in line]
    assert len(lines) == 23, loaded
    for name, graph in expected.items():
        assert any(line.startswith(f"{name} -> <{graph}>") for line in lines), f"{name}\n{loaded}"
    graphs = _graphs(stack)
    assert set(expected.values()) <= set(graphs)
    assert all(graphs[graph] > 0 for graph in expected.values())
    for secret in stack.sensitive.values():
        assert secret not in loaded


def test_load_semantic_calcula_las_metricas_de_cada_version(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    rows = _metric_rows(stack)
    versions = {
        f"{base}onto/{slug}/{version}"
        for slug, numbers in ONTOLOGY_VERSIONS.items()
        for version in numbers
    }
    assert versions <= set(rows)
    for iri in versions:
        row = rows[iri]
        assert row["ontology_iri"] == iri.rsplit("/", 1)[0]
        assert re.fullmatch(r"[0-9a-f]{64}", row["content_hash"])
        assert "owlready2" in row["tool"] and "Pellet" in row["tool"]
        # Pellet se ha ejecutado de verdad dentro del contenedor.
        assert row["consistency"]["reasoner"] == "Pellet"
        assert row["consistency"]["consistent"] is True, f"{iri}: {row['consistency']}"
        assert row["consistency"]["detail"] is None


def test_load_semantic_es_idempotente_y_no_recalcula_metricas(stack: Stack, loaded: str) -> None:
    before = _graphs(stack)
    computed = {iri: row["computed_at"] for iri, row in _metric_rows(stack).items()}
    code, output = _load_semantic(stack)
    assert code == 0, output
    lines = [line for line in output.splitlines() if " -> <" in line]
    assert len(lines) == 23, output
    assert all("sin cambios" in line for line in lines), output
    ontology_lines = [
        line for line in lines if line.startswith("ontologias/") and "externas" not in line
    ]
    assert len(ontology_lines) == 5
    assert all("métricas al día" in line for line in ontology_lines), output
    assert _graphs(stack) == before
    assert {iri: row["computed_at"] for iri, row in _metric_rows(stack).items()} == computed


def test_load_semantic_queda_en_la_auditoria(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    events = [
        e
        for e in _events(stack, "ontology_published", "scheme_published")
        if e["details"]["via"] == "cli"
    ]
    assert all(e["actor_id"] is None and e["actor_username"] == "cli" for e in events)
    created = [e for e in events if e["details"]["created"]]
    ontologies = {
        e["details"]["version_iri"] for e in created if e["action"] == "ontology_published"
    }
    schemes = {e["details"]["scheme"] for e in created if e["action"] == "scheme_published"}
    assert ontologies == {
        f"{base}onto/{slug}/{version}"
        for slug, numbers in ONTOLOGY_VERSIONS.items()
        for version in numbers
    }
    assert schemes == {
        *(f"{base}vocab/{slug}" for slug in (*DOMAIN_SCHEMES, "dominio", "tipo-dataset")),
        *(f"{base}vocab/corp/{slug}" for slug in CORP_SCHEMES),
    }
    for event in created:
        assert event["details"]["graph"] in (
            event["details"].get("version_iri"),
            event["details"].get("scheme"),
        )


# --- 3. /vocabularies -------------------------------------------------------------------


def test_los_recuentos_de_vocabularios(stack: Stack, baseline: dict) -> None:
    assert baseline["counts"] == {
        "own": 3,
        "external": 3,
        "skos_corp": 4,
        "skos_domain": 5,
    }
    assert baseline["total"] == 15 and len(baseline["items"]) == 15
    base = _base(stack)
    by_kind: dict[str, list[dict]] = {}
    for card in baseline["items"]:
        by_kind.setdefault(card["kind"], []).append(card)

    own = {card["slug"]: card for card in by_kind["own"]}
    assert set(own) == set(ONTOLOGY_VERSIONS)
    for slug, card in own.items():
        assert card["uri"] == f"{base}onto/{slug}"
        assert card["rdf_type"] == "owl:Ontology"
        assert card["version"] == ONTOLOGY_VERSIONS[slug][0]
        assert card["prefix"] == slug
        assert card["namespace"] == f"{base}onto/{slug}#"
        assert card["title"] and card["description"]
        assert card["metrics"]["classes"] > 0
        assert card["synthetic"] is True, f"{slug} no lleva la marca de sintético"
        assert card["domain"] is None and card["concepts"] is None

    external = {card["uri"]: card for card in by_kind["external"]}
    assert set(external) == EXTERNAL
    for card in external.values():
        assert card["status"] == "referenced"
        assert card["slug"] is None and card["metrics"] is None
        assert card["synthetic"] is False  # las externas son reales
        assert not card["uri"].startswith(base)

    corp = {card["slug"]: card for card in by_kind["skos_corp"]}
    assert sorted(corp) == CORP_SCHEMES
    for slug, card in corp.items():
        assert card["uri"] == f"{base}vocab/corp/{slug}"
        assert card["rdf_type"] == "skos:ConceptScheme"
        assert card["domain"] is None
        assert card["synthetic"] is True
    # Los que el prototipo no enumera («[N] conceptos») no llevan conceptos inventados.
    assert corp["trl"]["concepts"] == 9 and corp["financiacion"]["concepts"] > 0
    assert corp["organizacion"]["concepts"] == 0 and corp["sectores"]["concepts"] == 0

    domain = {card["slug"]: card for card in by_kind["skos_domain"]}
    assert set(domain) == set(DOMAIN_SCHEMES)
    for slug, card in domain.items():
        assert card["uri"] == f"{base}vocab/{slug}"
        expected = DOMAIN_SCHEMES[slug]
        assert card["domain"] == {
            "slug": expected,
            "uri": f"{base}vocab/dominio/{expected}",
            "label": DOMAIN_LABELS[expected],
        }
        assert card["concepts"] > 0 and card["synthetic"] is True
    # Los esquemas auxiliares no tienen tarjeta.
    assert {"dominio", "tipo-dataset"} & {card["slug"] for card in baseline["items"]} == set()
    # Ningún placeholder del prototipo ni dato personal en las tarjetas.
    assert not re.search(r"\[[A-ZÁÉÍÓÚÑ ]+\]", json.dumps(baseline, ensure_ascii=False))
    assert {card["status"] for card in baseline["items"]} <= {
        "published",
        "draft",
        "referenced",
    }


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"kind": "own"}, {"itot", "pqcm", "didx"}),
        ({"kind": "skos_corp"}, set(CORP_SCHEMES)),
        ({"kind": "skos_domain"}, set(DOMAIN_SCHEMES)),
        ({"domain": "pqc"}, {"pqc", "did"}),
        ({"domain": "ot"}, {"ot"}),
        ({"domain": "it"}, {"it"}),
        ({"domain": "ia"}, {"ia"}),
        ({"domain": "pqc", "kind": "skos_domain"}, {"pqc", "did"}),
        ({"domain": "pqc", "kind": "own"}, set()),
        ({"domain": "ot", "kind": "skos_corp"}, set()),
        ({"q": "pqcm"}, {"pqcm"}),
        ({"q": "PQCM", "kind": "own"}, {"pqcm"}),
        # Fase 4 (decisión 30): `q` busca en la URI sin BASE_URI y ya no en el espacio de
        # nombres (`onto/itot#`, el de vann:preferredNamespaceUri).
        ({"q": "onto/itot"}, {"itot"}),
        ({"q": "onto/itot#"}, set()),
        ({"q": "vocab/corp/trl"}, {"trl"}),
        ({"q": "no-existe-este-texto"}, set()),
        ({"q": '" } UNION { GRAPH ?g { ?s ?p ?o } } #'}, set()),
    ],
)
def test_los_filtros_de_vocabularios(
    stack: Stack, baseline: dict, params: dict[str, str], expected: set[str]
) -> None:
    page = _vocabularies(stack, **params)
    known = {*ONTOLOGY_VERSIONS, *DOMAIN_SCHEMES, *CORP_SCHEMES}
    assert {card["slug"] for card in page["items"] if card["slug"] in known} == expected
    # Los recuentos son de todo el repositorio, no del filtro.
    assert page["counts"]["external"] == 3


def test_el_filtro_de_ontologias_externas(stack: Stack, baseline: dict) -> None:
    page = _vocabularies(stack, kind="external")
    assert {card["uri"] for card in page["items"]} == EXTERNAL
    assert [c["uri"] for c in _vocabularies(stack, q="sosa")["items"]] == [
        "http://www.w3.org/ns/sosa/"
    ]
    assert _vocabularies(stack, kind="external", domain="ot")["items"] == []


def test_vocabularios_valida_sus_parametros(stack: Stack, baseline: dict) -> None:
    for query in (
        "kind=otro",
        "kind=OWN",
        "domain=did",
        "domain=dominio",
        f"q={'a' * 201}",
    ):
        assert _get(stack, f"/vocabularies?{query}").status == 422, query
    allowed = _get(stack, "/vocabularies", headers={"Origin": stack.frontend_origin})
    assert allowed.headers.get("access-control-allow-origin") == stack.frontend_origin
    other = _get(stack, "/vocabularies", headers={"Origin": "http://127.0.0.1:1"})
    assert "access-control-allow-origin" not in other.headers


# --- 4. Ficha de ontología --------------------------------------------------------------


def test_la_ficha_de_itot_trae_metricas_y_consistencia_de_pellet(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    detail = _json(stack, "/ontologies/itot")
    assert detail["slug"] == "itot" and detail["kind"] == "own"
    assert detail["uri"] == f"{base}onto/itot"
    assert detail["synthetic"] is True
    assert detail["status"] == "published"
    assert detail["title"] and detail["description"]

    metrics = detail["metrics"]
    assert metrics["classes"] == 13
    # Decisión 38: la ontología solo lleva la jerarquía que cita el prototipo, sin
    # propiedades, comentarios ni alineamientos propuestos.
    assert metrics["object_properties"] == 0 and metrics["data_properties"] == 0
    assert metrics["logical_axioms"] == 8
    assert detail["documentation"]["percent"] == 0
    assert detail["alignments"] == []
    assert metrics["imports"] == 2
    assert metrics["dl_expressivity"] is None  # no se calcula: no se inventa
    assert detail["profile"]["name"] in ("OWL 2 DL", "OWL 2 Full")
    assert detail["profile"]["approximate"] is True

    consistency = detail["consistency"]
    assert consistency["reasoner"] == "Pellet"
    assert consistency["consistent"] is True
    assert consistency["unsatisfiable_classes"] == 0 and consistency["unsatisfiable"] == []
    assert consistency["detail"] is None
    assert consistency["includes_imports"] is False
    assert "owlready2" in detail["metrics_tool"] and "Pellet" in detail["metrics_tool"]
    assert detail["metrics_computed_at"]
    documentation = detail["documentation"]
    assert (
        documentation["total"]
        == metrics["classes"] + metrics["object_properties"] + metrics["data_properties"]
    )
    assert 0 <= documentation["percent"] <= 100

    versioning = detail["versioning"]
    assert versioning["version"] == versioning["current_version"] == "1.2.0"
    assert versioning["version_iri"] == f"{base}onto/itot/1.2.0"
    assert versioning["prior_version"] == {
        "version_iri": f"{base}onto/itot/1.1.0",
        "version": "1.1.0",
    }
    assert [v["version"] for v in versioning["backward_compatible_with"]] == ["1.1.0"]
    assert [v["version"] for v in versioning["history"]] == ONTOLOGY_VERSIONS["itot"]
    assert [v["current"] for v in versioning["history"]] == [True, False, False]
    assert all(v["described"] for v in versioning["history"])

    # Los imports se declaran y se enlazan con las externas, pero no se descargan.
    imports = {i["uri"]: i for i in detail["imports"]}
    assert set(imports) == {
        "http://www.w3.org/ns/sosa/",
        "https://saref.etsi.org/core/",
    }
    assert all(i["known"] and i["title"] for i in imports.values())
    assert detail["metadata"]["prefix"] == "itot"
    assert detail["metadata"]["namespace"] == f"{base}onto/itot#"
    # Uso en el catálogo: la versión 2.1.0 de Modbus declara dct:conformsTo itot 1.2.0.
    (use,) = [u for u in detail["used_by_datasets"] if u["slug"] == "modbus-tcp-testbed"]
    assert [v["conforms_to"] for v in use["versions"]] == [f"{base}onto/itot/1.2.0"]
    # Conceptos SKOS que usa la ontología (dct:subject), con su esquema.
    assert detail["subjects"]
    for subject in detail["subjects"]:
        assert subject["type"] == "concept" and subject["label"]
        assert subject["scheme"]["slug"] in DOMAIN_SCHEMES
    # Placeholders del prototipo sin valor real: llegan vacíos, no inventados.
    assert detail["metadata"]["license"] is None
    assert detail["metadata"]["issued"] is None
    assert not re.search(r"\[[A-ZÁÉÍÓÚÑ ]+\]", json.dumps(detail, ensure_ascii=False))


def test_las_versiones_antiguas_de_una_ontologia_tienen_ficha(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    classes = {}
    for version in ONTOLOGY_VERSIONS["itot"]:
        detail = _json(stack, f"/ontologies/itot?version={version}")
        assert detail["versioning"]["version"] == version
        assert detail["versioning"]["version_iri"] == f"{base}onto/itot/{version}"
        assert detail["versioning"]["current_version"] == "1.2.0"
        assert detail["metrics"] is not None, f"la versión {version} no tiene métricas"
        assert detail["consistency"]["consistent"] is True
        classes[version] = detail["metrics"]["classes"]
        rdf = _get(stack, f"/ontologies/itot/rdf?format=turtle&version={version}")
        assert rdf.status == 200
        assert f'"{version}"' in rdf.text
        for other in ONTOLOGY_VERSIONS["itot"]:
            if other != version:
                assert f'owl:versionInfo "{other}"' not in rdf.text
    assert classes["1.2.0"] == 13
    first = _json(stack, "/ontologies/itot?version=1.0.0")
    assert first["versioning"]["prior_version"] is None
    for slug in ("pqcm", "didx"):
        other = _json(stack, f"/ontologies/{slug}")
        assert other["versioning"]["version"] == ONTOLOGY_VERSIONS[slug][0]
        assert other["metrics"]["classes"] > 0
        assert other["consistency"]["consistent"] is True


def test_ontologias_y_versiones_que_no_existen(stack: Stack, loaded: str) -> None:
    for path, status in (
        ("/ontologies/no-existe", 404),
        ("/ontologies/itot?version=9.9.9", 404),
        ("/ontologies/itot/rdf?version=9.9.9", 404),
        (
            "/ontologies/externas",
            404,
        ),  # el grafo de las externas no es una ontología propia
        ("/ontologies/ot", 404),  # un esquema no es una ontología
        ("/ontologies/itot?version=1.2", 422),
        ("/ontologies/Itot", 422),
        ("/ontologies/itot%0A", 422),
        ("/ontologies/itot/rdf?format=nt", 422),
    ):
        assert _get(stack, path).status == status, path


def test_rdf_de_una_ontologia_en_los_tres_formatos(stack: Stack, loaded: str) -> None:
    url = "/ontologies/itot/rdf"
    for fmt, media in (
        ("turtle", "text/turtle"),
        ("jsonld", "application/ld+json"),
        ("rdfxml", "application/rdf+xml"),
    ):
        response = _get(stack, f"{url}?format={fmt}")
        assert response.status == 200, fmt
        assert response.headers["content-type"].startswith(media), fmt
        assert "onto/itot" in response.text
        negotiated = _get(stack, url, headers={"Accept": media})
        assert negotiated.headers["content-type"].startswith(media), media
        assert "Accept" in negotiated.headers.get("vary", "")
    assert json.loads(_get(stack, f"{url}?format=jsonld").text)
    assert _get(stack, f"{url}?format=rdfxml").text.lstrip().startswith("<?xml")
    assert _get(stack, url, headers={"Accept": "text/csv"}).status == 406


# --- 5. Navegador SKOS ------------------------------------------------------------------


def test_el_arbol_del_esquema_ot(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    scheme = _json(stack, "/schemes/ot")
    assert scheme["slug"] == "ot" and scheme["corp"] is False and scheme["kind"] == "skos_domain"
    assert scheme["uri"] == f"{base}vocab/ot"
    assert scheme["domain"] == {
        "slug": "ot",
        "uri": f"{base}vocab/dominio/ot",
        "label": DOMAIN_LABELS["ot"],
    }
    assert scheme["version"] == "1.0" and scheme["synthetic"] is True
    assert scheme["responsible"] is None  # [RESPONSABLE]: placeholder, decisión 11
    nodes = _walk(scheme["tree"])
    assert len(nodes) == scheme["concept_count"] > 0
    assert len({n["uri"] for n in nodes}) == len(nodes)
    assert all(n["top_concept"] for n in scheme["tree"])
    assert any(n["children"] for n in scheme["tree"]), "el árbol no tiene jerarquía"
    for node in nodes:
        assert node["uri"] == f"{base}vocab/ot/{node['slug']}"
        assert node["label"]
    modbus = next(n for n in nodes if n["slug"] == "modbus-tcp")
    assert modbus["label"] == "Modbus/TCP"
    assert {"value": "Modbus TCP/IP", "lang": "es"} in modbus["alt_labels"]
    # Cada concepto del árbol tiene su detalle.
    for node in nodes:
        concept = _json(stack, f"/schemes/ot/concepts/{node['slug']}")
        assert concept["uri"] == node["uri"]
        assert concept["scheme"]["slug"] == "ot"
        assert concept["top_concept"] == node["top_concept"]
        assert {c["uri"] for c in concept["narrower"]} == {c["uri"] for c in node["children"]}


def test_el_concepto_modbus_tcp_con_sus_usos(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    concept = _json(stack, "/schemes/ot/concepts/modbus-tcp")
    assert concept["uri"] == f"{base}vocab/ot/modbus-tcp"
    assert concept["pref_label"] == "Modbus/TCP"
    assert {"es", "en"} <= {label["lang"] for label in concept["pref_labels"]}
    assert {"value": "Modbus TCP/IP", "lang": "es"} in concept["alt_labels"]
    assert concept["scheme"] == {
        "uri": f"{base}vocab/ot",
        "slug": "ot",
        "corp": False,
        "label": concept["scheme"]["label"],
    }
    assert concept["broader"], "el prototipo muestra un concepto más general"
    for ref in concept["broader"] + concept["narrower"] + concept["related"]:
        assert ref["label"], ref["uri"]
    # Recursos que usan este concepto.
    (dataset,) = [d for d in concept["used_by"]["datasets"] if d["slug"] == "modbus-tcp-testbed"]
    assert dataset["uri"] == f"{base}dataset/modbus-tcp-testbed"
    assert dataset["title"]
    assert "2.1.0" in [v["version"] for v in dataset["versions"]]
    assert "itot" in [o["slug"] for o in concept["used_by"]["ontologies"]]
    # Mapeos externos: los que el prototipo no detalla no se inventan ([QID]…).
    for mapping in concept["exact_match"] + concept["close_match"]:
        assert mapping.startswith(("http://", "https://")), mapping
    assert not any("[" in m for m in concept["exact_match"] + concept["close_match"])


def test_los_esquemas_corporativos(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    trl = _json(stack, "/schemes/corp/trl")
    assert trl["corp"] is True and trl["kind"] == "skos_corp"
    assert trl["uri"] == f"{base}vocab/corp/trl"
    assert trl["domain"] is None
    assert trl["responsible"] is None
    assert trl["concept_count"] == 9
    assert sorted(n["slug"] for n in _walk(trl["tree"])) == [f"trl-{n}" for n in range(1, 10)]
    concept = _json(stack, "/schemes/corp/trl/concepts/trl-1")
    assert concept["uri"] == f"{base}vocab/corp/trl/trl-1"
    assert concept["scheme"]["corp"] is True
    assert concept["definition"] is None  # el prototipo no la reproduce: no se inventa
    for slug in CORP_SCHEMES:
        scheme = _json(stack, f"/schemes/corp/{slug}")
        assert scheme["concept_count"] == len(_walk(scheme["tree"]))
    # Un esquema corporativo no se sirve como de dominio, ni al revés.
    for path in (
        "/schemes/trl",
        "/schemes/corp/ot",
        "/schemes/corp",
        "/schemes/no-existe",
        "/schemes/ot/concepts/no-existe",
        "/schemes/corp/trl/concepts/modbus-tcp",
        "/schemes/itot",
    ):
        assert _get(stack, path).status == 404, path
    assert _get(stack, "/schemes/OT").status == 422
    assert _get(stack, "/schemes/ot/concepts/Modbus_TCP").status == 422


def test_rdf_de_un_esquema_y_de_un_concepto(stack: Stack, loaded: str) -> None:
    for fmt, media in (
        ("turtle", "text/turtle"),
        ("jsonld", "application/ld+json"),
        ("rdfxml", "application/rdf+xml"),
    ):
        for path in ("/schemes/ot/rdf", "/schemes/corp/trl/rdf"):
            response = _get(stack, f"{path}?format={fmt}")
            assert response.status == 200, path
            assert response.headers["content-type"].startswith(media), path
    whole = _get(stack, "/vocab/ot", headers={"Accept": "text/turtle"}).text
    one = _get(stack, "/vocab/ot/modbus-tcp", headers={"Accept": "text/turtle"}).text
    assert "Modbus/TCP" in whole and "Modbus/TCP" in one
    assert "IEEE 1815" in whole and "IEEE 1815" not in one  # solo el concepto pedido


# --- 6. URIs persistentes ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "location"),
    [
        ("/onto/itot", "/ontologias/itot"),
        ("/onto/itot/1.2.0", "/ontologias/itot?version=1.2.0"),
        ("/onto/itot/1.0.0", "/ontologias/itot?version=1.0.0"),
        ("/onto/pqcm", "/ontologias/pqcm"),
        ("/vocab/ot", "/vocabularios/ot"),
        ("/vocab/did", "/vocabularios/did"),
        ("/vocab/corp/trl", "/vocabularios/corp/trl"),
        ("/vocab/ot/modbus-tcp", "/vocabularios/ot?concepto=modbus-tcp"),
        ("/vocab/corp/trl/trl-1", "/vocabularios/corp/trl?concepto=trl-1"),
        # Esquema auxiliar: la URI de dominio que la API devuelve en cada dataset.
        ("/vocab/dominio", "/vocabularios/dominio"),
        ("/vocab/dominio/ot", "/vocabularios/dominio?concepto=ot"),
    ],
)
def test_las_uris_persistentes_redirigen_303_al_frontend(
    stack: Stack, loaded: str, path: str, location: str
) -> None:
    frontend = stack.env["FRONTEND_BASE_URL"]
    response = _get(stack, path, headers=HTML, follow_redirects=False)
    assert response.status == 303, f"{path}: {response.status}"
    assert response.headers["location"] == f"{frontend}{location}"
    assert "Accept" in response.headers.get("vary", "")
    # El destino existe: el frontend sirve la aplicación en esa ruta.
    target = response.headers["location"].replace("http://localhost:", "http://127.0.0.1:")
    page = wait_for_http(target)
    assert page.status == 200, target
    assert '<div id="root">' in page.text


def test_las_uris_persistentes_sirven_rdf_por_negociacion(stack: Stack, loaded: str) -> None:
    for path in (
        "/onto/itot",
        "/onto/itot/1.1.0",
        "/vocab/ot",
        "/vocab/corp/trl",
        "/vocab/ot/modbus-tcp",
    ):
        # Fase 4 (decisión 31): sin Accept o con */* ya no sale Turtle, sino un 303 al HTML.
        for accept in (None, "*/*"):
            see_other = _get(
                stack,
                path,
                headers={"Accept": accept} if accept else {},
                follow_redirects=False,
            )
            assert see_other.status == 303, f"{path} {accept}"
            assert see_other.headers["location"].startswith(stack.frontend_origin + "/")
        for accept, media in (
            ("text/turtle", "text/turtle"),
            ("application/ld+json", "application/ld+json"),
            ("application/rdf+xml", "application/rdf+xml"),
        ):
            response = _get(stack, path, headers={"Accept": accept})
            assert response.status == 200, f"{path} {accept}"
            assert response.headers["content-type"].startswith(media), f"{path} {accept}"
        assert _get(stack, path, headers={"Accept": "image/png"}).status == 406, path
    # La URI de la ontología sirve la versión actual; la de una versión, esa versión.
    current = _get(stack, "/onto/itot", headers={"Accept": "text/turtle"}).text
    old = _get(stack, "/onto/itot/1.0.0", headers={"Accept": "text/turtle"}).text
    assert 'owl:versionInfo "1.2.0"' in current and 'owl:versionInfo "1.0.0"' in old
    assert 'owl:versionInfo "1.2.0"' not in old


def test_las_uris_persistentes_que_no_existen_dan_404(stack: Stack, loaded: str) -> None:
    for path in (
        "/onto/no-existe",
        "/onto/itot/9.9.9",
        "/onto/externas",
        "/vocab/no-existe",
        "/vocab/corp/no-existe",
        "/vocab/ot/no-existe",
        "/vocab/corp/trl/no-existe",
        "/vocab/corp",
    ):
        for headers in (HTML, {"Accept": "text/turtle"}):
            response = _get(stack, path, headers=headers, follow_redirects=False)
            assert response.status == 404, f"{path} {headers}"


def test_el_frontend_sirve_las_pantallas_de_la_fase_3(stack: Stack, loaded: str) -> None:
    """Solo comprueba que el frontend sirve la aplicación en esas rutas: el contenido lo
    pinta el navegador (ver «Lo que esta prueba no cubre» en el README)."""
    for path in (
        "/vocabularios",
        "/ontologias/itot",
        "/ontologias/itot?version=1.0.0",
        "/vocabularios/ot",
        "/vocabularios/ot?concepto=modbus-tcp",
        "/vocabularios/corp/trl",
    ):
        page = wait_for_http(f"{stack.frontend}{path}")
        assert page.status == 200, path
        assert '<div id="root">' in page.text


# --- 7. Publicación por la API ----------------------------------------------------------


def test_solo_editor_y_admin_publican_vocabularios(
    stack: Stack, baseline: dict, g3_member: Account
) -> None:
    before = _graphs(stack)
    events = len(_events(stack, "ontology_published", "scheme_published"))
    slug = f"e2edenegado{secrets.token_hex(3)}"
    bodies = {
        "/ontologies": _ontology_ttl(slug),
        "/schemes": _scheme_ttl(f"vocab/{slug}", prefix=slug),
    }
    for path, body in bodies.items():
        assert _post(stack, path, body, None).status == 401, path
        assert _post(stack, path, body, "no-es-un-token").status == 401, path
        assert _post(stack, path, body, g3_member.token).status == 403, path
    assert _graphs(stack) == before
    assert len(_events(stack, "ontology_published", "scheme_published")) == events
    assert _get(stack, f"/ontologies/{slug}").status == 404
    assert _get(stack, f"/schemes/{slug}").status == 404


def test_un_editor_publica_una_ontologia_con_metricas_de_pellet(
    stack: Stack, published_ontology: dict, g3_editor: Account, baseline: dict
) -> None:
    base = _base(stack)
    slug, result = published_ontology["slug"], published_ontology["result"]
    version_iri = f"{base}onto/{slug}/1.0.0"
    assert result["slug"] == slug and result["version"] == "1.0.0"
    assert result["uri"] == f"{base}onto/{slug}"
    assert result["version_iri"] == result["graph"] == version_iri
    assert (result["created"], result["changed"], result["metrics_recomputed"]) == (
        True,
        True,
        True,
    )
    assert result["metrics"]["classes"] == 2
    assert result["metrics"]["object_properties"] == 1
    assert result["metrics"]["imports"] == 1
    # Pellet real, dentro del contenedor.
    assert result["consistency"] == {
        "reasoner": "Pellet",
        "consistent": True,
        "unsatisfiable_classes": 0,
        "unsatisfiable": [],
        "detail": None,
        "includes_imports": False,
    }
    assert result["documentation"]["classes_documented"] == 1

    # En el triplestore (su grafo es el versionIRI) y en PostgreSQL.
    assert _graphs(stack)[version_iri] == result["triples"]
    assert version_iri in _metric_rows(stack)
    # En el listado y en la ficha.
    page = _vocabularies(stack)
    assert page["counts"]["own"] == baseline["counts"]["own"] + 1
    card = next(c for c in page["items"] if c["slug"] == slug)
    assert card["kind"] == "own" and card["status"] == "draft" and card["version"] == "1.0.0"
    assert card["metrics"] == {"classes": 2, "properties": 1}
    assert card["synthetic"] is True
    assert [c["slug"] for c in _vocabularies(stack, q=slug)["items"]] == [slug]
    detail = _json(stack, f"/ontologies/{slug}")
    assert detail["consistency"]["consistent"] is True
    assert [i["uri"] for i in detail["imports"]] == [published_ontology["remote"]]
    assert detail["imports"][0]["known"] is False
    redirect = _get(stack, f"/onto/{slug}", headers=HTML, follow_redirects=False)
    assert redirect.status == 303
    assert redirect.headers["location"] == f"{stack.env['FRONTEND_BASE_URL']}/ontologias/{slug}"
    # En la auditoría, con el editor como actor.
    (event,) = [e for e in _events(stack, "ontology_published") if e["details"]["slug"] == slug]
    assert event["actor_username"] == g3_editor.username and event["actor_id"] == g3_editor.id
    assert event["details"]["via"] == "api" and event["details"]["created"] is True
    assert event["details"]["consistent"] is True


def test_los_imports_de_una_ontologia_no_se_descargan(
    stack: Stack, published_ontology: dict
) -> None:
    """Ni owlready2 ni Pellet han pedido el ``owl:imports``: el destino era el Fuseki del
    entorno, que registra cada petición en su log."""
    assert not fuseki_logged(stack, published_ontology["probe"])
    # Control: la misma consulta, lanzada desde la prueba, sí queda registrada.
    control = f"qa-g3-control-{secrets.token_hex(6)}"
    http("GET", fuseki_probe_url(stack, control, from_host=True))
    assert fuseki_logged(stack, control), "el log de Fuseki no registra las consultas"


def test_republicar_una_ontologia_y_publicar_una_version_nueva(
    stack: Stack, published_ontology: dict, g3_editor: Account, admin: Account
) -> None:
    base = _base(stack)
    slug = published_ontology["slug"]
    computed = _metric_rows(stack)[f"{base}onto/{slug}/1.0.0"]["computed_at"]
    same = _post(stack, "/ontologies", published_ontology["body"], g3_editor.token)
    assert same.status == 200, same.text
    result = same.json()
    assert (result["created"], result["changed"], result["metrics_recomputed"]) == (
        False,
        False,
        False,
    )
    assert result["consistency"]["consistent"] is True
    assert _metric_rows(stack)[f"{base}onto/{slug}/1.0.0"]["computed_at"] == computed

    # El admin hereda los permisos de editor y publica la versión siguiente.
    newer = _ontology_ttl(slug, "1.1.0", prior="1.0.0", body=":Actuador a owl:Class .")
    created = _post(stack, "/ontologies", newer, admin.token)
    assert created.status == 201, created.text
    assert created.json()["metrics"]["classes"] == 3
    detail = _json(stack, f"/ontologies/{slug}")
    assert detail["versioning"]["current_version"] == "1.1.0"
    assert [v["version"] for v in detail["versioning"]["history"]] == ["1.1.0", "1.0.0"]
    assert detail["versioning"]["prior_version"]["version"] == "1.0.0"
    old = _json(stack, f"/ontologies/{slug}?version=1.0.0")
    assert old["metrics"]["classes"] == 2
    # Cada versión en su grafo: publicar la 1.1.0 no toca la 1.0.0.
    graphs = _graphs(stack)
    assert f"{base}onto/{slug}/1.0.0" in graphs and f"{base}onto/{slug}/1.1.0" in graphs
    events = [e for e in _events(stack, "ontology_published") if e["details"]["slug"] == slug]
    assert [e["actor_username"] for e in events] == [
        g3_editor.username,
        g3_editor.username,
        admin.username,
    ]
    assert [e["details"]["metrics_recomputed"] for e in events] == [True, False, True]


def test_una_ontologia_inconsistente_se_publica_y_se_avisa(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    slug = f"e2e{secrets.token_hex(4)}"
    body = _ontology_ttl(
        slug,
        body=":Sensor owl:disjointWith :Activo . :s1 a owl:NamedIndividual , :Sensor .",
    )
    response = _post(stack, "/ontologies", body, g3_editor.token)
    assert response.status == 201, response.text
    consistency = response.json()["consistency"]
    assert consistency["reasoner"] == "Pellet"
    assert consistency["consistent"] is False
    assert consistency["detail"]
    assert _json(stack, f"/ontologies/{slug}")["consistency"]["consistent"] is False


def test_publicar_una_ontologia_en_json_ld(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    base = _base(stack)
    slug = f"e2e{secrets.token_hex(4)}"
    text = {
        "@language": "es",
        "@value": "Ontología JSON-LD de la prueba de extremo a extremo",
    }
    document = {
        "@context": {
            "owl": "http://www.w3.org/2002/07/owl#",
            "dct": "http://purl.org/dc/terms/",
            "adms": "http://www.w3.org/ns/adms#",
            "vann": "http://purl.org/vocab/vann/",
        },
        "@graph": [
            {
                "@id": f"{base}onto/{slug}",
                "@type": "owl:Ontology",
                "owl:versionIRI": {"@id": f"{base}onto/{slug}/0.1.0"},
                "owl:versionInfo": "0.1.0",
                "dct:type": {"@id": f"{base}vocab/tipo-dataset/sintetico"},
                "adms:status": {"@id": "http://purl.org/adms/status/UnderDevelopment"},
                "dct:title": text,
                "dct:description": text,
                "vann:preferredNamespacePrefix": slug,
                "vann:preferredNamespaceUri": {"@id": f"{base}onto/{slug}#"},
            },
            {"@id": f"{base}onto/{slug}#Clase", "@type": "owl:Class"},
        ],
    }
    response = _post(stack, "/ontologies", json.dumps(document), g3_editor.token, JSONLD)
    assert response.status == 201, response.text
    assert response.json()["metrics"]["classes"] == 1
    detail = _json(stack, f"/ontologies/{slug}")
    assert detail["title"] == text["@value"] and detail["synthetic"] is True


def test_un_editor_publica_un_esquema_skos(
    stack: Stack, published_scheme: dict, g3_editor: Account, baseline: dict
) -> None:
    base = _base(stack)
    slug, result = published_scheme["slug"], published_scheme["result"]
    uri = f"{base}vocab/{slug}"
    assert result == {
        "slug": slug,
        "corp": False,
        "uri": uri,
        "graph": uri,
        "concepts": 2,
        "triples": result["triples"],
        "created": True,
        "changed": True,
        "catalog": f"{base}catalogo/{E2E_CATALOG}",  # decisión 50
    }
    assert _graphs(stack)[uri] == result["triples"]
    page = _vocabularies(stack)
    assert page["counts"]["skos_domain"] == baseline["counts"]["skos_domain"] + 1
    card = next(c for c in page["items"] if c["slug"] == slug)
    assert card["kind"] == "skos_domain" and card["concepts"] == 2
    assert card["domain"]["slug"] == "it" and card["domain"]["label"] == DOMAIN_LABELS["it"]
    assert slug in {c["slug"] for c in _vocabularies(stack, domain="it")["items"]}
    assert slug not in {c["slug"] for c in _vocabularies(stack, domain="ot")["items"]}
    scheme = _json(stack, f"/schemes/{slug}")
    (root,) = scheme["tree"]
    assert root["slug"] == "raiz" and [c["slug"] for c in root["children"]] == ["hoja"]
    assert root["alt_labels"] == [{"value": "Tronco", "lang": "es"}]
    leaf = _json(stack, f"/schemes/{slug}/concepts/hoja")
    assert [b["slug"] if "slug" in b else b["uri"] for b in leaf["broader"]] == [f"{uri}/raiz"]
    redirect = _get(stack, f"/vocab/{slug}/hoja", headers=HTML, follow_redirects=False)
    assert redirect.status == 303
    assert redirect.headers["location"] == (
        f"{stack.env['FRONTEND_BASE_URL']}/vocabularios/{slug}?concepto=hoja"
    )
    (event,) = [e for e in _events(stack, "scheme_published") if e["details"]["slug"] == slug]
    assert event["actor_username"] == g3_editor.username
    assert event["details"]["via"] == "api" and event["details"]["concepts"] == 2

    same = _post(stack, "/schemes", published_scheme["body"], g3_editor.token)
    assert same.status == 200
    assert (same.json()["created"], same.json()["changed"]) == (False, False)


def test_un_editor_publica_un_esquema_corporativo(
    stack: Stack, baseline: dict, admin: Account
) -> None:
    base = _base(stack)
    slug = f"e2e{secrets.token_hex(4)}"
    body = _scheme_ttl(f"vocab/corp/{slug}", prefix=slug)
    response = _post(stack, "/schemes", body, admin.token)
    assert response.status == 201, response.text
    assert response.json()["corp"] is True
    assert response.json()["graph"] == f"{base}vocab/corp/{slug}"
    card = next(c for c in _vocabularies(stack, kind="skos_corp")["items"] if c["slug"] == slug)
    assert card["domain"] is None
    assert _json(stack, f"/schemes/corp/{slug}")["concept_count"] == 2
    assert _get(stack, f"/schemes/{slug}").status == 404


# --- 8. Rechazos de la ingesta ----------------------------------------------------------


def test_lo_que_no_cumple_shacl_se_rechaza_con_422(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    before = _graphs(stack)
    events = len(_events(stack, "ontology_published", "scheme_published"))
    metrics = set(_metric_rows(stack))
    base = _base(stack)
    examples = sorted(INVALID_DIR.glob("*.ttl"))
    assert len(examples) >= 19
    for path in examples:
        endpoint = "/ontologies" if path.name.startswith("ontologia-") else "/schemes"
        # Tal cual, sin ?catalog=: es lo que valida validate.py (decisión 50).
        response = _post(stack, endpoint, path.read_bytes(), g3_editor.token, catalog=False)
        if path.name in NOT_MANAGED_SAMPLES:  # decisión 50, regla 12: 403, no 422
            assert response.status == 403, f"{path.name}: {response.status} {response.text[:300]}"
            assert response.json()["kind"] == "not_managed", path.name
            continue
        assert response.status == 422, f"{path.name}: {response.status} {response.text[:300]}"
        body = response.json()
        assert body["kind"] in ("shacl", "uri", "structure", "catalog"), path.name
        if body["kind"] == "shacl":
            assert body["issues"] and body["report"], path.name
            expected = set(
                re.findall(r"# expect-violation: (\S+)", path.read_text(encoding="utf-8"))
            )
            shapes = {issue["source_shape"] for issue in body["issues"]}
            assert {f"{base}shapes#{name}" for name in expected} <= shapes, path.name

    # Un ejemplo concreto, con su informe.
    sample = (INVALID_DIR / "esquema-sin-version.ttl").read_bytes()
    report = _post(stack, "/schemes", sample, g3_editor.token, catalog=False).json()
    assert report["kind"] == "shacl"
    assert f"{base}shapes#ConceptScheme-version" in {i["source_shape"] for i in report["issues"]}

    # Nada se ha escrito, calculado ni auditado.
    assert _graphs(stack) == before
    assert len(_events(stack, "ontology_published", "scheme_published")) == events
    assert set(_metric_rows(stack)) == metrics


def test_la_ingesta_no_escribe_fuera_de_su_grafo(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    before = _graphs(stack)
    slug = f"e2eintruso{secrets.token_hex(3)}"
    label = 'rdfs:label "Secuestrada"@es'
    for subject in (
        "onto/itot",
        "onto/itot/1.2.0",
        "onto/itot#Controlador",
        "onto/externas",
        "vocab/ot",
        "vocab/ot/modbus-tcp",
        "vocab/dominio/ot",
        "catalogo",
        "dataset/modbus-tcp-testbed",
    ):
        response = _post(
            stack,
            "/ontologies",
            _ontology_ttl(slug, body=f"<{subject}> {label} ."),
            g3_editor.token,
        )
        assert response.status == 422, subject
        assert response.json()["kind"] == "uri", subject
        hijack = '<http://www.w3.org/2004/02/skos/core#prefLabel> "Secuestrada"@es'
        response = _post(
            stack,
            "/schemes",
            _scheme_ttl(f"vocab/{slug}", prefix=slug, body=f"<{subject}> {hijack} ."),
            g3_editor.token,
        )
        assert response.status == 422, subject
        assert response.json()["kind"] == "uri", subject
    # Slugs reservados y versiones incoherentes.
    for body in (
        _ontology_ttl("externas"),
        _ontology_ttl(slug, "1.0"),
        _ontology_ttl(slug).replace(f"<onto/{slug}/1.0.0>", "<onto/itot/9.9.9>"),
        _ontology_ttl(slug, "2.0.0", prior="3.0.0"),
    ):
        assert _post(stack, "/ontologies", body, g3_editor.token).status == 422
    # 'corp' no es un slug (422); los esquemas auxiliares solo los carga load-semantic y
    # la API no los gestiona (decisión 50, regla 12: 403 not_managed).
    rejected = _post(stack, "/schemes", _scheme_ttl("vocab/corp", prefix=slug), g3_editor.token)
    assert rejected.status == 422 and rejected.json()["kind"] == "uri"
    for uri in ("vocab/dominio", "vocab/tipo-dataset"):
        rejected = _post(stack, "/schemes", _scheme_ttl(uri, prefix=slug), g3_editor.token)
        assert rejected.status == 403, uri
        assert rejected.json()["kind"] == "not_managed", uri
    assert _graphs(stack) == before
    for path in (
        "/ontologies/itot",
        "/schemes/ot",
        "/schemes/ot/concepts/modbus-tcp",
        "/datasets",
    ):
        assert "Secuestrada" not in _get(stack, path).text, path
    assert _get(stack, f"/ontologies/{slug}").status == 404
    assert _get(stack, f"/schemes/{slug}").status == 404


def test_la_ingesta_rechaza_sintaxis_tipos_y_xml(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    before = _graphs(stack)
    token = g3_editor.token
    slug = f"e2eraro{secrets.token_hex(3)}"
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">&x;</rdf:RDF>'
    )
    for path, body in (
        ("/ontologies", _ontology_ttl(slug)),
        ("/schemes", _scheme_ttl(f"vocab/{slug}", prefix=slug)),
    ):
        assert _post(stack, path, "esto no es turtle <", token).status == 422
        assert _post(stack, path, "DROP ALL", token).status == 422
        assert _post(stack, path, body, token, JSONLD).status == 422
        for content_type in (
            "application/rdf+xml",
            "application/xml",
            "text/plain",
            "application/sparql-update",
        ):
            for payload in (body, xxe):
                response = _post(stack, path, payload, token, {"Content-Type": content_type})
                assert response.status == 415, f"{path} {content_type}"
                assert "root:" not in response.text
        assert _post(stack, path, xxe, token).status == 422
        # Contexto JSON-LD remoto: se rechaza sin salir a buscarlo.
        probe = f"qa-g3-ctx-{secrets.token_hex(6)}"
        remote = {"@context": fuseki_probe_url(stack, probe), "@id": f"onto/{slug}"}
        response = _post(stack, path, json.dumps(remote), token, JSONLD)
        assert response.status == 422
        assert not fuseki_logged(stack, probe)
    assert _graphs(stack) == before


def test_la_ingesta_tiene_limites_de_expansion_y_profundidad(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    """Un prefijo muy largo repetido (bomba de expansión) y una jerarquía desmesurada se
    rechazan con 422 sin tumbar el servicio."""
    before = _graphs(stack)
    slug = f"e2elimite{secrets.token_hex(3)}"
    prefix = "http://x.example/" + "a" * 100_000 + "/"
    bomb = f"@prefix p: <{prefix}> .\n" + "\n".join(f"p:s{i} p:p p:o{i} ." for i in range(200))
    for path in ("/ontologies", "/schemes", "/datasets"):
        response = _post(stack, path, bomb, g3_editor.token)
        assert response.status == 422, f"{path}: {response.status}"
        assert response.json()["kind"] == "limit", path
    chain = "\n".join(
        f"<vocab/{slug}/c{i}> a skos:Concept ; skos:inScheme <vocab/{slug}> ; "
        f'skos:broader <vocab/{slug}/c{i - 1}> ; skos:prefLabel "c{i}"@es .'
        for i in range(1, 300)
    )
    deep = _scheme_ttl(f"vocab/{slug}", prefix=slug, body=chain.replace("/c0>", "/raiz>"))
    assert _post(stack, "/schemes", deep, g3_editor.token).status == 422
    assert _graphs(stack) == before
    assert http("GET", f"{stack.api}/health/ready").status == 200


def test_los_esquemas_auxiliares_se_sirven_como_tales(stack: Stack, loaded: str) -> None:
    base = _base(stack)
    for slug in ("dominio", "tipo-dataset"):
        scheme = _json(stack, f"/schemes/{slug}")
        assert scheme["kind"] == "auxiliary" and scheme["domain"] is None
        assert scheme["uri"] == f"{base}vocab/{slug}"
    assert sorted(n["slug"] for n in _walk(_json(stack, "/schemes/dominio")["tree"])) == [
        "ia",
        "it",
        "ot",
        "pqc",
    ]


def test_la_uri_de_dominio_de_un_dataset_lleva_al_esquema_auxiliar(
    stack: Stack, loaded: str
) -> None:
    """QA-G3-13: la ``uri`` de dominio de un dataset se puede seguir hasta el Navegador SKOS:
    303 al frontend, y la API da el esquema auxiliar y el concepto que esa pantalla pide."""
    base = _base(stack)
    (domain,) = _json(stack, "/datasets/modbus-tcp-testbed")["domains"]
    assert domain["uri"] == f"{base}vocab/dominio/ot"
    path = "/" + domain["uri"].removeprefix(base)
    redirect = _get(stack, path, headers=HTML, follow_redirects=False)
    assert redirect.status == 303
    location = urllib.parse.urlsplit(redirect.headers["location"])
    assert location.path == "/vocabularios/dominio"
    assert urllib.parse.parse_qs(location.query) == {"concepto": ["ot"]}
    page = wait_for_http(f"{stack.frontend}{location.path}?{location.query}")
    assert page.status == 200 and '<div id="root">' in page.text
    # Lo que pide la pantalla: el esquema (kind auxiliary) y el concepto.
    scheme = _json(stack, "/schemes/dominio")
    assert scheme["kind"] == "auxiliary" and scheme["concept_count"] == 4
    concept = _json(stack, "/schemes/dominio/concepts/ot")
    assert concept["uri"] == domain["uri"]
    assert concept["pref_label"] == domain["label"] == "OT / ICS"
    assert concept["scheme"]["slug"] == "dominio"
    rdf = _get(stack, path, headers={"Accept": "text/turtle"})
    assert rdf.status == 200 and "OT / ICS" in rdf.text


# --- 9. Dominio de los datasets ---------------------------------------------------------


def test_el_dominio_de_los_datasets_sale_del_esquema_de_sus_temas(
    stack: Stack, loaded: str
) -> None:
    base = _base(stack)
    expected = {
        "modbus-tcp-testbed": "ot",
        "hallazgos-auditorias-intrusion": "it",
        "ejemplos-adversarios-vision": "ia",
    }
    items = {item["slug"]: item for item in _json(stack, "/datasets?page_size=100")["items"]}
    for slug, domain in expected.items():
        card = items[slug]
        assert card["domains"] == [
            {
                "slug": domain,
                "uri": f"{base}vocab/dominio/{domain}",
                "label": DOMAIN_LABELS[domain],
            }
        ], slug
        detail = _json(stack, f"/datasets/{slug}")
        assert detail["domains"] == card["domains"], slug
        found = {
            i["slug"] for i in _json(stack, f"/datasets?domain={domain}&page_size=100")["items"]
        }
        assert slug in found
    # La ficha de Modbus muestra «OT / ICS»: la etiqueta del dominio, no la del esquema.
    modbus = _json(stack, "/datasets/modbus-tcp-testbed")
    assert [d["label"] for d in modbus["domains"]] == ["OT / ICS"]
    assert _json(stack, "/schemes/ot")["title"] != "OT / ICS"
    themes = {theme["uri"]: theme for theme in modbus["version"]["metadata"]["themes"]}
    assert themes[f"{base}vocab/ot/modbus-tcp"]["label"] == "Modbus/TCP"


def test_un_tema_del_esquema_did_da_el_dominio_pqc(
    stack: Stack, baseline: dict, g3_editor: Account
) -> None:
    """``vocab/did`` declara ``dct:subject vocab/dominio/pqc``: un dataset con un tema de
    ese esquema es del dominio «PQC e identidad», aunque el esquema no se llame ``pqc``."""
    base = _base(stack)
    slug = f"e2e-did-{secrets.token_hex(3)}"
    response = _post(
        stack,
        "/datasets",
        _series_ttl(slug, "vocab/did/credencial-verificable"),
        g3_editor.token,
    )
    assert response.status == 201, response.text
    detail = _json(stack, f"/datasets/{slug}")
    assert detail["domains"] == [
        {
            "slug": "pqc",
            "uri": f"{base}vocab/dominio/pqc",
            "label": DOMAIN_LABELS["pqc"],
        }
    ]
    assert slug in {i["slug"] for i in _json(stack, "/datasets?domain=pqc&page_size=100")["items"]}
    assert slug not in {
        i["slug"] for i in _json(stack, "/datasets?domain=it&page_size=100")["items"]
    }
    concept = _json(stack, "/schemes/did/concepts/credencial-verificable")
    assert slug in [d["slug"] for d in concept["used_by"]["datasets"]]


def test_un_tema_de_un_esquema_publicado_por_la_api_da_su_dominio(
    stack: Stack, published_scheme: dict, g3_editor: Account
) -> None:
    scheme = published_scheme["slug"]
    slug = f"e2e-tema-{secrets.token_hex(3)}"
    response = _post(stack, "/datasets", _series_ttl(slug, f"vocab/{scheme}/hoja"), g3_editor.token)
    assert response.status == 201, response.text
    detail = _json(stack, f"/datasets/{slug}")
    assert [d["slug"] for d in detail["domains"]] == ["it"]
    assert detail["version"]["metadata"]["themes"][0]["label"] == "Hoja"
    concept = _json(stack, f"/schemes/{scheme}/concepts/hoja")
    assert [d["slug"] for d in concept["used_by"]["datasets"]] == [slug]


# --- 10. Descargas ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "name", "formats"),
    [
        ("/ontologies/itot/rdf", "itot-1.2.0", ("turtle", "jsonld", "rdfxml")),
        ("/ontologies/itot/rdf?version=1.0.0", "itot-1.0.0", ("turtle", "rdfxml")),
        ("/schemes/ot/rdf", "ot-1.0", ("turtle", "jsonld", "rdfxml")),
        ("/schemes/corp/trl/rdf", "corp-trl-1.0", ("turtle", "jsonld", "rdfxml")),
        ("/schemes/corp/financiacion/rdf", "corp-financiacion-2026.1", ("turtle",)),
        (
            "/datasets/modbus-tcp-testbed/rdf",
            "modbus-tcp-testbed-2.1.0",
            ("turtle", "jsonld"),
        ),
    ],
)
def test_la_descarga_lleva_content_disposition(
    stack: Stack, loaded: str, path: str, name: str, formats: tuple[str, ...]
) -> None:
    extension = {"turtle": "ttl", "jsonld": "jsonld", "rdfxml": "rdf"}
    sep = "&" if "?" in path else "?"
    for fmt in formats:
        inline = _get(stack, f"{path}{sep}format={fmt}")
        assert inline.status == 200
        assert "content-disposition" not in inline.headers
        for flag in ("1", "true"):
            response = _get(stack, f"{path}{sep}format={fmt}&download={flag}")
            assert response.status == 200
            header = response.headers["content-disposition"]
            assert header == f'attachment; filename="{name}.{extension[fmt]}"'
            assert re.fullmatch(SAFE_DISPOSITION, header)
            assert response.headers["content-type"] == inline.headers["content-type"]
            assert len(response.text) == len(inline.text) > 0
    assert _get(stack, f"{path}{sep}download=quizas").status == 422
    # El navegador puede leer la descarga desde el origen del frontend.
    cors = _get(stack, f"{path}{sep}download=1", headers={"Origin": stack.frontend_origin})
    assert cors.headers.get("access-control-allow-origin") == stack.frontend_origin


# --- 11. Cierre -------------------------------------------------------------------------


def test_la_auditoria_y_los_logs_de_la_fase_3_no_contienen_secretos(
    stack: Stack, published_ontology: dict, published_scheme: dict
) -> None:
    dump = "\n".join(stack.psql("select row_to_json(a) from audit_events a order by a.id"))
    metrics = "\n".join(stack.psql("select row_to_json(m) from ontology_metrics m"))
    result = stack.compose("logs", "--no-color", "--no-log-prefix", timeout=120)
    assert result.returncode == 0, result.stderr
    logs = result.stdout + result.stderr
    assert dump and metrics and logs.strip()
    for name, secret in stack.sensitive.items():
        assert secret not in dump, f"audit_events contiene {name}"
        assert secret not in metrics, f"ontology_metrics contiene {name}"
        assert secret not in logs, f"los logs contienen {name}"
    # Las métricas guardadas no llevan rutas del contenedor ni trazas de Java.
    for leak in ("/tmp/", "/opt/venv", "site-packages", ".java:", "Traceback"):
        assert leak not in metrics, leak


def test_la_api_de_vocabularios_no_expone_credenciales(
    stack: Stack, published_ontology: dict
) -> None:
    password = stack.env["FUSEKI_ADMIN_PASSWORD"]
    for path in (
        "/openapi.json",
        "/vocabularies",
        "/ontologies/itot",
        f"/ontologies/{published_ontology['slug']}",
        "/schemes/ot",
        "/schemes/ot/concepts/modbus-tcp",
    ):
        response = _get(stack, path)
        assert response.status == 200, path
        for secret in (
            password,
            stack.env["JWT_SECRET"],
            stack.env["POSTGRES_PASSWORD"],
        ):
            assert secret not in response.text, path


def test_fuseki_sigue_sin_admitir_escrituras_anonimas_tras_la_fase_3(
    stack: Stack, published_scheme: dict
) -> None:
    base = _base(stack)
    endpoint = f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}"
    before = _graphs(stack)
    for graph in (f"{base}onto/itot/1.2.0", f"{base}vocab/ot", f"{base}vocab/dominio"):
        quoted = urllib.parse.quote(graph, safe="")
        assert http("DELETE", f"{endpoint}/data?graph={quoted}").status == 401
        put = http(
            "PUT",
            f"{endpoint}/data?graph={quoted}",
            raw_body=b"<urn:qa:s> <urn:qa:p> <urn:qa:o> .",
            headers=TURTLE,
        )
        assert put.status == 401
        drop = http("POST", f"{endpoint}/update", form={"update": f"DROP GRAPH <{graph}>"})
        assert drop.status == 401
    assert _graphs(stack) == before


def test_no_quedan_procesos_de_pellet_y_el_entorno_sigue_sano(stack: Stack) -> None:
    processes = stack.compose(
        "exec", "-T", "backend", "sh", "-c", "cat /proc/[0-9]*/cmdline | tr '\\0' ' '"
    )
    assert processes.returncode == 0, processes.stderr
    assert "pellet.Pellet" not in processes.stdout
    ready = http("GET", f"{stack.api}/health/ready")
    assert ready.status == 200, ready.text
    restarts = stack.compose("ps", "--all", "--format", "{{.Service}} {{.Status}}").stdout
    assert "Restarting" not in restarts
    assert "unhealthy" not in restarts
