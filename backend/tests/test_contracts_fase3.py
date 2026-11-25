"""Coherencia de los contratos entre capas en la fase 3 (agente ``qa``).

- ``backend`` -> ``frontend``: tipos, enumerados, rutas y parámetros de
  ``frontend/src/api`` frente a ``backend/openapi.json``, y las rutas del frontend a las
  que redirigen (303) las URIs persistentes.
- ``semantico`` -> ``backend``: los ficheros de ``semantic/`` frente a lo que carga
  ``load-semantic`` (20 ficheros, 21 grafos) y frente a ``semantic/uris.md``.
- ``infra`` -> ``backend``: variables del razonador en ``.env.example`` frente a
  ``Settings`` y Compose, y la versión de Java de la imagen y de CI.
- Etiquetas de Git: ``semantic/uris.md``, ``infra/scripts/publicar.py`` y
  ``.github/workflows/publicar.yml`` hablan de las mismas etiquetas y ficheros.

Las pruebas de la fase 2 (``test_contracts_fase2.py``) siguen vigentes. Cada prueba se
salta si la carpeta de la otra capa no está (p. ej. dentro de la imagen Docker del
backend). Los defectos abiertos van con ``xfail(strict=True)`` y su identificador
(hoy, ninguno).
"""

import importlib.util
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF
from sqlalchemy.orm import Session

from app import cli, ingest, owl_metrics, uris, vocab_ingest
from app.config import Settings, get_settings
from app.export_openapi import OPENAPI_PATH
from app.uris import SKOS, Uris
from tests.conftest import BASE_URI, REPO_SEMANTIC_DIR
from tests.test_contracts_fase2 import (
    ENV_EXAMPLE,
    FRONTEND_TYPES,
    REPO_ROOT,
    _compose_backend_environment,
    _require,
    _settings_env_names,
    _typescript_properties,
    _typescript_source,
)

FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
URIS_MD = REPO_SEMANTIC_DIR / "uris.md"
PUBLICAR_PY = REPO_ROOT / "infra" / "scripts" / "publicar.py"
PUBLICAR_YML = REPO_ROOT / ".github" / "workflows" / "publicar.yml"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
COMPOSE = REPO_ROOT / "docker-compose.yml"


def _contract() -> dict[str, Any]:
    return json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))


# --- backend -> frontend ----------------------------------------------------------------

PHASE_3_INTERFACES = {
    "VocabularyCard",
    "VocabularyCounts",
    "VocabularyPage",
    "MetricsSummary",
    "OntologyDetail",
    "OntologyMetadata",
    "OntologyVersioning",
    "OntologyVersionSummary",
    "OntologyVersionRef",
    "OntologyMetricsRead",
    "OwlProfile",
    "ConsistencyRead",
    "DocumentationCoverageRead",
    "ImportRef",
    "Alignment",
    "AlignmentMapping",
    "DatasetUse",
    "DatasetVersionUse",
    "OntologyUse",
    "SubjectRef",
    "SchemeRef",
    "SchemeDetail",
    "SchemeMetadata",
    "ConceptNode",
    "ConceptDetail",
    "ConceptRef",
    "ConceptUsage",
    "LangLiteral",
}


def test_frontend_declares_every_phase_3_read_schema() -> None:
    """Todo esquema que devuelve una lectura de la fase 3 tiene su interfaz. (Los
    resultados de la ingesta no: el frontend no publica.)"""
    interfaces = set(_typescript_properties())
    schemas = set(_contract()["components"]["schemas"])
    assert schemas >= PHASE_3_INTERFACES
    assert interfaces >= PHASE_3_INTERFACES, PHASE_3_INTERFACES - interfaces


def _aliases() -> dict[str, list[str]]:
    """``export type X = 'a' | 'b'`` -> ``{X: [a, b]}``."""
    return {
        name: re.findall(r"'([^']+)'", body)
        for name, body in re.findall(r"export type (\w+) = ([^\n]+)", _typescript_source())
    }


