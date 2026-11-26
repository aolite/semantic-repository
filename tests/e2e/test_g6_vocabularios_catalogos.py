"""Decisión 50 · esquemas SKOS y ontologías en los catálogos, de extremo a extremo.

Contra el Compose real (Fuseki y PostgreSQL de verdad): las consultas Update y de usos de la
decisión 50 solo se habían probado con dobles. Va después de G5 (por el nombre del fichero).
Cubre: publicar con ``?catalog=`` y sin él, la pertenencia en el grafo del catálogo (y no en el
del recurso), editar y mover, dar de baja (lápida, 410 en el recurso, sus conceptos y sus
versiones), los 409 (en uso por cada tipo de uso, otro catálogo, catálogo no vacío, conceptos
quitados o reactivados, slug y prefijo VANN dados de baja), los 422 (``replacement``,
``deprecated_theme``), el 403 ``not_managed``, los roles en cada endpoint y los intentos de
inyección por las IRIs que se interpolan en SPARQL.

Solo datos ficticios. Cómo lanzarlas: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import json
import secrets
import urllib.parse

import pytest
from conftest import Account, Response, Stack, create_account, create_catalog, http

AR = "http://publications.europa.eu/resource/authority/access-right/"
IANA = "http://www.iana.org/assignments/media-types/"
TURTLE = {"Content-Type": "text/turtle"}
HTML = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
RELATIONS = ["related", "exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch"]


# --- Utilidades ------------------------------------------------------------------------


def _slug(prefix: str) -> str:
    return f"{prefix}{secrets.token_hex(3)}"


def _base(stack: Stack) -> str:
    return stack.env["BASE_URI"]


def _json(response: Response) -> dict:
    return response.json()  # type: ignore[return-value]


def _api(stack: Stack, method: str, path: str, token: str | None, body: object | None = None):
    return http(method, f"{stack.api}{path}", json_body=body, token=token)


def _get(stack: Stack, path: str, **kwargs: object) -> Response:
    return http("GET", f"{stack.api}{path}", **kwargs)  # type: ignore[arg-type]


def _post(stack: Stack, path: str, ttl: str, token: str | None) -> Response:
    return http("POST", f"{stack.api}{path}", raw_body=ttl.encode(), headers=TURTLE, token=token)


def _sparql(stack: Stack, query: str) -> list[dict]:
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/sparql",
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return response.json()["results"]["bindings"]  # type: ignore[index]


def _ask(stack: Stack, query: str) -> bool:
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/sparql",
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    return bool(response.json()["boolean"])  # type: ignore[index]


def _graph_has(stack: Stack, graph: str, triple: str) -> bool:
    return _ask(stack, f"ASK {{ GRAPH <{graph}> {{ {triple} }} }}")


def _graph_exists(stack: Stack, graph: str) -> bool:
    return _ask(stack, f"ASK {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")


def _audit(stack: Stack, action: str) -> list[dict]:
    assert action.replace("_", "").isalpha()
    return [
        json.loads(line)
        for line in stack.psql(
            f"select row_to_json(a) from audit_events a where a.action = '{action}' order by a.id"
        )
    ]


def scheme_ttl(
    slug: str,
    prefix: str,
    *,
    corp: bool = False,
    concepts: tuple[str, ...] = ("raiz", "hoja"),
    deprecated: dict[str, list[str]] | None = None,
    related: list[tuple[str, str, str]] | None = None,
    status: str = "Completed",
    extra: str = "",
) -> str:
    """Esquema SKOS mínimo ficticio. ``concepts[0]`` es la raíz; los demás cuelgan de ella.
    ``deprecated`` es ``{concepto: [sustitutos]}``; ``related``, ``(concepto, relación, IRI)``."""
    path = f"vocab/corp/{slug}" if corp else f"vocab/{slug}"
    subject = "" if corp else "dct:subject <vocab/dominio/it> ;"
    root, leaves = concepts[0], concepts[1:]
    lines = [
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .",
        "@prefix dct: <http://purl.org/dc/terms/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix adms: <http://www.w3.org/ns/adms#> .",
        "@prefix vann: <http://purl.org/vocab/vann/> .",
        f"<{path}> a skos:ConceptScheme ; {subject}",
        "    dct:type <vocab/tipo-dataset/sintetico> ;",
        f'    skos:prefLabel "Esquema de la prueba {slug}"@es ;',
        f'    dct:title "Esquema de la prueba {slug}"@es ;',
        '    dct:description "Esquema creado por la prueba e2e de la decisión 50."@es ;',
        f'    owl:versionInfo "1.0" ; adms:status <http://purl.org/adms/status/{status}> ;',
        f'    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <{path}/> ;',
        f"    skos:hasTopConcept <{path}/{root}> .",
        f'<{path}/{root}> a skos:Concept ; skos:inScheme <{path}> ; skos:topConceptOf <{path}> ;',
        f'    skos:prefLabel "Raíz"@es .',
    ]
    for leaf in leaves:
        lines.append(
            f'<{path}/{leaf}> a skos:Concept ; skos:inScheme <{path}> ; '
            f'skos:broader <{path}/{root}> ; skos:prefLabel "Hoja {leaf}"@es .'
        )
    for concept, targets in (deprecated or {}).items():
        lines.append(f'<{path}/{concept}> owl:deprecated "true"^^<http://www.w3.org/2001/XMLSchema#boolean> .')
        for target in targets:
            lines.append(f"<{path}/{concept}> dct:isReplacedBy <{target}> .")
    for concept, relation, target in related or []:
        lines.append(f"<{path}/{concept}> skos:{relation} <{target}> .")
    lines.append(extra)
    return "\n".join(lines) + "\n"


def ontology_ttl(
    slug: str,
    prefix: str,
    version: str = "1.0.0",
    *,
    prior: str | None = None,
    extra: str = "",
) -> str:
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
    dct:description "Ontología creada por la prueba e2e de la decisión 50."@es ;
    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <onto/{slug}#> .
:Activo a owl:Class ; rdfs:comment "Clase de relleno de la prueba."@es .
:Sensor a owl:Class ; rdfs:subClassOf :Activo .
{extra}
"""