def _schema_enum(schema: dict[str, Any]) -> list[str] | None:
    """Valores de un enumerado (o constante) de un esquema o de los elementos de su lista."""
    if "enum" in schema:
        return list(schema["enum"])
    if "const" in schema:
        return [schema["const"]]
    if schema.get("type") == "array":
        return _schema_enum(schema["items"])
    for option in schema.get("anyOf", []):
        values = _schema_enum(option)
        if values is not None:
            return values
    return None


# Valores nuevos de un enum del contrato que el frontend todavía no tiene (el contrato
# OpenAPI cambia en su propia PR y el frontend se adapta después). Se borran cuando
# frontend/src/api/types.ts los incorpore.
PENDING_FRONTEND_VALUES: dict[tuple[str, str], set[str]] = {}


def test_frontend_literal_types_match_the_contract_enums() -> None:
    """Cada propiedad que el contrato limita a unos valores tiene en TypeScript
    exactamente esos valores (escritos en la propiedad o en un alias)."""
    aliases = _aliases()
    schemas = _contract()["components"]["schemas"]
    renamed = {
        "TokenResponse": "Token",
        "CurrentUser": "UserRead",
        "HealthResponse": "HealthStatus",
    }
    checked = 0
    for ts_name, properties in _typescript_properties().items():
        schema = schemas[renamed.get(ts_name, ts_name)]
        for prop, (ts_type, _optional) in properties.items():
            expected = _schema_enum(schema["properties"][prop])
            if expected is None:
                target = schema["properties"][prop]
                ref = target.get("$ref") or next(
                    (o["$ref"] for o in target.get("anyOf", []) if "$ref" in o), None
                )
                if ref is None or "enum" not in schemas[ref.rsplit("/", 1)[-1]]:
                    continue
                expected = schemas[ref.rsplit("/", 1)[-1]]["enum"]
            literals = re.findall(r"'([^']+)'", ts_type)
            if not literals:
                alias = re.match(r"\(?(\w+)", ts_type)
                assert alias and alias.group(1) in aliases, f"{ts_name}.{prop}: {ts_type}"
                literals = aliases[alias.group(1)]
            pending = PENDING_FRONTEND_VALUES.get((ts_name, prop), set())
            assert not pending & set(literals), f"{ts_name}.{prop}: quita {pending} de la lista"
            expected = [value for value in expected if value not in pending]
            assert sorted(literals) == sorted(expected), f"{ts_name}.{prop}"
            checked += 1
    assert checked >= 12


def test_frontend_scheme_kind_matches_the_contract() -> None:
    """QA-G3-13 (corregido): el frontend contempla ``auxiliary`` (esquemas ``vocab/dominio``
    y ``vocab/tipo-dataset``), con el tipo en la propiedad o en un alias."""
    ts_type, _optional = _typescript_properties()["SchemeDetail"]["kind"]
    expected = _contract()["components"]["schemas"]["SchemeDetail"]["properties"]["kind"]["enum"]
    literals = re.findall(r"'([^']+)'", ts_type) or _aliases()[ts_type]
    assert sorted(literals) == sorted(expected)
    assert "auxiliary" in literals


def _query_enum(path: str, parameter: str) -> list[str]:
    for item in _contract()["paths"][path]["get"]["parameters"]:
        if item["name"] == parameter:
            values = _schema_enum(item["schema"])
            assert values is not None, parameter
            return values
    raise AssertionError(f"{path} no tiene el parámetro {parameter}")


def test_frontend_enums_of_phase_3_match_the_contract() -> None:
    aliases = _aliases()
    assert aliases["VocabularyKind"] == _query_enum("/vocabularies", "kind")
    assert aliases["DomainSlug"] == _query_enum("/vocabularies", "domain")
    for path in ("/ontologies/{slug}/rdf", "/schemes/{slug}/rdf", "/schemes/corp/{slug}/rdf"):
        assert aliases["VocabRdfFormat"] == _query_enum(path, "format"), path
    # El RDF de un dataset sigue sin RDF/XML.
    assert aliases["RdfFormat"] == _query_enum("/datasets/{slug}/rdf", "format")
    assert "rdfxml" not in aliases["RdfFormat"]