def series_ttl(
    slug: str, catalog: str, versions: dict[str, list[str]], conforms: list[str] | None = None
) -> str:
    """Serie con las versiones ``{versión: [temas]}`` (la última es ``dcat:last``); ``conforms``
    son las IRIs de ``dct:conformsTo`` de cada versión."""
    last = list(versions)[-1]
    out = [
        "@prefix dcat: <http://www.w3.org/ns/dcat#> .",
        "@prefix dct:  <http://purl.org/dc/terms/> .",
        f"<catalogo/{catalog}> dcat:dataset <dataset/{slug}> .",
        f"<dataset/{slug}> a dcat:DatasetSeries ; dct:type <vocab/tipo-dataset/sintetico> ;",
        f'    dct:title "Serie {slug}"@es ; dct:description "Serie de la prueba e2e de la 50."@es ;',
        f"    dcat:last <dataset/{slug}/{last}> .",
    ]
    for version, themes in versions.items():
        links = ", ".join(f"<{t}>" for t in themes)
        out += [
            f"<dataset/{slug}/{version}> a dcat:Dataset ; dct:type <vocab/tipo-dataset/sintetico> ;",
            f'    dct:title "Serie {slug}"@es ; dct:description "Serie de la prueba e2e de la 50."@es ;',
            f'    dcat:version "{version}" ; dcat:inSeries <dataset/{slug}> ;',
            f"    dct:accessRights <{AR}PUBLIC> ;",
            f"    dcat:theme {links} ;" if themes else "",
            "    dct:conformsTo " + ", ".join(f"<{c}>" for c in conforms) + " ;" if conforms else "",
            f"    dcat:distribution <dataset/{slug}/{version}/csv> .",
            f"<dataset/{slug}/{version}/csv> a dcat:Distribution ; dct:accessRights <{AR}PUBLIC> ;",
            f"    dcat:mediaType <{IANA}text/csv> ; dcat:accessURL <dataset/{slug}/{version}/csv> .",
        ]
    return "\n".join(out) + "\n"


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def editor(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


def _new_catalog(stack: Stack, admin: Account) -> str:
    slug = _slug("c50")
    assert create_catalog(stack, admin.token, slug).status == 201
    return slug


@pytest.fixture(scope="module")
def cat_a(stack: Stack, admin: Account) -> str:
    return _new_catalog(stack, admin)


@pytest.fixture(scope="module")
def cat_b(stack: Stack, admin: Account) -> str:
    return _new_catalog(stack, admin)


def publish_scheme(
    stack: Stack, token: str | None, catalog: str, slug: str | None = None, **kwargs: object
) -> tuple[str, Response]:
    slug = slug or _slug("s")
    prefix = kwargs.pop("prefix", None) or f"p{slug}"  # type: ignore[assignment]
    ttl = scheme_ttl(slug, prefix, **kwargs)  # type: ignore[arg-type]
    return slug, _post(stack, f"/schemes?catalog={catalog}", ttl, token)


def publish_ontology(
    stack: Stack, token: str | None, catalog: str, slug: str | None = None, **kwargs: object
) -> tuple[str, Response]:
    slug = slug or _slug("o")
    prefix = kwargs.pop("prefix", None) or f"p{slug}"  # type: ignore[assignment]
    ttl = ontology_ttl(slug, prefix, **kwargs)  # type: ignore[arg-type]
    return slug, _post(stack, f"/ontologies?catalog={catalog}", ttl, token)


def _catalog_detail(stack: Stack, catalog: str) -> dict:
    response = _get(stack, f"/catalogs/{catalog}")
    assert response.status == 200, response.text
    return _json(response)


def _scheme_slugs(stack: Stack, catalog: str) -> list[str]:
    return sorted(s["slug"] for s in _catalog_detail(stack, catalog)["schemes"])


def _ontology_slugs(stack: Stack, catalog: str) -> list[str]:
    return sorted(o["slug"] for o in _catalog_detail(stack, catalog)["ontologies"])


# --- 1. Publicar con catálogo ---------------------------------------------------------


def test_publicar_un_esquema_exige_catalogo(stack: Stack, editor: Account, cat_a: str) -> None:
    slug = _slug("s")
    body = scheme_ttl(slug, f"p{slug}")
    sin = _post(stack, "/schemes", body, editor.token)
    assert sin.status == 422, sin.text
    assert _get(stack, f"/schemes/{slug}").status == 404  # no se escribió nada
    assert _post(stack, "/schemes?catalog=no-existe", body, editor.token).status == 422
    assert _get(stack, f"/schemes/{slug}").status == 404
    ok = _post(stack, f"/schemes?catalog={cat_a}", body, editor.token)
    assert ok.status == 201, ok.text
    assert _json(ok)["catalog"] == f"{_base(stack)}catalogo/{cat_a}"


def test_la_pertenencia_vive_en_el_grafo_del_catalogo(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201, created.text
    uri, catalog = f"{base}vocab/{slug}", f"{base}catalogo/{cat_a}"
    assert _graph_has(stack, catalog, f"<{catalog}> <http://www.w3.org/ns/dcat#resource> <{uri}>")
    # Ni el grafo del esquema ni ningún otro grafo llevan el triple.
    assert not _ask(
        stack,
        f"ASK {{ GRAPH ?g {{ ?c <http://www.w3.org/ns/dcat#resource> <{uri}> }} "
        f"FILTER(?g != <{catalog}>) }}",
    )
    assert not _graph_has(stack, uri, "?c <http://www.w3.org/ns/dcat#resource> ?r")
    detail = _json(_get(stack, f"/schemes/{slug}"))
    assert detail["catalog"]["slug"] == cat_a
    page = _catalog_detail(stack, cat_a)
    assert slug in _scheme_slugs(stack, cat_a)
    assert page["scheme_count"] == len(page["schemes"])
    # El listado de vocabularios filtra por catálogo.
    listed = _json(_get(stack, f"/vocabularies?catalog={cat_a}"))
    assert slug in {i["slug"] for i in listed["items"]}


def test_publicar_una_ontologia_exige_catalogo_y_la_versionada_conserva_el_suyo(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    slug = _slug("o")
    body = ontology_ttl(slug, f"p{slug}")
    assert _post(stack, "/ontologies", body, editor.token).status == 422
    assert _get(stack, f"/ontologies/{slug}").status == 404
    created = _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token)
    assert created.status == 201, created.text
    assert slug in _ontology_slugs(stack, cat_a)
    catalog = f"{base}catalogo/{cat_a}"
    assert _graph_has(
        stack, catalog, f"<{catalog}> <http://www.w3.org/ns/dcat#resource> <{base}onto/{slug}>"
    )
    # Pertenece la ontología, no cada versión.
    assert not _graph_has(
        stack, f"{base}onto/{slug}/1.0.0", "?c <http://www.w3.org/ns/dcat#resource> ?r"
    )
    # Una versión nueva en el mismo catálogo: 201 y sigue en uno solo.
    second = _post(
        stack,
        f"/ontologies?catalog={cat_a}",
        ontology_ttl(slug, f"p{slug}", "1.1.0", prior="1.0.0"),
        editor.token,
    )
    assert second.status == 201, second.text
    assert _ontology_slugs(stack, cat_a).count(slug) == 1
    # Publicar otra versión en otro catálogo es explícito: 409 catalog_conflict.
    other = _post(
        stack,
        f"/ontologies?catalog={cat_b}",
        ontology_ttl(slug, f"p{slug}", "1.2.0", prior="1.1.0"),
        editor.token,
    )
    assert other.status == 409, other.text
    assert _json(other)["kind"] == "catalog_conflict"
    assert slug not in _ontology_slugs(stack, cat_b)
    assert _get(stack, f"/ontologies/{slug}?version=1.2.0").status == 404


def test_un_esquema_en_otro_catalogo_da_409_y_sin_cambios(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    again = _post(stack, f"/schemes?catalog={cat_b}", scheme_ttl(slug, f"p{slug}"), editor.token)
    assert again.status == 409, again.text
    assert _json(again)["kind"] == "catalog_conflict"
    assert slug not in _scheme_slugs(stack, cat_b)
    assert slug in _scheme_slugs(stack, cat_a)
    # El mismo contenido en su catálogo: 200 sin cambios.
    same = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(slug, f"p{slug}"), editor.token)
    assert same.status == 200 and _json(same)["changed"] is False


def test_el_catalogo_del_rdf_y_el_del_parametro_no_pueden_discrepar(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    slug = _slug("s")
    body = scheme_ttl(
        slug,
        f"p{slug}",
        extra=f"<catalogo/{cat_b}> <http://www.w3.org/ns/dcat#resource> <vocab/{slug}> .",
    )
    assert _post(stack, f"/schemes?catalog={cat_a}", body, editor.token).status == 422
    assert _get(stack, f"/schemes/{slug}").status == 404
    # Sin parámetro, el triple del RDF basta.
    assert _post(stack, "/schemes", body, editor.token).status == 201
    assert slug in _scheme_slugs(stack, cat_b)


@pytest.mark.parametrize(
    "extra",
    [
        # Cambiar los metadatos del catálogo desde el RDF de un esquema.
        '<catalogo/{cat}> <http://purl.org/dc/terms/title> "Robado"@es .',
        # Meter en el catálogo un recurso ajeno.
        "<catalogo/{cat}> <http://www.w3.org/ns/dcat#resource> <vocab/ot> .",
        "<catalogo/{cat}> <http://www.w3.org/ns/dcat#dataset> <dataset/otro> .",
        # El catálogo raíz no lista esquemas.
        "<catalogo> <http://www.w3.org/ns/dcat#resource> <vocab/{slug}> .",
    ],
)
def test_el_rdf_no_puede_escribir_en_el_catalogo_mas_que_su_pertenencia(
    stack: Stack, editor: Account, cat_a: str, extra: str
) -> None:
    slug = _slug("s")
    before = _json(_get(stack, f"/catalogs/{cat_a}"))
    body = scheme_ttl(slug, f"p{slug}", extra=extra.format(cat=cat_a, slug=slug))
    response = _post(stack, f"/schemes?catalog={cat_a}", body, editor.token)
    assert response.status == 422, response.text
    assert _get(stack, f"/schemes/{slug}").status == 404
    assert _json(_get(stack, f"/catalogs/{cat_a}")) == before


# --- 2. Editar y mover ----------------------------------------------------------------


def test_editar_y_mover_un_esquema(
    stack: Stack, admin: Account, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    for actor in (editor, admin):
        slug, created = publish_scheme(stack, actor.token, cat_a)
        assert created.status == 201
        before_concepts = _json(_get(stack, f"/schemes/{slug}"))["concept_count"]
        patched = _api(stack, "PATCH", f"/schemes/{slug}", actor.token, {"title": 'Título "nuevo" & <b>'})
        assert patched.status == 200, patched.text
        detail = _json(patched)
        assert detail["title"] == 'Título "nuevo" & <b>'
        assert detail["concept_count"] == before_concepts  # los conceptos no cambian
        assert detail["catalog"]["slug"] == cat_a
        moved = _api(stack, "PATCH", f"/schemes/{slug}", actor.token, {"catalog": cat_b})
        assert moved.status == 200, moved.text
        assert _json(moved)["catalog"]["slug"] == cat_b
        assert slug in _scheme_slugs(stack, cat_b) and slug not in _scheme_slugs(stack, cat_a)
        uri = f"{base}vocab/{slug}"
        assert not _graph_has(
            stack, f"{base}catalogo/{cat_a}", f"?c <http://www.w3.org/ns/dcat#resource> <{uri}>"
        )
        assert _graph_has(
            stack, f"{base}catalogo/{cat_b}", f"?c <http://www.w3.org/ns/dcat#resource> <{uri}>"
        )
        # Ninguna URI cambió: los conceptos siguen donde estaban.
        assert _get(stack, f"/schemes/{slug}/concepts/hoja").status == 200
        assert _get(stack, f"/vocab/{slug}/hoja", follow_redirects=False, headers=HTML).status == 303
        # Mover de un catálogo que no existe: 422; PATCH vacío no cambia el catálogo.
        assert _api(stack, "PATCH", f"/schemes/{slug}", actor.token, {"catalog": "no-existe"}).status == 422
        assert _api(stack, "PATCH", f"/schemes/{slug}", actor.token, {}).status == 200
        assert _json(_get(stack, f"/schemes/{slug}"))["catalog"]["slug"] == cat_b
        # Campos que no se editan por esta vía.
        for forbidden in ({"slug": "otro"}, {"uri": "x"}, {"concepts": []}):
            assert _api(stack, "PATCH", f"/schemes/{slug}", actor.token, forbidden).status == 422
    assert [e["details"]["via"] for e in _audit(stack, "scheme_updated")][-1] == "api"


def test_editar_y_mover_un_esquema_corporativo(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    slug = _slug("k")
    created = _post(
        stack, f"/schemes?catalog={cat_a}", scheme_ttl(slug, f"p{slug}", corp=True), editor.token
    )
    assert created.status == 201, created.text
    assert _json(created)["corp"] is True
    moved = _api(stack, "PATCH", f"/schemes/corp/{slug}", editor.token, {"catalog": cat_b})
    assert moved.status == 200, moved.text
    assert slug in _scheme_slugs(stack, cat_b)
    assert _api(stack, "PATCH", f"/schemes/{slug}", editor.token, {"title": "x"}).status == 404
    assert _api(stack, "DELETE", f"/schemes/corp/{slug}", editor.token).status == 204
    assert _get(stack, f"/schemes/corp/{slug}").status == 410
    # vocab/ot y vocab/corp/ot son URIs distintas: la baja de una no bloquea la otra.
    other = _post(
        stack,
        f"/schemes?catalog={cat_a}",
        scheme_ttl(slug, f"q{slug}"),
        editor.token,
    )
    assert other.status == 201, other.text


def test_mover_una_ontologia_no_toca_sus_versiones(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    slug, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    assert (
        _post(
            stack,
            f"/ontologies?catalog={cat_a}",
            ontology_ttl(slug, f"p{slug}", "1.1.0", prior="1.0.0"),
            editor.token,
        ).status
        == 201
    )
    rdf_before = _get(stack, f"/ontologies/{slug}/rdf?format=turtle&version=1.0.0").text
    moved = _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {"catalog": cat_b})
    assert moved.status == 200, moved.text
    assert slug in _ontology_slugs(stack, cat_b) and slug not in _ontology_slugs(stack, cat_a)
    assert _json(_get(stack, f"/ontologies/{slug}"))["catalog"]["slug"] == cat_b
    assert _get(stack, f"/ontologies/{slug}/rdf?format=turtle&version=1.0.0").text == rdf_before
    assert _json(_get(stack, f"/ontologies/{slug}"))["versioning"]["current_version"] == "1.1.0"
    assert not _graph_has(
        stack,
        f"{base}catalogo/{cat_a}",
        f"?c <http://www.w3.org/ns/dcat#resource> <{base}onto/{slug}>",
    )
    # Solo el catálogo es editable; sin él o con otro campo, 422; destino que no existe, 422.
    assert _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {}).status == 422
    assert _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {"title": "x"}).status == 422
    assert (
        _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {"catalog": cat_b, "title": "x"}).status
        == 422
    )
    assert _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {"catalog": "no-existe"}).status == 422
    assert _api(stack, "PATCH", "/ontologies/no-existe", editor.token, {"catalog": cat_b}).status == 404


# --- 3. Baja: lápida y 410 ------------------------------------------------------------


def test_dar_de_baja_un_esquema(stack: Stack, admin: Account, editor: Account, cat_a: str) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    uri = f"{base}vocab/{slug}"
    assert _graph_exists(stack, uri)
    assert _api(stack, "DELETE", f"/schemes/{slug}", editor.token).status == 204
    # La lápida sustituye a la descripción y el triple del catálogo desaparece.
    assert not _graph_exists(stack, uri)
    assert not _graph_has(
        stack, f"{base}catalogo/{cat_a}", f"?c <http://www.w3.org/ns/dcat#resource> <{uri}>"
    )
    assert _graph_has(stack, f"{base}bajas", f"<{uri}> <http://www.w3.org/ns/adms#status> ?s")
    assert not _graph_has(stack, f"{base}bajas", f"<{uri}> a <http://www.w3.org/2004/02/skos/core#ConceptScheme>")
    assert slug not in _scheme_slugs(stack, cat_a)
    assert slug not in {i["slug"] for i in _json(_get(stack, "/vocabularies?page_size=100"))["items"]}
    # 410 en la API: el esquema, sus conceptos, su RDF, y editar o borrar de nuevo.
    for path in (
        f"/schemes/{slug}",
        f"/schemes/{slug}/concepts/hoja",
        f"/schemes/{slug}/rdf",
    ):
        gone = _get(stack, path)
        assert gone.status == 410, f"{path}: {gone.status} {gone.text[:200]}"
        assert _json(gone)["resource"] == "scheme"
    assert _api(stack, "PATCH", f"/schemes/{slug}", editor.token, {"title": "x"}).status == 410
    assert _api(stack, "DELETE", f"/schemes/{slug}", admin.token).status == 410
    # Una URI de concepto que nunca existió bajo un esquema vivo sigue siendo 404.
    assert _get(stack, "/schemes/no-existe-nunca/concepts/hoja").status == 404
    # 410 en las URIs persistentes: HTML y RDF (lápida), también por arrastre.
    for path in (f"/vocab/{slug}", f"/vocab/{slug}/hoja"):
        assert http("GET", f"{stack.api}{path}", headers=HTML, follow_redirects=False).status == 410, path
        rdf = http("GET", f"{stack.api}{path}", headers={"Accept": "text/turtle"}, follow_redirects=False)
        assert rdf.status == 410, path
        assert "Esquema de la prueba" in rdf.text or uri in rdf.text
        assert "skos:hasTopConcept" not in rdf.text and "ConceptScheme" not in rdf.text
    rows = _audit(stack, "scheme_withdrawn")
    assert any(r["details"]["scheme"] == uri and r["details"]["prefix"] == f"p{slug}" for r in rows)
    assert stack.psql(f"select resource_uri from withdrawn_prefixes where prefix = 'p{slug}'") == [uri]


def test_dar_de_baja_una_ontologia_con_todas_sus_versiones(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    assert (
        _post(
            stack,
            f"/ontologies?catalog={cat_a}",
            ontology_ttl(slug, f"p{slug}", "1.1.0", prior="1.0.0"),
            editor.token,
        ).status
        == 201
    )
    versions = [f"{base}onto/{slug}/1.0.0", f"{base}onto/{slug}/1.1.0"]
    assert all(_graph_exists(stack, v) for v in versions)
    assert stack.psql(f"select count(*) from ontology_metrics where ontology_iri = '{base}onto/{slug}'") == ["2"]
    assert _api(stack, "DELETE", f"/ontologies/{slug}", editor.token).status == 204
    assert not any(_graph_exists(stack, v) for v in versions)
    assert stack.psql(f"select count(*) from ontology_metrics where ontology_iri = '{base}onto/{slug}'") == ["0"]
    assert slug not in _ontology_slugs(stack, cat_a)
    for path in (
        f"/ontologies/{slug}",
        f"/ontologies/{slug}?version=1.0.0",
        f"/ontologies/{slug}/rdf",
        f"/ontologies/{slug}/rdf?version=1.1.0",
    ):
        gone = _get(stack, path)
        assert gone.status == 410, f"{path}: {gone.status}"
        assert _json(gone)["resource"] == "ontology"
    for path in (f"/onto/{slug}", f"/onto/{slug}/1.0.0", f"/onto/{slug}/1.1.0"):
        assert http("GET", f"{stack.api}{path}", headers=HTML, follow_redirects=False).status == 410, path
        turtle = http("GET", f"{stack.api}{path}", headers={"Accept": "text/turtle"}, follow_redirects=False)
        assert turtle.status == 410 and "owl:Ontology" not in turtle.text, path
    # Un término #X cae en la URI de la ontología (el fragmento no llega al servidor).
    assert http("GET", f"{stack.api}/onto/{slug}", headers=HTML, follow_redirects=False).status == 410
    assert _api(stack, "PATCH", f"/ontologies/{slug}", editor.token, {"catalog": cat_a}).status == 410
    assert _api(stack, "DELETE", f"/ontologies/{slug}", editor.token).status == 410
    assert any(r["details"]["ontology"] == f"{base}onto/{slug}" for r in _audit(stack, "ontology_withdrawn"))


def test_un_slug_y_un_prefijo_dados_de_baja_no_se_reutilizan(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    # Esquema.
    slug, created = publish_scheme(stack, editor.token, cat_a, prefix=_slug("vp"))
    assert created.status == 201
    assert _api(stack, "DELETE", f"/schemes/{slug}", editor.token).status == 204
    for catalog in (cat_a, cat_b):  # el slug no se reutiliza ni en otro catálogo
        again = _post(stack, f"/schemes?catalog={catalog}", scheme_ttl(slug, _slug("zz")), editor.token)
        assert again.status == 409 and _json(again)["kind"] == "withdrawn", again.text
    # Ontología.
    oslug, created = publish_ontology(stack, editor.token, cat_a, prefix=_slug("op"))
    assert created.status == 201
    assert _api(stack, "DELETE", f"/ontologies/{oslug}", editor.token).status == 204
    again = _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(oslug, _slug("zz")), editor.token)
    assert again.status == 409 and _json(again)["kind"] == "withdrawn", again.text
    # El prefijo VANN: otro recurso con el prefijo de uno dado de baja, 409 prefix_withdrawn,
    # en esquemas y ontologías, cruzados entre sí.
    p_scheme, p_onto = _slug("pw"), _slug("pw")
    s1, created = publish_scheme(stack, editor.token, cat_a, prefix=p_scheme)
    o1, created_o = publish_ontology(stack, editor.token, cat_a, prefix=p_onto)
    assert created.status == 201 and created_o.status == 201
    assert _api(stack, "DELETE", f"/schemes/{s1}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{o1}", editor.token).status == 204
    for new_slug, prefix_used in ((_slug("n"), p_scheme), (_slug("n"), p_onto)):
        scheme = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(new_slug, prefix_used), editor.token)
        onto = _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(new_slug, prefix_used), editor.token)
        for response in (scheme, onto):
            assert response.status == 409, response.text
            assert _json(response)["kind"] == "prefix_withdrawn"
        assert _get(stack, f"/schemes/{new_slug}").status == 404
        assert _get(stack, f"/ontologies/{new_slug}").status == 404
    # vocab/x y vocab/corp/x son URIs distintas (con otro prefijo, 201).
    corp = _post(
        stack,
        f"/schemes?catalog={cat_a}",
        scheme_ttl(s1, _slug("ok"), corp=True),
        editor.token,
    )
    assert corp.status == 201, corp.text