def _client_calls() -> dict[str, set[str]]:
    """``{ruta de la API: {parámetros de consulta}}`` que construye ``frontend/src/api``.

    Las rutas se normalizan como en OpenAPI: cada ``${…}`` es un parámetro ``{}``."""
    source = _require(FRONTEND_SRC / "api" / "vocabularies.ts").read_text(encoding="utf-8")
    source += (FRONTEND_SRC / "api" / "datasets.ts").read_text(encoding="utf-8")
    # schemePath(slug, corp) se expande a sus dos rutas.
    assert "`/schemes/${corp ? 'corp/' : ''}${encodeURIComponent(slug)}`" in source
    calls: dict[str, set[str]] = {}
    string = r"(`[^`]*`|'[^']*')"

    def add(raw: str, names: set[str]) -> None:
        variants = [raw]
        if "${schemePath(slug, corp)}" in raw:
            variants = [
                raw.replace("${schemePath(slug, corp)}", scheme)
                for scheme in ("/schemes/{}", "/schemes/corp/{}")
            ]
        for variant in variants:
            calls.setdefault(re.sub(r"\$\{[^}]*\}", "{}", variant), set()).update(names)

    for raw, params in re.findall(rf"withQuery\(\s*{string},\s*\{{([^}}]*)\}}", source):
        add(raw[1:-1], {n.split(":")[0].strip() for n in params.split(",") if n.strip()})
    for raw in re.findall(rf"apiRequest<\w+>\(\s*{string}", source):
        add(raw[1:-1], set())
    # fetchScheme llama a la ruta del esquema sin más.
    assert "apiRequest<SchemeDetail>(schemePath(slug, corp)," in source
    add("${schemePath(slug, corp)}", set())
    return calls


def test_frontend_calls_only_paths_and_parameters_of_the_contract() -> None:
    contract = {
        re.sub(r"\{[^}]*\}", "{}", path): {p["name"] for p in ops["get"].get("parameters", [])}
        for path, ops in _contract()["paths"].items()
        if "get" in ops
    }
    calls = _client_calls()
    expected = {
        "/vocabularies": {"q", "kind", "domain"},
        "/ontologies/{}": {"version"},
        "/ontologies/{}/rdf": {"format", "version", "download"},
        "/schemes/{}": set(),
        "/schemes/corp/{}": set(),
        "/schemes/{}/rdf": {"format", "download"},
        "/schemes/corp/{}/rdf": {"format", "download"},
        "/schemes/{}/concepts/{}": set(),
        "/schemes/corp/{}/concepts/{}": set(),
    }
    for path, params in expected.items():
        assert path in calls, f"el frontend no llama a {path}"
        assert calls[path] == params, path
    for path, params in calls.items():
        assert path in contract, f"el frontend llama a {path}, que no está en openapi.json"
        assert params <= contract[path], f"{path}: {params - contract[path]}"


def test_frontend_has_the_routes_the_backend_redirects_to() -> None:
    """Las URIs persistentes redirigen (303) a ``/ontologias/{slug}?version=`` y a
    ``/vocabularios/[corp/]{slug}?concepto=``: el frontend tiene esas rutas y lee esos
    parámetros."""
    backend = (REPO_ROOT / "backend" / "app" / "routers" / "linked_data_vocab.py").read_text(
        encoding="utf-8"
    )
    for fragment in ("/ontologias/", "?version=", "/vocabularios/", "corp/", "?concepto="):
        assert fragment in backend, fragment
    app = _require(FRONTEND_SRC / "App.tsx").read_text(encoding="utf-8")
    for route in (
        'path="ontologias/:slug"',
        'path="vocabularios/:slug"',
        'path="vocabularios/corp/:slug"',
    ):
        assert route in app, route
    assert app.index('path="vocabularios/corp/:slug"') < app.index('path="vocabularios/:slug"')
    pages = FRONTEND_SRC / "pages"
    assert "searchParams.get('version')" in (pages / "OntologyPage.tsx").read_text(encoding="utf-8")
    assert "searchParams.get('concepto')" in (pages / "SkosPage.tsx").read_text(encoding="utf-8")
    routes = (FRONTEND_SRC / "vocab" / "routes.ts").read_text(encoding="utf-8")
    assert "`/ontologias/${encodeURIComponent(slug)}`" in routes
    assert "`${base}?version=${encodeURIComponent(version)}`" in routes
    assert "`/vocabularios/${corp ? 'corp/' : ''}${encodeURIComponent(slug)}`" in routes
    assert "`${base}?concepto=${encodeURIComponent(concept)}`" in routes


def test_frontend_slug_and_version_patterns_match_the_backend() -> None:
    routes = _require(FRONTEND_SRC / "vocab" / "routes.ts").read_text(encoding="utf-8")
    slug = re.search(r"const SLUG = '([^']+)'", routes)
    version = re.search(r"const VERSION = '([^']+)'", routes)
    assert slug and version
    plain = lambda pattern: pattern.replace("(?:", "(").replace("\\\\", "\\")  # noqa: E731
    assert f"^{plain(slug.group(1))}$" == uris.SLUG_PATTERN
    assert f"^{plain(version.group(1))}$" == uris.VERSION_PATTERN
    reserved = re.search(r"RESERVED_SCHEMES = new Set\(\[([^\]]+)\]\)", routes)
    assert reserved
    assert set(re.findall(r"'([^']+)'", reserved.group(1))) == {"corp", "dominio", "tipo-dataset"}


def test_frontend_types_file_exists() -> None:
    assert _require(FRONTEND_TYPES).is_file()


# --- semantico -> backend ---------------------------------------------------------------


@pytest.fixture
def real_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """``Settings`` apuntando a la carpeta ``semantic/`` real del repositorio."""
    _require(REPO_SEMANTIC_DIR / "ontologias")
    monkeypatch.setenv("SEMANTIC_DIR", str(REPO_SEMANTIC_DIR))
    get_settings.cache_clear()
    ingest.clear_caches()
    settings = get_settings()
    yield settings
    get_settings.cache_clear()
    ingest.clear_caches()


def _semantic_files() -> dict[str, list[Path]]:
    root = _require(REPO_SEMANTIC_DIR / "vocabularios").parent
    return {
        "schemes": sorted((root / "vocabularios").glob("*.ttl")),
        "corp": sorted((root / "vocabularios" / "corp").glob("*.ttl")),
        "ontologies": sorted((root / "ontologias").glob("*/*.ttl")),
        "external": [root / "ontologias" / "externas.ttl"],
        "auxiliary": [root / "data" / "vocab-minimo.ttl"],
        "catalog": [root / "data" / "catalogo.ttl"],
        "series": sorted((root / "data" / "sintetico").glob("*.ttl")),
    }


def test_semantic_has_the_twenty_files_load_semantic_reads() -> None:
    files = _semantic_files()
    assert [p.stem for p in files["schemes"]] == ["did", "ia", "it", "ot", "pqc"]
    assert [p.stem for p in files["corp"]] == ["financiacion", "organizacion", "sectores", "trl"]
    assert [f"{p.parent.name}/{p.stem}" for p in files["ontologies"]] == [
        "didx/1.0.0",
        "itot/1.0.0",
        "itot/1.1.0",
        "itot/1.2.0",
        "pqcm/0.4.0",
    ]
    assert all(path.is_file() for group in files.values() for path in group)
    assert sum(len(group) for group in files.values()) == 20
    # Las rutas son las constantes del backend.
    root = REPO_SEMANTIC_DIR
    assert files["auxiliary"] == [root / ingest.VOCAB_FILE]
    assert files["catalog"] == [root / ingest.CATALOG_FILE]
    assert files["external"] == [root / ingest.EXTERNAL_ONTOLOGIES_FILE]
    assert files["schemes"][0].parent == root / ingest.VOCABULARIES_DIR
    assert files["ontologies"][0].parent.parent == root / ingest.ONTOLOGIES_DIR
    assert files["series"][0].parent == root / ingest.SYNTHETIC_DIR
    # Nada más en esas carpetas que load-semantic no vaya a leer.
    others = {
        p.relative_to(root).as_posix()
        for folder in ("vocabularios", "ontologias")
        for p in (root / folder).rglob("*")
        if p.is_file()
    } - {p.relative_to(root).as_posix() for group in files.values() for p in group}
    assert others == set()