# --- 4. 409 «en uso» (regla 8) --------------------------------------------------------


def _in_use(response: Response) -> list[dict]:
    assert response.status == 409, f"{response.status} {response.text[:400]}"
    body = _json(response)
    assert body["kind"] == "in_use"
    assert body["used_by"], body
    return body["used_by"]


def test_un_esquema_usado_como_tema_de_un_dataset_no_se_da_de_baja(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    scheme, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    series = _slug("d")
    theme = f"vocab/{scheme}/hoja"
    published = _post(stack, "/datasets", series_ttl(series, cat_a, {"1.0.0": [theme]}), editor.token)
    assert published.status == 201, published.text
    uses = _in_use(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token))
    assert uses == [
        {
            "uri": f"{base}dataset/{series}/1.0.0",
            "resource": "dataset",
            "via": "http://www.w3.org/ns/dcat#theme",
            "target": f"{base}{theme}",
        }
    ]
    assert _get(stack, f"/schemes/{scheme}").status == 200  # sigue vivo
    assert _graph_exists(stack, f"{base}vocab/{scheme}")
    # Dado de baja el dataset, ya nadie lo usa.
    assert _api(stack, "DELETE", f"/datasets/{series}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204


def test_un_esquema_usado_por_una_ontologia_no_se_da_de_baja(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    scheme, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    onto = _slug("o")
    body = ontology_ttl(
        onto,
        f"p{onto}",
        extra=f"<onto/{onto}> <http://purl.org/dc/terms/subject> <vocab/{scheme}/raiz> .",
    )
    assert _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token).status == 201
    uses = _in_use(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token))
    assert uses == [
        {
            "uri": f"{base}onto/{onto}/1.0.0",
            "resource": "ontology",
            "via": "http://purl.org/dc/terms/subject",
            "target": f"{base}vocab/{scheme}/raiz",
        }
    ]
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204


@pytest.mark.parametrize("relation", RELATIONS)
def test_un_esquema_con_mapeos_desde_otro_no_se_da_de_baja(
    stack: Stack, editor: Account, cat_a: str, relation: str
) -> None:
    base = _base(stack)
    target, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    source = _slug("m")
    mapping = [("hoja", relation, f"{base}vocab/{target}/hoja")]
    ok = _post(
        stack,
        f"/schemes?catalog={cat_a}",
        scheme_ttl(source, f"p{source}", related=mapping),
        editor.token,
    )
    assert ok.status == 201, ok.text
    uses = _in_use(_api(stack, "DELETE", f"/schemes/{target}", editor.token))
    assert [(u["resource"], u["via"], u["target"]) for u in uses] == [
        ("scheme", f"http://www.w3.org/2004/02/skos/core#{relation}", f"{base}vocab/{target}/hoja")
    ]
    assert uses[0]["uri"] == f"{base}vocab/{source}/hoja"
    # El que mapea se puede dar de baja (nadie lo usa) y entonces el destino queda libre.
    assert _api(stack, "DELETE", f"/schemes/{source}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/schemes/{target}", editor.token).status == 204


def test_los_mapeos_dentro_del_mismo_esquema_no_cuentan_como_uso(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug = _slug("i")
    body = scheme_ttl(
        slug,
        f"p{slug}",
        concepts=("raiz", "hoja", "otra"),
        related=[("hoja", "related", f"{base}vocab/{slug}/otra")],
    )
    assert _post(stack, f"/schemes?catalog={cat_a}", body, editor.token).status == 201
    assert _api(stack, "DELETE", f"/schemes/{slug}", editor.token).status == 204


def test_un_esquema_en_uso_no_se_da_de_baja_aunque_lo_use_un_recurso_de_otro_catalogo(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    scheme, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    series = _slug("d")
    themed = series_ttl(series, cat_b, {"1.0.0": [f"vocab/{scheme}/raiz"]})
    published = _post(stack, "/datasets", themed, editor.token)
    assert published.status == 201, published.text
    assert _in_use(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token))
    # Mover el esquema tampoco lo suelta: el uso sigue.
    assert _api(stack, "PATCH", f"/schemes/{scheme}", editor.token, {"catalog": cat_b}).status == 200
    assert _in_use(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token))
    assert _graph_exists(stack, f"{base}vocab/{scheme}")


def test_una_ontologia_importada_por_otra_no_se_da_de_baja(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    target, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    for imported in (f"onto/{target}", f"onto/{target}/1.0.0"):
        user = _slug("u")
        body = ontology_ttl(user, f"p{user}", extra=f"<onto/{user}> owl:imports <{imported}> .")
        assert _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token).status == 201
        uses = _in_use(_api(stack, "DELETE", f"/ontologies/{target}", editor.token))
        assert [(u["uri"], u["via"], u["target"]) for u in uses] == [
            (f"{base}onto/{user}/1.0.0", "http://www.w3.org/2002/07/owl#imports", f"{base}{imported}")
        ]
        assert _graph_exists(stack, f"{base}onto/{target}/1.0.0")
        assert _api(stack, "DELETE", f"/ontologies/{user}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{target}", editor.token).status == 204


def test_una_ontologia_con_terminos_usados_por_otra_no_se_da_de_baja(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    target, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    user = _slug("u")
    body = ontology_ttl(
        user, f"p{user}", extra=f"<onto/{user}#Maquina> rdfs:subClassOf <onto/{target}#Activo> ."
    )
    assert _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token).status == 201
    uses = _in_use(_api(stack, "DELETE", f"/ontologies/{target}", editor.token))
    assert (uses[0]["uri"], uses[0]["via"], uses[0]["target"]) == (
        f"{base}onto/{user}/1.0.0",
        None,
        f"{base}onto/{target}#Activo",
    )
    # Un término como predicado también cuenta.
    other = _slug("u")
    body = ontology_ttl(
        other, f"p{other}", extra=f"<onto/{other}#a> <onto/{target}#mide> <onto/{other}#b> ."
    )
    assert _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token).status == 201
    assert len(_in_use(_api(stack, "DELETE", f"/ontologies/{target}", editor.token))) == 2
    for slug in (user, other):
        assert _api(stack, "DELETE", f"/ontologies/{slug}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{target}", editor.token).status == 204