def test_load_semantic_plan_covers_every_file_and_graph(
    real_settings: Settings, db: Session
) -> None:
    """``load-semantic`` valida los 21 ficheros reales y los reparte en 22 grafos: cada
    esquema en su URI, cada versión de ontología en su ``owl:versionIRI``, las externas en
    ``onto/externas``, el catálogo raíz, el catálogo «sintetico» (decisión 49) y las tres
    series."""
    base = Uris(real_settings.base_uri)
    plan, failed = cli._validate_all(real_settings, base, db)
    assert failed is False
    graphs = {
        **{prepared.uri: name for name, prepared in plan.schemes},
        **{prepared.version_iri: name for name, prepared, _analysis in plan.ontologies},
        **{graph_uri: name for name, graph_uri, _graph in plan.plain},
        **{graph_uri: name for name, graph_uri, _graph in plan.catalogs},
        **{prepared.uri: name for name, prepared in plan.series},
    }
    expected = {
        *(
            base.scheme(slug)
            for slug in ("did", "ia", "it", "ot", "pqc", "dominio", "tipo-dataset")
        ),
        *(
            base.scheme(slug, corp=True)
            for slug in ("financiacion", "organizacion", "sectores", "trl")
        ),
        base.ontology_version("itot", "1.0.0"),
        base.ontology_version("itot", "1.1.0"),
        base.ontology_version("itot", "1.2.0"),
        base.ontology_version("pqcm", "0.4.0"),
        base.ontology_version("didx", "1.0.0"),
        base.external_ontologies_graph,
        base.root_catalog,
        base.catalog("sintetico"),
        base.series("modbus-tcp-testbed"),
        base.series("hallazgos-auditorias-intrusion"),
        base.series("ejemplos-adversarios-vision"),
    }
    assert set(graphs) == expected
    assert len(graphs) == 22
    files = {name.split(" (")[0] for name in graphs.values()}
    assert len(files) == 21


def test_every_domain_scheme_declares_one_catalog_domain(
    real_settings: Settings, db: Session
) -> None:
    """Contrato de dominios de la fase 3: el dominio es el ``dct:subject`` del esquema, un
    concepto de ``vocab/dominio``; los corporativos y los auxiliares no llevan."""
    base = Uris(real_settings.base_uri)
    plan, _failed = cli._validate_all(real_settings, base, db)
    domains: dict[str, list[str | None]] = {}
    for _name, prepared in plan.schemes:
        subjects = [
            base.domain_of_domain_concept(str(o))
            for o in prepared.graph.objects(URIRef(prepared.uri), uris.DCT.subject)
        ]
        domains[("corp/" if prepared.corp else "") + prepared.slug] = subjects
    assert domains == {
        "it": ["it"],
        "ot": ["ot"],
        "pqc": ["pqc"],
        "did": ["pqc"],
        "ia": ["ia"],
        "dominio": [],
        "tipo-dataset": [],
        "corp/financiacion": [],
        "corp/organizacion": [],
        "corp/sectores": [],
        "corp/trl": [],
    }
    aux = next(p for _n, p in plan.schemes if p.slug == "dominio")
    concepts = {str(c) for c in aux.graph.subjects(RDF.type, SKOS.Concept)}
    assert concepts == {base.domain_concept(slug) for slug in uris.DOMAIN_SLUGS}


def test_uris_md_patterns_match_the_backend() -> None:
    text = _require(URIS_MD).read_text(encoding="utf-8").replace("\\|", "|")
    assert f"`{uris.SLUG_PATTERN}`" in text
    assert f"`{uris.VERSION_PATTERN}`" in text
    base = Uris("{BASE_URI}")
    for documented in (
        base.ontology("{slug}"),
        base.ontology_version("{slug}", "{version}"),
        f"{base.ontology('{slug}')}#{{Nombre}}",
        base.scheme("{esquema}"),
        base.scheme("{esquema}", corp=True),
        base.external_ontologies_graph,
        base.domain_concepts_scheme,
        base.synthetic_type,
        base.root_catalog,
        base.catalog("{slug}"),
        base.withdrawn_graph,
    ):
        assert f"`{documented}`" in text, documented