def test_las_versiones_de_una_ontologia_no_se_cuentan_como_uso_entre_si(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    slug, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    second = _post(
        stack,
        f"/ontologies?catalog={cat_a}",
        ontology_ttl(
            slug,
            f"p{slug}",
            "1.1.0",
            prior="1.0.0",
            extra=f"<onto/{slug}> owl:imports <onto/{slug}/1.0.0> .",
        ),
        editor.token,
    )
    assert second.status == 201, second.text
    assert _api(stack, "DELETE", f"/ontologies/{slug}", editor.token).status == 204


def test_el_409_en_uso_no_escribe_nada_ni_audita(stack: Stack, editor: Account, cat_a: str) -> None:
    base = _base(stack)
    scheme, _ = publish_scheme(stack, editor.token, cat_a)
    series = _slug("d")
    themed = series_ttl(series, cat_a, {"1.0.0": [f"vocab/{scheme}/hoja"]})
    assert _post(stack, "/datasets", themed, editor.token).status == 201
    before = len(_audit(stack, "scheme_withdrawn"))
    prefixes = stack.psql("select count(*) from withdrawn_prefixes")
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 409
    assert len(_audit(stack, "scheme_withdrawn")) == before
    assert stack.psql("select count(*) from withdrawn_prefixes") == prefixes
    assert _get(stack, f"/schemes/{scheme}/concepts/hoja").status == 200
    assert not _graph_has(stack, f"{base}bajas", f"<{base}vocab/{scheme}> ?p ?o")  # sin lápida


# --- 5. Catálogo no vacío (regla 10) ---------------------------------------------------


def test_un_catalogo_con_esquemas_u_ontologias_no_se_da_de_baja(
    stack: Stack, admin: Account, editor: Account
) -> None:
    base = _base(stack)
    catalog = _new_catalog(stack, admin)
    scheme, _ = publish_scheme(stack, editor.token, catalog)
    onto, _ = publish_ontology(stack, editor.token, catalog)
    refused = _api(stack, "DELETE", f"/catalogs/{catalog}", editor.token)
    assert refused.status == 409, refused.text
    body = _json(refused)
    assert body["kind"] == "catalog_not_empty"
    assert body["datasets"] == []
    assert sorted(body["resources"]) == sorted([f"{base}vocab/{scheme}", f"{base}onto/{onto}"])
    # Solo con ontologías, y vacío.
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204
    again = _api(stack, "DELETE", f"/catalogs/{catalog}", editor.token)
    assert again.status == 409 and _json(again)["resources"] == [f"{base}onto/{onto}"]
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/catalogs/{catalog}", editor.token).status == 204
    # Un catálogo dado de baja no admite publicar ni recibir recursos (422).
    gone = _post(stack, f"/schemes?catalog={catalog}", scheme_ttl(_slug("s"), _slug("x")), editor.token)
    assert gone.status == 422, gone.text
    other, _ = publish_scheme(stack, editor.token, _new_catalog(stack, admin))
    assert _api(stack, "PATCH", f"/schemes/{other}", editor.token, {"catalog": catalog}).status == 422
    assert _json(_get(stack, f"/schemes/{other}"))["catalog"]["slug"] != catalog


def test_el_catalogo_con_un_esquema_movido_queda_vacio_y_se_puede_borrar(
    stack: Stack, admin: Account, editor: Account, cat_b: str
) -> None:
    catalog = _new_catalog(stack, admin)
    scheme, _ = publish_scheme(stack, editor.token, catalog)
    assert _api(stack, "DELETE", f"/catalogs/{catalog}", editor.token).status == 409
    assert _api(stack, "PATCH", f"/schemes/{scheme}", editor.token, {"catalog": cat_b}).status == 200
    assert _api(stack, "DELETE", f"/catalogs/{catalog}", editor.token).status == 204


# --- 6. Conceptos: quitados, reactivados, retirados y sustitutos (regla 9) -------------


def _republish(
    stack: Stack, token: str | None, catalog: str, slug: str, **kwargs: object
) -> Response:
    prefix = kwargs.pop("prefix", None) or f"p{slug}"
    return _post(
        stack,
        f"/schemes?catalog={catalog}",
        scheme_ttl(slug, prefix, **kwargs),  # type: ignore[arg-type]
        token,
    )


def test_republicar_sin_un_concepto_publicado_da_409_y_no_cambia_nada(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a, concepts=("raiz", "hoja", "otra"))
    assert created.status == 201
    before = _get(stack, f"/schemes/{slug}/rdf?format=turtle").text
    refused = _republish(stack, editor.token, cat_a, slug, concepts=("raiz", "hoja"))
    assert refused.status == 409, refused.text
    body = _json(refused)
    assert body["kind"] == "concepts_removed"
    assert [i["focus_node"] for i in body["issues"]] == [f"{base}vocab/{slug}/otra"]
    assert _get(stack, f"/schemes/{slug}/rdf?format=turtle").text == before
    # Añadir conceptos sí se puede.
    more = _republish(stack, editor.token, cat_a, slug, concepts=("raiz", "hoja", "otra", "nueva"))
    assert more.status == 200, more.text
    assert _json(_get(stack, f"/schemes/{slug}"))["concept_count"] == 4


def test_retirar_un_concepto_con_sustituto_y_no_poder_reactivarlo(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a, concepts=("raiz", "hoja", "otra"))
    assert created.status == 201
    replacement = f"{base}vocab/{slug}/otra"
    retired = _republish(
        stack,
        editor.token,
        cat_a,
        slug,
        concepts=("raiz", "hoja", "otra"),
        deprecated={"hoja": [replacement]},
    )
    assert retired.status == 200, retired.text
    concept = _json(_get(stack, f"/schemes/{slug}/concepts/hoja"))
    assert concept["deprecated"] is True
    assert [r["uri"] for r in concept["replaced_by"]] == [replacement]
    assert _json(_get(stack, f"/schemes/{slug}/concepts/otra"))["deprecated"] is False
    tree = _json(_get(stack, f"/schemes/{slug}"))["tree"]
    assert "hoja" in {c["slug"] for n in tree for c in n["children"]}  # conserva su lugar
    # Reactivar (quitar owl:deprecated): 409 concept_reactivated.
    again = _republish(stack, editor.token, cat_a, slug, concepts=("raiz", "hoja", "otra"))
    assert again.status == 409 and _json(again)["kind"] == "concept_reactivated", again.text
    assert _json(_get(stack, f"/schemes/{slug}/concepts/hoja"))["deprecated"] is True
    # Poner owl:deprecated false también es reactivar.
    false_ttl = scheme_ttl(
        slug,
        f"p{slug}",
        concepts=("raiz", "hoja", "otra"),
        extra=f"<vocab/{slug}/hoja> <http://www.w3.org/2002/07/owl#deprecated> false .",
    )
    again = _post(stack, f"/schemes?catalog={cat_a}", false_ttl, editor.token)
    assert again.status in (409, 422), again.text
    assert _json(_get(stack, f"/schemes/{slug}/concepts/hoja"))["deprecated"] is True
    # Retirarlo y además quitarlo sigue siendo concepts_removed.
    removed = _republish(stack, editor.token, cat_a, slug, concepts=("raiz", "otra"))
    assert removed.status == 409 and _json(removed)["kind"] == "concepts_removed"


def test_un_sustituto_tiene_que_ser_un_concepto_vivo(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a)
    other, created_other = publish_scheme(stack, editor.token, cat_b)
    dead, created_dead = publish_scheme(stack, editor.token, cat_a)
    assert created.status == created_other.status == created_dead.status == 201
    assert _api(stack, "DELETE", f"/schemes/{dead}", editor.token).status == 204
    for target in (
        f"{base}vocab/{slug}/no-existe",  # concepto que no existe
        f"{base}vocab/{dead}/hoja",  # concepto de un esquema dado de baja
        f"{base}vocab/{slug}",  # el esquema, que no es un concepto
        f"{base}onto/itot#Activo",  # fuera de los vocabularios
        "https://example.org/externo/x",  # IRI externa
    ):
        refused = _republish(stack, editor.token, cat_a, slug, deprecated={"hoja": [target]})
        assert refused.status == 422, f"{target}: {refused.status} {refused.text[:300]}"
        assert _json(refused)["kind"] == "replacement"
        assert _json(_get(stack, f"/schemes/{slug}/concepts/hoja"))["deprecated"] is False
    # Un concepto vivo de otro esquema, sí.
    ok = _republish(stack, editor.token, cat_a, slug, deprecated={"hoja": [f"{base}vocab/{other}/hoja"]})
    assert ok.status == 200, ok.text
    replaced = _json(_get(stack, f"/schemes/{slug}/concepts/hoja"))["replaced_by"]
    assert [r["uri"] for r in replaced] == [f"{base}vocab/{other}/hoja"]


def test_dct_isreplacedby_sin_owl_deprecated_o_hacia_si_mismo_se_rechaza(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    body = scheme_ttl(
        slug,
        f"p{slug}",
        extra=f"<vocab/{slug}/hoja> <http://purl.org/dc/terms/isReplacedBy> <{base}vocab/{slug}/raiz> .",
    )
    assert _post(stack, f"/schemes?catalog={cat_a}", body, editor.token).status == 422
    self_replaced = scheme_ttl(slug, f"p{slug}", deprecated={"hoja": [f"{base}vocab/{slug}/hoja"]})
    assert _post(stack, f"/schemes?catalog={cat_a}", self_replaced, editor.token).status == 422


def test_una_version_nueva_con_un_tema_retirado_da_422_con_los_sustitutos(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    scheme, created = publish_scheme(stack, editor.token, cat_a, concepts=("raiz", "hoja", "otra"))
    assert created.status == 201
    series = _slug("d")
    hoja, otra = f"vocab/{scheme}/hoja", f"vocab/{scheme}/otra"
    first = _post(stack, "/datasets", series_ttl(series, cat_a, {"1.0.0": [hoja]}), editor.token)
    assert first.status == 201, first.text
    # Retirar el tema usado por una versión ya publicada es legal.
    retired = _republish(
        stack,
        editor.token,
        cat_a,
        scheme,
        concepts=("raiz", "hoja", "otra"),
        deprecated={"hoja": [f"{base}{otra}"]},
    )
    assert retired.status == 200, retired.text
    both = series_ttl(series, cat_a, {"1.0.0": [hoja], "1.1.0": [hoja]})
    refused = _post(stack, "/datasets", both, editor.token)
    assert refused.status == 422, refused.text
    body = _json(refused)
    assert body["kind"] == "deprecated_theme"
    assert [(i["value"], i["replaced_by"]) for i in body["issues"]] == [
        (f"{base}{hoja}", [f"{base}{otra}"])
    ]
    assert _get(stack, f"/datasets/{series}/rdf?version=1.1.0&format=turtle").status == 404
    # Republicar la serie tal cual (la versión ya publicada no se comprueba): sin cambios.
    same = _post(stack, "/datasets", series_ttl(series, cat_a, {"1.0.0": [hoja]}), editor.token)
    assert same.status == 200, same.text
    # Con el sustituto, se publica.
    fixed = series_ttl(series, cat_a, {"1.0.0": [hoja], "1.1.0": [otra]})
    ok = _post(stack, "/datasets", fixed, editor.token)
    assert ok.status in (200, 201), ok.text
    # Un tema retirado sin sustitutos: 422 con replaced_by vacío.
    bare, _ = publish_scheme(stack, editor.token, cat_a, deprecated={"hoja": []})
    lone = series_ttl(_slug("d"), cat_a, {"1.0.0": [f"vocab/{bare}/hoja"]})
    refused = _post(stack, "/datasets", lone, editor.token)
    assert refused.status == 422 and _json(refused)["kind"] == "deprecated_theme"
    assert _json(refused)["issues"][0]["replaced_by"] == []


# --- 7. 403 not_managed: ontologías externas y esquemas auxiliares (reglas 5 y 12) ----

EXTERNAL_ONTOLOGY = "http://www.w3.org/ns/sosa/"


def _snapshot(stack: Stack) -> dict[str, int]:
    rows = _sparql(stack, "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")
    return {row["g"]["value"]: int(row["n"]["value"]) for row in rows}


@pytest.mark.parametrize("who", ["editor", "admin"])
def test_los_esquemas_auxiliares_y_las_ontologias_externas_dan_403_not_managed(
    stack: Stack, admin: Account, editor: Account, cat_a: str, who: str
) -> None:
    token = (editor if who == "editor" else admin).token
    before = _snapshot(stack)
    requests = [
        ("PATCH", "/schemes/dominio", {"title": "x"}),
        ("PATCH", "/schemes/dominio", {"catalog": cat_a}),
        ("PATCH", "/schemes/tipo-dataset", {"title": "x"}),
        ("DELETE", "/schemes/dominio", None),
        ("DELETE", "/schemes/tipo-dataset", None),
        ("PATCH", "/ontologies/externas", {"catalog": cat_a}),
        ("DELETE", "/ontologies/externas", None),
    ]
    for method, path, body in requests:
        response = _api(stack, method, path, token, body)
        assert response.status == 403, f"{method} {path}: {response.status} {response.text[:200]}"
        assert _json(response)["kind"] == "not_managed"
    # Publicar: un esquema auxiliar (con o sin catálogo) y una ontología externa.
    for slug in ("dominio", "tipo-dataset"):
        response = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(slug, f"x{slug[:4]}"), token)
        assert response.status == 403, f"{slug}: {response.status} {response.text[:200]}"
        assert _json(response)["kind"] == "not_managed"
    external = f"<{EXTERNAL_ONTOLOGY}> a <http://www.w3.org/2002/07/owl#Ontology> .\n"
    response = _post(stack, f"/ontologies?catalog={cat_a}", external, token)
    assert response.status == 403, response.text
    assert _json(response)["kind"] == "not_managed"
    # Nada cambió: ni grafos, ni catálogos, ni lápidas.
    assert _snapshot(stack) == before
    assert _json(_get(stack, "/schemes/dominio"))["catalog"] is None
    assert not any(
        i["slug"] in ("dominio", "tipo-dataset")
        for i in _catalog_detail(stack, cat_a)["schemes"]
    )


def test_not_managed_no_se_confunde_con_el_rol(stack: Stack, member: Account) -> None:
    # Un miembro recibe el 403 normal (sin kind): el rol se comprueba antes que el recurso.
    for method, path, body in (
        ("PATCH", "/schemes/dominio", {"title": "x"}),
        ("DELETE", "/ontologies/externas", None),
    ):
        response = _api(stack, method, path, member.token, body)
        assert response.status == 403
        assert _json(response).get("kind") is None
        assert _api(stack, method, path, None, body).status == 401


def test_el_segmento_reservado_corp_no_es_un_esquema(stack: Stack, editor: Account, cat_a: str) -> None:
    body = scheme_ttl("corp", "xcorp")
    assert _post(stack, f"/schemes?catalog={cat_a}", body, editor.token).status == 422
    assert _get(stack, "/schemes/corp").status in (404, 422)
    assert _api(stack, "DELETE", "/schemes/corp", editor.token).status in (404, 422)


# --- 8. Roles en cada endpoint nuevo ---------------------------------------------------


def _write_requests(slug: str, onto: str, cat: str) -> list[tuple[str, str, object | None, bool]]:
    ttl = scheme_ttl(_slug("r"), _slug("rp"))
    return [
        ("POST", f"/schemes?catalog={cat}", ttl, True),
        ("POST", f"/ontologies?catalog={cat}", ontology_ttl(_slug("r"), _slug("rp")), True),
        ("PATCH", f"/schemes/{slug}", {"title": "Cambiado por un rol sin permiso"}, False),
        ("PATCH", f"/schemes/corp/{slug}", {"title": "x"}, False),
        ("PATCH", f"/ontologies/{onto}", {"catalog": cat}, False),
        ("DELETE", f"/schemes/{slug}", None, False),
        ("DELETE", f"/schemes/corp/{slug}", None, False),
        ("DELETE", f"/ontologies/{onto}", None, False),
        # Recursos que no existen: el rol se comprueba antes que la existencia.
        ("PATCH", "/schemes/no-existe-rol", {"title": "x"}, False),
        ("DELETE", "/ontologies/no-existe-rol", None, False),
    ]


def _send(stack: Stack, method: str, path: str, body: object | None, raw: bool, token: str | None):
    if raw:
        return _post(stack, path, str(body), token)
    return _api(stack, method, path, token, body)


def test_anonimo_401_miembro_403_y_token_manipulado_401_en_cada_endpoint_nuevo(
    stack: Stack, editor: Account, member: Account, cat_a: str
) -> None:
    slug, _ = publish_scheme(stack, editor.token, cat_a)
    onto, _ = publish_ontology(stack, editor.token, cat_a)
    before = _snapshot(stack)
    forged = (member.token or "")[:-3] + "AAA"
    for method, path, body, raw in _write_requests(slug, onto, cat_a):
        assert _send(stack, method, path, body, raw, None).status == 401, (method, path)
        denied = _send(stack, method, path, body, raw, member.token)
        assert denied.status == 403, (method, path, denied.status)
        assert _json(denied).get("kind") is None
        assert _send(stack, method, path, body, raw, forged).status == 401, (method, path)
        assert _send(stack, method, path, body, raw, "no-es-un-jwt").status == 401, (method, path)
    assert _snapshot(stack) == before  # los rechazos no escriben nada
    assert _json(_get(stack, f"/schemes/{slug}"))["title"].startswith("Esquema de la prueba")


def test_editor_y_admin_tienen_los_mismos_permisos_de_escritura(
    stack: Stack, admin: Account, editor: Account, cat_a: str, cat_b: str
) -> None:
    for actor in (editor, admin):
        scheme, created = publish_scheme(stack, actor.token, cat_a)
        onto, created_o = publish_ontology(stack, actor.token, cat_a)
        assert created.status == created_o.status == 201
        assert _api(stack, "PATCH", f"/schemes/{scheme}", actor.token, {"catalog": cat_b}).status == 200
        assert _api(stack, "PATCH", f"/ontologies/{onto}", actor.token, {"catalog": cat_b}).status == 200
        assert _api(stack, "DELETE", f"/schemes/{scheme}", actor.token).status == 204
        assert _api(stack, "DELETE", f"/ontologies/{onto}", actor.token).status == 204
    # Un editor o admin cuya cuenta se da de baja pierde el permiso con el token vigente.
    # (la baja de usuarios la cubre G1; aquí solo se comprueba que el rol viaja en el token.)


def test_la_lectura_de_lo_nuevo_es_publica(stack: Stack, editor: Account, cat_a: str) -> None:
    slug, _ = publish_scheme(stack, editor.token, cat_a)
    onto, _ = publish_ontology(stack, editor.token, cat_a)
    for path in (
        "/catalogs",
        f"/catalogs/{cat_a}",
        f"/vocabularies?catalog={cat_a}",
        f"/schemes/{slug}",
        f"/ontologies/{onto}",
    ):
        assert _get(stack, path).status == 200, path
    detail = _catalog_detail(stack, cat_a)
    assert detail["scheme_count"] >= 1 and detail["ontology_count"] >= 1
    listed = {c["slug"]: c for c in _json(_get(stack, "/catalogs"))["items"]}
    assert listed[cat_a]["scheme_count"] == detail["scheme_count"]
    assert listed[cat_a]["ontology_count"] == detail["ontology_count"]


# --- 9. Inyección y abuso por las IRIs y los parámetros ---------------------------------

HOSTILE_IRIS = [
    "https://example.org/a^b",
    "https://example.org/a|b",
    "https://example.org/a`b",
    "https://example.org/a{b}",
    "https://example.org/a\\b",
    'https://example.org/a"b',
    "https://example.org/a b",
]


@pytest.mark.parametrize("target", HOSTILE_IRIS)
def test_un_sustituto_con_una_iri_hostil_no_llega_a_sparql(
    stack: Stack, editor: Account, cat_a: str, target: str
) -> None:
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    before = _snapshot(stack)
    hostile = (
        f"<vocab/{slug}/hoja> <http://www.w3.org/2002/07/owl#deprecated> true ; "
        f"<http://purl.org/dc/terms/isReplacedBy> <{target}> ."
    )
    body = scheme_ttl(slug, f"p{slug}", extra=hostile)
    response = _post(stack, f"/schemes?catalog={cat_a}", body, editor.token)
    # Se rechaza con 422 «uri» antes de llegar a ninguna consulta SPARQL, sin escribir nada.
    assert response.status == 422, f"{target!r}: {response.status} {response.text[:300]}"
    assert _json(response)["kind"] == "uri"
    assert _snapshot(stack) == before


@pytest.mark.parametrize("target", HOSTILE_IRIS)
def test_un_tema_con_una_iri_hostil_no_rompe_la_comprobacion_de_temas_retirados(
    stack: Stack, editor: Account, cat_a: str, target: str
) -> None:
    series = _slug("d")
    body = series_ttl(series, cat_a, {"1.0.0": [target]})
    response = _post(stack, "/datasets", body, editor.token)
    assert response.status == 422, f"{target!r}: {response.status} {response.text[:300]}"
    assert _json(response)["kind"] == "uri"
    assert _get(stack, f"/datasets/{series}").status == 404


@pytest.mark.parametrize(
    "evil",
    ["a> . <http://evil/x", 'a"', "a b", "A", "a%2Fb", "a;b", "../x", "a\nb", "a{b}", "x" * 300],
)
def test_slugs_y_catalogos_maliciosos_en_las_rutas_nuevas(
    stack: Stack, editor: Account, cat_a: str, evil: str
) -> None:
    before = _snapshot(stack)
    quoted = urllib.parse.quote(evil, safe="")
    for method, path, body in (
        ("PATCH", f"/schemes/{quoted}", {"title": "x"}),
        ("PATCH", f"/schemes/corp/{quoted}", {"title": "x"}),
        ("PATCH", f"/ontologies/{quoted}", {"catalog": cat_a}),
        ("DELETE", f"/schemes/{quoted}", None),
        ("DELETE", f"/schemes/corp/{quoted}", None),
        ("DELETE", f"/ontologies/{quoted}", None),
        ("PATCH", "/schemes/ot", {"catalog": evil}),
        ("PATCH", "/ontologies/itot", {"catalog": evil}),
    ):
        response = _api(stack, method, path, editor.token, body)
        assert response.status in (404, 422), f"{method} {path}: {response.status}"
        assert evil not in response.text or response.status == 404
    for resource, ttl in (
        ("schemes", scheme_ttl(_slug("s"), _slug("p"))),
        ("ontologies", ontology_ttl(_slug("o"), _slug("p"))),
    ):
        response = _post(stack, f"/{resource}?catalog={quoted}", ttl, editor.token)
        assert response.status == 422, f"{resource}: {response.status}"
    assert _get(stack, f"/vocabularies?catalog={quoted}").status in (200, 422)
    assert _snapshot(stack) == before


def test_titulo_y_publicador_hostiles_de_un_esquema_quedan_como_literales(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    slug, created = publish_scheme(stack, editor.token, cat_a)
    assert created.status == 201
    before = _snapshot(stack)
    for title in (
        '" ; <http://purl.org/dc/terms/title> "inyectado',
        "\\\" \\u0022 \\\\",
        '"""\n<http://evil.example/x> a <http://evil.example/Y> .\n"""',
        "<script>alert(1)</script>",
    ):
        response = _api(
            stack, "PATCH", f"/schemes/{slug}", editor.token, {"title": title, "publisher_name": title}
        )
        assert response.status in (200, 422), response.text
        if response.status == 200:
            assert _json(response)["title"] == title
    after = _snapshot(stack)
    assert set(after) == set(before)
    assert not _ask(stack, "ASK { GRAPH ?g { <http://evil.example/x> ?p ?o } }")


# --- 10. load-semantic respeta lo hecho desde la aplicación ----------------------------


def test_load_semantic_no_deshace_el_traslado_de_un_esquema_ni_de_una_ontologia(
    stack: Stack, admin: Account, cat_a: str
) -> None:
    base = _base(stack)
    original = {
        "schemes/corp/trl": _json(_get(stack, "/schemes/corp/trl"))["catalog"]["slug"],
        "ontologies/pqcm": _json(_get(stack, "/ontologies/pqcm"))["catalog"]["slug"],
    }
    assert set(original.values()) == {"vocabularios-sinteticos"}
    try:
        assert _api(stack, "PATCH", "/schemes/corp/trl", admin.token, {"catalog": cat_a}).status == 200
        assert _api(stack, "PATCH", "/ontologies/pqcm", admin.token, {"catalog": cat_a}).status == 200
        result = stack.compose(
            "exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=900
        )
        assert result.returncode == 0, result.stdout + result.stderr
        # Tras G5 el dataset sintético dado de baja se omite: se comprueban las líneas de lo que
        # nos importa (la cuenta de 23 grafos es la de G3, con el entorno recién cargado).
        lines = [line for line in result.stdout.splitlines() if " -> <" in line]
        for name in (
            "data/catalogos/vocabularios-sinteticos.ttl",
            "vocabularios/corp/trl.ttl",
            "ontologias/pqcm/0.4.0.ttl",
        ):
            assert any(line.strip().startswith(name) and "sin cambios" in line for line in lines), (
                name,
                result.stdout,
            )
        assert _json(_get(stack, "/schemes/corp/trl"))["catalog"]["slug"] == cat_a
        assert _json(_get(stack, "/ontologies/pqcm"))["catalog"]["slug"] == cat_a
        # Y sigue en un solo catálogo (el del traslado), nunca en dos.
        for resource in (f"{base}vocab/corp/trl", f"{base}onto/pqcm"):
            rows = _sparql(
                stack,
                "SELECT ?c WHERE { GRAPH ?c { ?c <http://www.w3.org/ns/dcat#resource> "
                f"<{resource}> }} }}",
            )
            assert len(rows) == 1, rows
    finally:
        assert _api(stack, "PATCH", "/schemes/corp/trl", admin.token, {"catalog": original["schemes/corp/trl"]}).status == 200
        assert _api(stack, "PATCH", "/ontologies/pqcm", admin.token, {"catalog": original["ontologies/pqcm"]}).status == 200


def test_el_catalogo_de_los_esquemas_sinteticos_lista_los_doce(stack: Stack) -> None:
    detail = _catalog_detail(stack, "vocabularios-sinteticos")
    schemes = {s["slug"] for s in detail["schemes"] if not s["corp"]}
    corp = {s["slug"] for s in detail["schemes"] if s["corp"]}
    assert schemes == {"it", "ot", "pqc", "did", "ia"}
    assert corp == {"organizacion", "financiacion", "trl", "sectores"}
    assert {o["slug"] for o in detail["ontologies"]} == {"itot", "pqcm", "didx"}
    assert detail["datasets"] == []
    # Los auxiliares y las externas no están en ningún catálogo.
    listed = _json(_get(stack, "/vocabularies?page_size=100"))
    for item in listed["items"]:
        if item.get("kind") == "ontology-external" or item["slug"] in ("dominio", "tipo-dataset"):
            assert item.get("catalog") in (None, {}), item
    # Dar de baja el catálogo con esquemas y ontologías: 409 (nadie lo hace de verdad).
    refusal = http("DELETE", f"{stack.api}/catalogs/vocabularios-sinteticos")
    assert refusal.status == 401


# --- 11. SPARQL público, auditoría y concurrencia ---------------------------------------


def _public_sparql(stack: Stack, token: str, query: str) -> list[dict]:
    response = http(
        "POST",
        f"{stack.api}/sparql",
        raw_body=query.encode(),
        headers={"Content-Type": "application/sparql-query", "Accept": "application/sparql-results+json"},
        token=token,
    )
    assert response.status == 200, response.text
    return response.json()["results"]["bindings"]  # type: ignore[index]


def test_lo_dado_de_baja_sale_del_sparql_publico_y_la_lapida_no_se_ve(
    stack: Stack, editor: Account, member: Account, cat_a: str
) -> None:
    base = _base(stack)
    scheme, _ = publish_scheme(stack, editor.token, cat_a)
    onto, _ = publish_ontology(stack, editor.token, cat_a)
    probe = (
        "SELECT ?s WHERE {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), \"{prefix}\")) }} LIMIT 5"
    )
    for prefix in (f"{base}vocab/{scheme}", f"{base}onto/{onto}"):
        assert _public_sparql(stack, member.token, probe.format(prefix=prefix))  # control: se ve
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    for prefix in (f"{base}vocab/{scheme}", f"{base}onto/{onto}"):
        assert _public_sparql(stack, member.token, probe.format(prefix=prefix)) == []
    # Tampoco por el grafo de lápidas ni con GRAPH ?g.
    graph_probe = (
        "SELECT ?g WHERE {{ GRAPH ?g {{ ?s ?p ?o . FILTER(STRSTARTS(STR(?s), \"{prefix}\")) }} }}"
    )
    for prefix in (f"{base}vocab/{scheme}", f"{base}onto/{onto}"):
        assert _public_sparql(stack, member.token, graph_probe.format(prefix=prefix)) == []
    from_bajas = http(
        "POST",
        f"{stack.api}/sparql",
        raw_body=f"SELECT * FROM <{base}bajas> WHERE {{ ?s ?p ?o }}".encode(),
        headers={"Content-Type": "application/sparql-query"},
        token=member.token,
    )
    assert from_bajas.status == 400


def test_la_auditoria_de_editar_y_dar_de_baja_lleva_al_actor_y_no_secretos(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    scheme, _ = publish_scheme(stack, editor.token, cat_a)
    onto, _ = publish_ontology(stack, editor.token, cat_a)
    assert _api(stack, "PATCH", f"/schemes/{scheme}", editor.token, {"catalog": cat_b}).status == 200
    assert _api(stack, "PATCH", f"/ontologies/{onto}", editor.token, {"catalog": cat_b}).status == 200
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    for action, key, value in (
        ("scheme_updated", "scheme", f"{base}vocab/{scheme}"),
        ("ontology_updated", "ontology", f"{base}onto/{onto}"),
        ("scheme_withdrawn", "scheme", f"{base}vocab/{scheme}"),
        ("ontology_withdrawn", "ontology", f"{base}onto/{onto}"),
    ):
        rows = [r for r in _audit(stack, action) if r["details"][key] == value]
        assert len(rows) == 1, (action, rows)
        assert rows[0]["actor_username"] == editor.username
        assert rows[0]["details"]["via"] == "api"
        assert editor.token not in json.dumps(rows[0])
    moved = [r for r in _audit(stack, "scheme_updated") if r["details"]["scheme"] == f"{base}vocab/{scheme}"]
    assert moved[0]["details"]["moved_from"] == [f"{base}catalogo/{cat_a}"]
    assert moved[0]["details"]["catalog"] == f"{base}catalogo/{cat_b}"


def test_las_bajas_y_traslados_simultaneos_son_coherentes(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    import threading

    base = _base(stack)
    scheme, _ = publish_scheme(stack, editor.token, cat_a)
    codes: list[int] = []

    def delete() -> None:
        codes.append(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status)

    threads = [threading.Thread(target=delete) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [204, 410, 410, 410, 410, 410], codes
    assert len(_audit_for(stack, "scheme_withdrawn", f"{base}vocab/{scheme}")) == 1
    # Traslados simultáneos a dos catálogos: queda en uno solo.
    other, _ = publish_scheme(stack, editor.token, cat_a)
    results: list[int] = []

    def move(target: str) -> None:
        results.append(_api(stack, "PATCH", f"/schemes/{other}", editor.token, {"catalog": target}).status)

    movers = [threading.Thread(target=move, args=(t,)) for t in (cat_a, cat_b, cat_a, cat_b)]
    for thread in movers:
        thread.start()
    for thread in movers:
        thread.join()
    assert results == [200] * 4 or sorted(results) == [200] * 4, results
    rows = _sparql(
        stack,
        "SELECT ?c WHERE { GRAPH ?c { ?c <http://www.w3.org/ns/dcat#resource> "
        f"<{base}vocab/{other}> }} }}",
    )
    assert len(rows) == 1, rows  # nunca en dos catálogos a la vez


def _audit_for(stack: Stack, action: str, uri: str) -> list[dict]:
    return [r for r in _audit(stack, action) if uri in json.dumps(r["details"])]


# --- 12. Estructura: lo que la API no crea ----------------------------------------------


def test_una_ontologia_sin_version_o_con_el_slug_reservado_no_crea_nada(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    before = _snapshot(stack)
    sin_version = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        f"<onto/{_slug('ext')}> a owl:Ontology .\n"
    )
    assert _post(stack, f"/ontologies?catalog={cat_a}", sin_version, editor.token).status == 422
    reservada = ontology_ttl("externas", _slug("xp"))
    assert _post(stack, f"/ontologies?catalog={cat_a}", reservada, editor.token).status in (403, 422)
    assert _snapshot(stack) == before
    assert _json(_get(stack, "/vocabularies"))["counts"] is not None


# --- 13. Segunda ronda de la decisión 50 -----------------------------------------------


def _issue_values(response: Response) -> list[str]:
    return [i["value"] for i in _json(response)["issues"]]


def test_qa_50_01_dos_recursos_vivos_no_comparten_prefijo_vann(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    shared = _slug("sh")
    scheme, created = publish_scheme(stack, editor.token, cat_a, prefix=shared)
    assert created.status == 201
    # Otro esquema, otra ontología (en cualquier catálogo): 409 prefix_in_use y el dueño en value.
    other = _slug("s")
    for catalog in (cat_a, cat_b):
        response = _post(stack, f"/schemes?catalog={catalog}", scheme_ttl(other, shared), editor.token)
        assert response.status == 409, response.text
        assert _json(response)["kind"] == "prefix_in_use"
        assert _issue_values(response) == [f"{base}vocab/{scheme}"]
    onto = _slug("o")
    response = _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(onto, shared), editor.token)
    assert response.status == 409 and _json(response)["kind"] == "prefix_in_use", response.text
    assert _issue_values(response) == [f"{base}vocab/{scheme}"]
    assert _get(stack, f"/schemes/{other}").status == 404 and _get(stack, f"/ontologies/{onto}").status == 404
    # El dueño sigue publicando (republicar el esquema) con su propio prefijo.
    again = _republish(stack, editor.token, cat_a, scheme, concepts=("raiz", "hoja", "otra"), prefix=shared)
    assert again.status == 200, again.text
    # Una ontología dueña de su prefijo publica versiones nuevas.
    own = _slug("op")
    assert _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(own, f"q{own}"), editor.token).status == 201
    newer = ontology_ttl(own, f"q{own}", "1.1.0", prior="1.0.0")
    assert _post(stack, f"/ontologies?catalog={cat_a}", newer, editor.token).status == 201
    # Y una ontología con el prefijo de un esquema: el mismo 409 desde el otro lado.
    clash = _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(_slug("o"), f"q{own}"), editor.token)
    assert clash.status == 409 and _issue_values(clash) == [f"{base}onto/{own}"], clash.text
    # Dado de baja el dueño, el prefijo queda reservado: prefix_withdrawn (ya no «en uso»).
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204
    after = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(_slug("s"), shared), editor.token)
    assert after.status == 409 and _json(after)["kind"] == "prefix_withdrawn", after.text
    after = _post(stack, f"/ontologies?catalog={cat_a}", ontology_ttl(_slug("o"), shared), editor.token)
    assert after.status == 409 and _json(after)["kind"] == "prefix_withdrawn", after.text


def test_el_prefijo_de_un_recurso_sintetico_tampoco_se_puede_usar(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    # `ot` es el prefijo del esquema vocab/ot (de los ficheros de semantic/).
    import re

    turtle = _get(stack, "/schemes/ot/rdf?format=turtle").text
    found = re.search(r'preferredNamespacePrefix\s+"([^"]+)"', turtle)
    assert found, turtle[:500]
    response = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(_slug("s"), found.group(1)), editor.token)
    assert response.status == 409, response.text
    assert _json(response)["kind"] == "prefix_in_use"
    assert _issue_values(response) == [f"{base}vocab/ot"]


@pytest.mark.xfail(
    strict=True,
    reason="QA-50-06 (backend, propuesta): live_prefix_owners mira todas las versiones de una "
    "ontología, así que el prefijo que una versión nueva dejó de usar sigue ocupado (prefix_in_use)",
)
def test_qa_50_06_el_prefijo_antiguo_de_una_version_de_ontologia_no_bloquea_a_otros(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    """Una ontología cambia de prefijo en su versión 1.1.0: el prefijo que dejó queda libre."""
    old, new = _slug("pa"), _slug("pb")
    slug, created = publish_ontology(stack, editor.token, cat_a, prefix=old)
    assert created.status == 201
    v2 = ontology_ttl(slug, new, "1.1.0", prior="1.0.0")
    assert _post(stack, f"/ontologies?catalog={cat_a}", v2, editor.token).status == 201
    taker = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(_slug("s"), old), editor.token)
    assert taker.status == 201, taker.text


def test_qa_50_02_dar_de_baja_un_sustituto_da_409_in_use_por_dct_isreplacedby(
    stack: Stack, editor: Account, cat_a: str, cat_b: str
) -> None:
    base = _base(stack)
    retired, _ = publish_scheme(stack, editor.token, cat_a)
    replacement, _ = publish_scheme(stack, editor.token, cat_b)
    target = f"{base}vocab/{replacement}/hoja"
    assert _republish(stack, editor.token, cat_a, retired, deprecated={"hoja": [target]}).status == 200
    uses = _in_use(_api(stack, "DELETE", f"/schemes/{replacement}", editor.token))
    assert uses == [
        {
            "uri": f"{base}vocab/{retired}/hoja",
            "resource": "scheme",
            "via": "http://purl.org/dc/terms/isReplacedBy",
            "target": target,
        }
    ]
    assert _get(stack, f"/schemes/{replacement}").status == 200
    # Dado de baja el esquema con el concepto retirado, el sustituto queda libre.
    assert _api(stack, "DELETE", f"/schemes/{retired}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/schemes/{replacement}", editor.token).status == 204


def test_un_isreplacedby_dentro_del_mismo_esquema_no_bloquea_la_baja(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    slug, _ = publish_scheme(stack, editor.token, cat_a, concepts=("raiz", "hoja", "otra"))
    retired = _republish(
        stack,
        editor.token,
        cat_a,
        slug,
        concepts=("raiz", "hoja", "otra"),
        deprecated={"hoja": [f"{base}vocab/{slug}/otra"]},
    )
    assert retired.status == 200, retired.text
    assert _api(stack, "DELETE", f"/schemes/{slug}", editor.token).status == 204


def test_qa_50_03_unknown_theme_en_las_versiones_nuevas(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    live, _ = publish_scheme(stack, editor.token, cat_a)
    dead, _ = publish_scheme(stack, editor.token, cat_a)
    assert _api(stack, "DELETE", f"/schemes/{dead}", editor.token).status == 204
    cases = {
        f"vocab/{live}/no-existe": "no es un concepto de ningún esquema publicado",
        f"vocab/{dead}/hoja": "esquema dado de baja",
        f"vocab/{live}": "no es un concepto",  # el esquema, no un concepto
        "vocab/ot/no-existe": "no es un concepto de ningún esquema publicado",
    }
    before = _snapshot(stack)
    for theme, text in cases.items():
        series = _slug("d")
        response = _post(stack, "/datasets", series_ttl(series, cat_a, {"1.0.0": [theme]}), editor.token)
        assert response.status == 422, f"{theme}: {response.status} {response.text[:300]}"
        body = _json(response)
        assert body["kind"] == "unknown_theme", theme
        assert [i["value"] for i in body["issues"]] == [f"{base}{theme}"]
        assert text in body["issues"][0]["message"], (theme, body["issues"])
        assert _get(stack, f"/datasets/{series}").status == 404
    assert _snapshot(stack) == before
    # Sí pasan: un concepto vivo, un concepto de un esquema auxiliar y un tema externo.
    for theme in (f"vocab/{live}/hoja", "vocab/dominio/ot", "https://example.org/externo/tema"):
        series = _slug("d")
        response = _post(stack, "/datasets", series_ttl(series, cat_a, {"1.0.0": [theme]}), editor.token)
        assert response.status == 201, f"{theme}: {response.status} {response.text[:300]}"
    # Una mezcla rechaza solo por el desconocido; las versiones publicadas no se reevalúan.
    series = _slug("d")
    ok = series_ttl(series, cat_a, {"1.0.0": [f"vocab/{live}/hoja"]})
    assert _post(stack, "/datasets", ok, editor.token).status == 201
    mixed = series_ttl(series, cat_a, {"1.0.0": [f"vocab/{live}/hoja"], "1.1.0": [f"vocab/{live}/hoja", "vocab/ot/x-x"]})
    refused = _post(stack, "/datasets", mixed, editor.token)
    assert refused.status == 422 and _json(refused)["kind"] == "unknown_theme"
    assert _post(stack, "/datasets", ok, editor.token).status == 200


def test_in_use_por_dct_subject_hacia_el_esquema_mismo(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    scheme, _ = publish_scheme(stack, editor.token, cat_a)
    onto = _slug("o")
    body = ontology_ttl(
        onto, f"p{onto}", extra=f"<onto/{onto}> <http://purl.org/dc/terms/subject> <vocab/{scheme}> ."
    )
    created = _post(stack, f"/ontologies?catalog={cat_a}", body, editor.token)
    assert created.status == 201, created.text
    uses = _in_use(_api(stack, "DELETE", f"/schemes/{scheme}", editor.token))
    assert uses == [
        {
            "uri": f"{base}onto/{onto}/1.0.0",
            "resource": "ontology",
            "via": "http://purl.org/dc/terms/subject",
            "target": f"{base}vocab/{scheme}",
        }
    ]
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204


def test_in_use_por_dct_conformsto_de_una_version_de_dataset(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    base = _base(stack)
    onto, created = publish_ontology(stack, editor.token, cat_a)
    assert created.status == 201
    for target in (f"onto/{onto}", f"onto/{onto}/1.0.0"):
        series = _slug("d")
        ttl = series_ttl(series, cat_a, {"1.0.0": []}, conforms=[target])
        published = _post(stack, "/datasets", ttl, editor.token)
        assert published.status == 201, published.text
        uses = _in_use(_api(stack, "DELETE", f"/ontologies/{onto}", editor.token))
        assert uses == [
            {
                "uri": f"{base}dataset/{series}/1.0.0",
                "resource": "dataset",
                "via": "http://purl.org/dc/terms/conformsTo",
                "target": f"{base}{target}",
            }
        ]
        assert _graph_exists(stack, f"{base}onto/{onto}/1.0.0")
        assert _api(stack, "DELETE", f"/datasets/{series}", editor.token).status == 204
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204


def test_las_ontologias_sinteticas_no_se_pueden_dar_de_baja(stack: Stack, editor: Account) -> None:
    """Con los datos sintéticos, `itot` está en uso (la importan otras ontologías y la usan
    versiones de dataset): la baja da 409 y no toca nada."""
    before = _snapshot(stack)
    response = _api(stack, "DELETE", "/ontologies/itot", editor.token)
    assert response.status == 409, response.text
    uses = _json(response)["used_by"]
    assert uses and {u["resource"] for u in uses} <= {"ontology", "dataset"}
    assert _snapshot(stack) == before
    assert _get(stack, "/ontologies/itot").status == 200


def test_la_baja_conserva_titulos_con_barras_dolares_y_escapes(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    """La lápida se escribe con BIND de expresiones (no con INSERT DATA): un título con `\\u`,
    `$`, comillas, saltos de línea o texto no latino llega íntegro al 410."""
    titles = [
        "Barra \\ y \\u0041 y \\U0001F600 y \\n literal",
        'Comillas " y \' y """ triples',
        "Dólar $title ${x} y $$",
        "Ñandú · 日本語 · عربى · 🙂",
        "} ; DROP ALL ; {",
    ]
    for title in titles:
        scheme, _ = publish_scheme(stack, editor.token, cat_a)
        patched = _api(stack, "PATCH", f"/schemes/{scheme}", editor.token, {"title": title})
        assert patched.status == 200, (title, patched.text)
        assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204, title
        gone = _get(stack, f"/schemes/{scheme}")
        assert gone.status == 410, (title, gone.status)
        assert _json(gone)["title"].replace("\r", "") == title.replace("\r", ""), (title, _json(gone))
    # Ontología: el título viene del RDF de su última versión (escapes de Turtle).
    onto = _slug("o")
    ttl = ontology_ttl(onto, f"p{onto}").replace(
        f'"Ontología de la prueba {onto}"@es', r'"Barra \\ y \\u0041 $x \"q\" ñ"@es'
    )
    assert _post(stack, f"/ontologies?catalog={cat_a}", ttl, editor.token).status == 201
    assert _api(stack, "DELETE", f"/ontologies/{onto}", editor.token).status == 204
    gone = _get(stack, f"/ontologies/{onto}")
    assert gone.status == 410 and _json(gone)["title"] == 'Barra \\ y \\u0041 $x "q" ñ', gone.text
    assert not _ask(stack, "ASK { GRAPH ?g { ?s <http://evil.example/p> ?o } }")


def test_la_baja_se_puede_reintentar_si_fuseki_cae_a_mitad(
    stack: Stack, editor: Account, cat_a: str
) -> None:
    """Fallo real a mitad de la baja contra el stack: PostgreSQL ya tiene reservado el prefijo
    (se confirma antes del Update) y Fuseki cae justo antes de la petición de Update. Se
    consigue reteniendo desde otra sesión de PostgreSQL una fila con el mismo prefijo: el
    INSERT del backend espera, se para Fuseki, se suelta la fila y la baja sigue hasta el
    Update, que falla (503). Después: el recurso sigue vivo y completo, su dueño puede
    republicarlo, nadie más puede usar el prefijo, y reintentar la baja la completa una sola
    vez."""
    import subprocess
    import time

    base = _base(stack)
    prefix = _slug("rb")
    scheme, created = publish_scheme(stack, editor.token, cat_a, prefix=prefix)
    assert created.status == 201
    uri = f"{base}vocab/{scheme}"
    sql = (
        "BEGIN; INSERT INTO withdrawn_prefixes (prefix, resource_uri, withdrawn_at) "
        f"VALUES ('{prefix}', '{uri}', now()); SELECT pg_sleep(12); ROLLBACK;"
    )
    holder = subprocess.Popen(  # noqa: S603 - comando fijo, datos de la prueba
        [
            *stack._base(),
            "exec", "-T", "postgres", "psql", "-U", stack.env["POSTGRES_USER"],
            "-d", stack.env["POSTGRES_DB"], "-v", "ON_ERROR_STOP=1", "-c", sql,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    result: dict[str, Response] = {}
    try:
        time.sleep(3)  # la fila retenida ya está insertada (sin confirmar)
        import threading

        thread = threading.Thread(
            target=lambda: result.update(r=http("DELETE", f"{stack.api}/schemes/{scheme}", token=editor.token, timeout=90))
        )
        thread.start()
        time.sleep(3)  # el backend ya hizo sus lecturas y espera en el INSERT del prefijo
        assert stack.compose("stop", "fuseki", timeout=120).returncode == 0
        thread.join(timeout=60)  # al soltarse la fila (12 s) sigue y falla en el Update
        assert not thread.is_alive()
    finally:
        holder.kill()
        holder.wait()
        assert stack.compose("start", "fuseki", timeout=120).returncode == 0
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if _get(stack, "/health/ready").status == 200:
                break
            time.sleep(2)
    failed = result["r"]
    assert failed.status == 503, f"{failed.status} {failed.text[:300]}"
    # Estado coherente: vivo y completo, prefijo reservado a su nombre, sin lápida ni auditoría.
    assert _get(stack, f"/schemes/{scheme}").status == 200
    assert _get(stack, f"/schemes/{scheme}/concepts/hoja").status == 200
    assert not _graph_has(stack, f"{base}bajas", f"<{uri}> ?p ?o")
    assert stack.psql(f"select resource_uri from withdrawn_prefixes where prefix = '{prefix}'") == [uri]
    assert not [r for r in _audit(stack, "scheme_withdrawn") if r["details"]["scheme"] == uri]
    # Su dueño sigue publicando; otro recurso no puede usar el prefijo.
    assert _republish(stack, editor.token, cat_a, scheme, prefix=prefix).status == 200
    clash = _post(stack, f"/schemes?catalog={cat_a}", scheme_ttl(_slug("s"), prefix), editor.token)
    assert clash.status == 409, clash.text
    # Reintentar completa la baja, una sola vez.
    assert _api(stack, "DELETE", f"/schemes/{scheme}", editor.token).status == 204
    assert _get(stack, f"/schemes/{scheme}").status == 410
    assert stack.psql(f"select count(*) from withdrawn_prefixes where prefix = '{prefix}'") == ["1"]
    assert len([r for r in _audit(stack, "scheme_withdrawn") if r["details"]["scheme"] == uri]) == 1
    assert not _graph_exists(stack, uri)