def test_reserved_scheme_slugs_match_uris_md() -> None:
    text = _require(URIS_MD).read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "están reservados" in line)
    documented = set(
        re.findall(r"`([a-z-]+)`", line.split("están reservados")[0].rsplit(". ", 1)[-1])
    )
    assert documented == {"corp", "dominio", "tipo-dataset"}
    # 'corp' no puede ser un slug; 'dominio' y 'tipo-dataset' son los esquemas auxiliares,
    # que solo carga load-semantic.
    assert documented == set(uris.RESERVED_SCHEME_SLUGS) | set(uris.AUXILIARY_SCHEME_SLUGS)


def test_auxiliary_scheme_graphs_match_uris_md(real_settings: Settings) -> None:
    text = _require(URIS_MD).read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| Esquemas auxiliares"))
    documented = set(re.findall(r"`(\{BASE_URI\}[^`]*)`", row))
    base = Uris("{BASE_URI}")
    assert documented == {base.scheme("dominio"), base.scheme("tipo-dataset")}


def test_reserved_ontology_slug_is_the_external_graph() -> None:
    assert set(uris.RESERVED_ONTOLOGY_SLUGS) == {"externas"}
    assert Uris(BASE_URI).external_ontologies_graph == f"{BASE_URI}onto/externas"


# --- Etiquetas de Git: uris.md, publicar.py y publicar.yml -------------------------------


@pytest.fixture(scope="module")
def publicar() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publicar", _require(PUBLICAR_PY))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_tags() -> dict[str, Path]:
    """Etiqueta que corresponde a cada fichero según ``semantic/uris.md``."""
    tags: dict[str, Path] = {}
    files = _semantic_files()
    for path in files["ontologies"]:
        tags[f"onto/{path.parent.name}/v{path.stem}"] = path
    for key, prefix in (("schemes", "vocab"), ("corp", "vocab/corp")):
        for path in files[key]:
            graph = Graph().parse(path, format="turtle", publicID=BASE_URI)
            (scheme,) = set(graph.subjects(RDF.type, SKOS.ConceptScheme))
            (version,) = set(graph.objects(scheme, OWL.versionInfo))
            tags[f"{prefix}/{path.stem}/v{version}"] = path
    return tags


def test_every_versioned_file_has_a_tag_that_publicar_accepts(publicar: ModuleType) -> None:
    tags = _expected_tags()
    assert len(tags) == 14  # 5 versiones de ontología + 5 esquemas de dominio + 4 corporativos
    for tag, path in tags.items():
        kind, slug, version = publicar.parse_tag(tag)
        assert publicar.source_path(kind, slug, version) == path, tag
        # La cabecera de cada fichero anuncia esa misma etiqueta.
        assert f"Etiqueta Git: {tag}." in path.read_text(encoding="utf-8"), tag


def test_tag_patterns_are_the_same_in_uris_md_publicar_and_the_workflow(
    publicar: ModuleType,
) -> None:
    text = _require(URIS_MD).read_text(encoding="utf-8")
    for pattern in (
        "`onto/{slug}/v{version}`",
        "`vocab/{slug}/v{version}`",
        "`vocab/corp/{slug}/v{version}`",
    ):
        assert pattern in text, pattern
        assert pattern.strip("`") in PUBLICAR_PY.read_text(encoding="utf-8")
        assert pattern in (REPO_ROOT / "infra" / "README.md").read_text(encoding="utf-8")
    examples = re.search(r"\(`(onto/[^`]+)`, `(vocab/[^`]+)`, `(vocab/corp/[^`]+)`\)", text)
    assert examples, "uris.md ya no da un ejemplo de cada etiqueta"
    workflow = _require(PUBLICAR_YML).read_text(encoding="utf-8")
    globs = re.findall(r'^\s+- "((?:onto|vocab)/[^"]+)"$', workflow, re.MULTILINE)
    assert sorted(globs) == ["onto/*/v*", "vocab/*/v*", "vocab/corp/*/v*"]
    patterns = [re.compile(re.escape(g).replace(r"\*", "[^/]*")) for g in globs]
    for tag in [*examples.groups(), *_expected_tags()]:
        assert publicar.parse_tag(tag), tag
        assert any(p.fullmatch(tag) for p in patterns), f"{tag} no dispara publicar.yml"
    # El patrón de slug y de versión es el del backend.
    assert f"^{publicar.SLUG.replace('(?:', '(')}$" == uris.SLUG_PATTERN
    assert f"^{publicar.VERSION.replace('(?:', '(')}$" == uris.VERSION_PATTERN
    assert publicar.DEFAULT_BASE_URI == BASE_URI


# --- infra -> backend -------------------------------------------------------------------


def _commented_env_example() -> dict[str, str]:
    """Variables opcionales de ``.env.example``: líneas ``# NOMBRE=valor``."""
    values: dict[str, str] = {}
    for line in _require(ENV_EXAMPLE).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"#\s*([A-Z][A-Z0-9_]*)=(.*)", line.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def test_reasoner_variables_are_documented_with_the_backend_defaults() -> None:
    optional = _commented_env_example()
    fields = Settings.model_fields
    assert optional["REASONER_TIMEOUT_SECONDS"] == f"{fields['reasoner_timeout_seconds'].default:g}"
    assert optional["REASONER_JAVA_MEMORY_MB"] == str(fields["reasoner_java_memory_mb"].default)
    # Límites de la ingesta (QA-G3-03 y QA-G3-10).
    assert optional["INGEST_MAX_TRIPLES"] == str(fields["ingest_max_triples"].default)
    assert optional["SHACL_TIMEOUT_SECONDS"] == f"{fields['shacl_timeout_seconds'].default:g}"
    assert optional["SHACL_MEMORY_MB"] == str(fields["shacl_memory_mb"].default)
    # Toda variable opcional documentada es un puerto del host o la lee el backend.
    for name in optional:
        assert name.endswith("_HOST_PORT") or name in _settings_env_names(), name
    # Llegan al backend por env_file: Compose no las fija ni las pisa en `environment`.
    compose = _require(COMPOSE).read_text(encoding="utf-8")
    assert re.search(r"^  backend:\n(?:    .*\n|\n)*?    env_file: \.env$", compose, re.MULTILINE)
    assert (
        not {"REASONER_TIMEOUT_SECONDS", "REASONER_JAVA_MEMORY_MB"} & _compose_backend_environment()
    )


def test_java_version_of_image_and_ci_is_enough_for_pellet() -> None:
    dockerfile = _require(DOCKERFILE).read_text(encoding="utf-8")
    (image_java,) = set(re.findall(r"openjdk-(\d+)-jre-headless", dockerfile))
    assert int(image_java) >= owl_metrics.MIN_JAVA_MAJOR
    assert re.search(r"ARG JRE_VERSION=\d+(?:\.\d+)+\+\d+-\S+", dockerfile), "JRE sin fijar"
    ci = _require(CI_YML).read_text(encoding="utf-8")
    backend_job = ci.split("\n  frontend:")[0]
    (ci_java,) = re.findall(r'java-version: "(\d+)"', backend_job)
    assert int(ci_java) >= owl_metrics.MIN_JAVA_MAJOR


def test_reasoner_settings_reach_the_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Las variables documentadas son las que usa la ingesta al llamar al razonador."""
    seen: dict[str, Any] = {}

    def fake(graph: Graph, iri: str, **kwargs: Any) -> owl_metrics.Consistency:
        seen.update(kwargs)
        return owl_metrics.Consistency()

    monkeypatch.setattr(owl_metrics, "check_consistency", fake)
    monkeypatch.setenv("REASONER_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("REASONER_JAVA_MEMORY_MB", "300")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        base = Uris(settings.base_uri)
        body = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> . <onto/x> a owl:Ontology ; "
            "owl:versionIRI <onto/x/1.0.0> . <onto/x#A> a owl:Class ."
        )
        graph = Graph().parse(data=body, format="turtle", publicID=base.base)
        prepared = vocab_ingest.check_ontology_structure(graph, base)
        vocab_ingest.compute_ontology_metrics(prepared, settings)
    finally:
        get_settings.cache_clear()
    assert seen == {"timeout_seconds": 7.0, "java_memory_mb": 300}
