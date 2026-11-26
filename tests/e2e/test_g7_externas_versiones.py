"""Decisión 51 · versiones de las ontologías externas, de extremo a extremo.

Contra el Compose real (Fuseki, PostgreSQL y Pellet de verdad). Va después de G6 (por el nombre).
Cubre la sustitución entera (primera y segunda, con ``dcat:previousVersion``), la inmutabilidad
de las versiones anteriores, la resolución de URIs (303 y negociación), la visibilidad en SPARQL,
los errores y roles de cada endpoint, el prefijo reservado, ``load-semantic`` después de una
sustitución, las sustituciones concurrentes y las pruebas de seguridad (rol, ``BASE_URI``,
tamaño y tipo, inyección por los campos, SSRF por ``owl:imports`` y recorrido de rutas).

Reparto de las externas sintéticas (``semantic/ontologias/externas.ttl``): ``saref`` recibe las
sustituciones de la historia (y cambia de prefijo), ``sosa`` las de la robustez y la concurrencia,
y ``d3f`` no se sustituye nunca con éxito: solo recibe peticiones que se rechazan, así que sigue
siendo una externa sin versiones (la usan las pruebas de Playwright). Los ficheros son
sintéticos y pequeños; no se descarga ninguna ontología de internet. Cada prueba calcula el
``n`` esperado a partir de la API, así que también valen sobre un entorno que ya tenga versiones.

Solo datos ficticios. Cómo lanzarlas: ``tests/e2e/README.md``.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import threading
import urllib.parse

import pytest
from conftest import (
    Account,
    Response,
    Stack,
    create_account,
    create_catalog,
    fuseki_logged,
    fuseki_probe_url,
    http,
)

SAREF = "saref"
SAREF_IRI = "https://saref.etsi.org/core/"
SOSA = "sosa"
SOSA_IRI = "http://www.w3.org/ns/sosa/"
D3F = "d3f"
D3F_IRI = "http://d3fend.mitre.org/ontologies/d3fend.owl"
HTML = {"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"}
SPARQL_QUERY = {"Content-Type": "application/sparql-query"}
TURTLE = {"Content-Type": "text/turtle"}
PROV = "http://www.w3.org/ns/prov#"
DCAT = "http://www.w3.org/ns/dcat#"
DCT = "http://purl.org/dc/terms/"


# --- Utilidades ------------------------------------------------------------------------


def _json(response: Response) -> dict:
    return response.json()  # type: ignore[return-value]


def _base(stack: Stack) -> str:
    return stack.env["BASE_URI"]


def _version_uri(stack: Stack, slug: str, number: int) -> str:
    return f"{_base(stack)}onto/externas/{slug}/{number}"


def _tag() -> str:
    return secrets.token_hex(3)


def _prefix(label: str = "e") -> str:
    return f"{label}{secrets.token_hex(3)}"


def ontology_file(iri: str, tag: str, *, namespace: str | None = None, version: str = "1") -> str:
    """Ontología externa sintética: declara la IRI oficial y unas pocas entidades suyas."""
    ns = namespace or iri
    return f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{iri}> a owl:Ontology ; owl:versionInfo "publicador {version}" .
<{ns}Marcador{tag}> a owl:Class ; rdfs:label "Marcador {tag}"@en .
<{ns}Sensor{tag}> a owl:Class ; rdfs:subClassOf <{ns}Marcador{tag}> .
<{ns}Actuador{tag}> a owl:Class .
<{ns}tiene{tag}> a owl:ObjectProperty ; rdfs:domain <{ns}Sensor{tag}> .
"""


def multipart(
    parts: list[tuple[str, bytes | str, str | None, str | None]], boundary: str = "e2eBoundary7"
) -> tuple[bytes, dict[str, str]]:
    """``(cuerpo, cabeceras)`` de un multipart/form-data: ``(nombre, valor, fichero, tipo)``."""
    out = b""
    for name, value, filename, ctype in parts:
        out += f"--{boundary}\r\n".encode()
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        out += (disposition + "\r\n").encode()
        if ctype:
            out += f"Content-Type: {ctype}\r\n".encode()
        out += b"\r\n" + (value if isinstance(value, bytes) else value.encode()) + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return out, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def replace(
    stack: Stack,
    slug: str,
    token: str | None,
    *,
    iri: str,
    prefix: str,
    namespace: str | None = None,
    tag: str | None = None,
    text: str | bytes | None = None,
    filename: str = "ontologia.ttl",
    ctype: str | None = "text/turtle",
    title: str | None = None,
    extra: dict[str, str] | None = None,
    omit: tuple[str, ...] = (),
    timeout: float | None = 120,
) -> Response:
    """``POST /ontologies/externas/{slug}/versions`` con campos válidos por defecto."""
    tag = tag or _tag()
    fields: dict[str, str] = {
        "title": title if title is not None else f"Externa de la prueba {tag}",
        "prefix": prefix,
        "namespace": namespace or iri,
        "description": "Sustitución creada por la prueba e2e de la decisión 51.",
        "version_info": f"publicador {tag}",
        "publisher": "Editorial de pruebas",
        "version_notes": f"Notas de la sustitución {tag}.",
    }
    fields.update(extra or {})
    for name in omit:
        fields.pop(name, None)
    data = text if text is not None else ontology_file(iri, tag, namespace=namespace)
    parts: list[tuple[str, bytes | str, str | None, str | None]] = [
        (name, value, None, None) for name, value in fields.items()
    ]
    if "file" not in omit:
        parts.append(("file", data, filename, ctype))
    body, headers = multipart(parts)
    return http(
        "POST",
        f"{stack.api}/ontologies/externas/{slug}/versions",
        raw_body=body,
        headers=headers,
        token=token,
        timeout=timeout,
    )


def ficha(stack: Stack, slug: str) -> dict:
    response = http("GET", f"{stack.api}/ontologies/externas/{slug}")
    assert response.status == 200, response.text
    return _json(response)


def last_number(stack: Stack, slug: str) -> int:
    return max((v["number"] for v in ficha(stack, slug)["versions"]), default=0)


def _sparql_fuseki(stack: Stack, query: str) -> list[dict]:
    response = http(
        "POST",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/sparql",
        form={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )
    assert response.status == 200, response.text
    body = _json(response)
    return body["results"]["bindings"] if "results" in body else [body]  # type: ignore[index]


def _ask(stack: Stack, query: str) -> bool:
    return bool(_sparql_fuseki(stack, query)[0]["boolean"])


def _graph_triples(stack: Stack, graph: str) -> list[tuple[str, str, str]]:
    rows = _sparql_fuseki(
        stack,
        f"SELECT ?s ?p ?o WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }} ORDER BY ?s ?p ?o",
    )
    return [(r["s"]["value"], r["p"]["value"], r["o"]["value"]) for r in rows]


def _graph_exists(stack: Stack, graph: str) -> bool:
    return _ask(stack, f"ASK {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}")


def _external_graphs(stack: Stack) -> list[str]:
    base = f"{_base(stack)}onto/externas/"
    rows = _sparql_fuseki(
        stack,
        "SELECT DISTINCT ?g WHERE { GRAPH ?g { ?s ?p ?o } "
        f'FILTER(STRSTARTS(STR(?g), "{base}")) }} ORDER BY ?g',
    )
    return [r["g"]["value"] for r in rows]


def _reference_value(stack: Stack, ontology: str, predicate: str) -> list[str]:
    rows = _sparql_fuseki(
        stack,
        f"SELECT ?o WHERE {{ GRAPH <{_base(stack)}onto/externas> {{ <{ontology}> <{predicate}> ?o }} }}",
    )
    return sorted(r["o"]["value"] for r in rows)


def _audit_count(stack: Stack, action: str) -> int:
    assert action.replace("_", "").isalpha()
    return int(stack.psql(f"select count(*) from audit_events where action = '{action}'")[0])


def _state(stack: Stack) -> tuple[list[str], int]:
    """Instantánea de lo que un rechazo no puede cambiar: grafos de externas y auditoría."""
    return _external_graphs(stack), _audit_count(stack, "external_ontology_replaced")


def _get(stack: Stack, path: str, **kwargs: object) -> Response:
    return http("GET", f"{stack.api}{path}", **kwargs)  # type: ignore[arg-type]


def _frontend(stack: Stack, path: str) -> str:
    return f"{stack.env['FRONTEND_BASE_URL']}{path}"


# --- Fixtures --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def editor(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "editor")


@pytest.fixture(scope="module")
def member(stack: Stack, admin: Account) -> Account:
    return create_account(stack, admin, "miembro")


@pytest.fixture(scope="module")
def history(stack: Stack, editor: Account, admin: Account) -> dict:
    """Las dos primeras sustituciones de ``saref`` (editor y admin) y lo que había antes."""
    before = ficha(stack, SAREF)
    base = max((v["number"] for v in before["versions"]), default=0)
    snapshot_before = (
        _graph_triples(stack, _version_uri(stack, SAREF, base)) if base else []
    )
    first_tag, second_tag = _tag(), _tag()
    first = replace(
        stack, SAREF, editor.token, iri=SAREF_IRI, prefix=SAREF, tag=first_tag, title="Primera"
    )
    assert first.status == 201, first.text
    snapshot_first = _graph_triples(stack, _version_uri(stack, SAREF, base + 1))
    rdf_first = _get(stack, f"/ontologies/externas/{SAREF}/rdf?version={base + 1}&format=turtle")
    # La segunda cambia de prefijo: el que deja de usar queda reservado (más abajo).
    new_prefix = _prefix("sar")
    second = replace(
        stack,
        SAREF,
        admin.token,
        iri=SAREF_IRI,
        prefix=new_prefix,
        tag=second_tag,
        title="Segunda",
        extra={"version_info": "[VERSIÓN]"},
    )
    assert second.status == 201, second.text
    return {
        "base": base,
        "before": before,
        "snapshot_before": snapshot_before,
        "first": _json(first),
        "second": _json(second),
        "first_tag": first_tag,
        "second_tag": second_tag,
        "snapshot_first": snapshot_first,
        "rdf_first": rdf_first.text,
        "new_prefix": new_prefix,
    }


# --- Sustitución: primera y segunda ----------------------------------------------------


def test_la_primera_sustitucion_crea_la_version_con_su_registro(stack: Stack, history: dict) -> None:
    first = history["first"]
    n = history["base"] + 1
    assert first["number"] == n
    assert first["version"] == str(n)
    assert first["slug"] == SAREF
    assert first["uri"] == SAREF_IRI
    assert first["version_uri"] == _version_uri(stack, SAREF, n) == first["graph"]
    expected_previous = _version_uri(stack, SAREF, n - 1) if n > 1 else None
    assert first["previous_version"] == expected_previous
    assert first["triples"] > 5
    assert first["metrics"]["classes"] == 3
    assert first["metrics"]["object_properties"] == 1
    assert first["consistency"]["reasoner"] == "Pellet"
    assert first["consistency"]["consistent"] is True
    assert first["profile"]["name"].startswith("OWL 2")

    version = first["version_uri"]
    triples = set(_graph_triples(stack, version))
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    assert (version, rdf_type, f"{PROV}Entity") in triples
    assert (version, f"{DCT}isVersionOf", SAREF_IRI) in triples
    assert (version, f"{DCAT}version", str(n)) in triples
    assert any(s == version and p == f"{PROV}generatedAtTime" for s, p, _ in triples)
    # El fichero oficial está en el mismo grafo (sus entidades, bajo la IRI oficial).
    assert any(s.startswith(SAREF_IRI + "Marcador") for s, _, _ in triples)
    # El registro nunca se declara owl:Ontology ni lleva owl:versionIRI.
    owl = "http://www.w3.org/2002/07/owl#"
    assert (version, rdf_type, f"{owl}Ontology") not in triples
    assert not any(s == version and p == f"{owl}versionIRI" for s, p, _ in triples)


def test_la_segunda_sustitucion_enlaza_con_la_primera(stack: Stack, history: dict) -> None:
    first, second = history["first"], history["second"]
    n = history["base"] + 2
    assert second["number"] == n
    assert second["previous_version"] == first["version_uri"] == _version_uri(stack, SAREF, n - 1)
    triples = set(_graph_triples(stack, second["version_uri"]))
    for predicate in (f"{DCAT}previousVersion", f"{PROV}wasRevisionOf"):
        assert (second["version_uri"], predicate, first["version_uri"]) in triples
    # El placeholder [VERSIÓN] no se escribe como owl:versionInfo del registro.
    owl_info = "http://www.w3.org/2002/07/owl#versionInfo"
    assert not any(s == second["version_uri"] and p == owl_info for s, p, _ in triples)

    # La referencia lista todas las versiones y la actual es la última.
    has_version = _reference_value(stack, SAREF_IRI, f"{DCAT}hasVersion")
    assert second["version_uri"] in has_version and first["version_uri"] in has_version
    assert _reference_value(stack, SAREF_IRI, f"{DCAT}hasCurrentVersion") == [
        second["version_uri"]
    ]
    # La referencia no duplica nada: un solo título, un solo prefijo.
    assert len(_reference_value(stack, SAREF_IRI, f"{DCT}title")) == 1
    assert _reference_value(stack, SAREF_IRI, "http://purl.org/vocab/vann/preferredNamespacePrefix") == [
        history["new_prefix"]
    ]


def test_la_ficha_lista_las_versiones_y_la_actual(stack: Stack, history: dict) -> None:
    detail = ficha(stack, SAREF)
    n = history["base"] + 2
    assert detail["slug"] == SAREF
    assert detail["uri"] == SAREF_IRI
    assert detail["kind"] == "external" and detail["status"] == "referenced"
    assert detail["title"] == "Segunda"
    assert detail["prefix"] == history["new_prefix"]
    numbers = [v["number"] for v in detail["versions"]]
    assert numbers == sorted(numbers, reverse=True)
    assert numbers[:2] == [n, n - 1]
    assert detail["current_version"]["number"] == n
    assert [v["current"] for v in detail["versions"]].count(True) == 1
    assert detail["versions"][0]["current"] is True
    assert detail["versions"][0]["previous_version"] == _version_uri(stack, SAREF, n - 1)
    assert detail["versions"][0]["metrics"]["classes"] == 3
    assert detail["versions"][1]["notes"] == f"Notas de la sustitución {history['first_tag']}."
    # La ficha de una externa nunca sustituida: sin versiones ni métricas.
    untouched = ficha(stack, D3F)
    assert untouched["versions"] == [] and untouched["current_version"] is None


def test_las_versiones_anteriores_no_cambian(stack: Stack, history: dict) -> None:
    first_uri = history["first"]["version_uri"]
    assert _graph_triples(stack, first_uri) == history["snapshot_first"]
    n_first = history["base"] + 1
    rdf = _get(stack, f"/ontologies/externas/{SAREF}/rdf?version={n_first}&format=turtle")
    assert rdf.status == 200
    assert rdf.text == history["rdf_first"]
    # Su ficha sigue diciendo lo que dijo: la 1ª no es la actual y conserva su métrica.
    row = next(v for v in ficha(stack, SAREF)["versions"] if v["number"] == n_first)
    assert row["current"] is False and row["metrics"]["classes"] == 3
    if history["base"]:
        assert _graph_triples(stack, _version_uri(stack, SAREF, history["base"])) == (
            history["snapshot_before"]
        )


def test_el_rdf_de_la_ontologia_por_defecto_es_la_version_actual(
    stack: Stack, history: dict
) -> None:
    rdf = _get(stack, f"/ontologies/externas/{SAREF}/rdf?format=turtle")
    assert rdf.status == 200
    assert f"Marcador{history['second_tag']}" in rdf.text
    assert f"Marcador{history['first_tag']}" not in rdf.text
    old = _get(stack, f"/ontologies/externas/{SAREF}/rdf?version={history['base'] + 1}")
    assert f"Marcador{history['first_tag']}" in old.text
    assert _get(stack, f"/ontologies/externas/{SAREF}/rdf?version=99999").status == 404
    assert _get(stack, f"/ontologies/externas/{D3F}/rdf").status == 404
    assert _get(stack, f"/ontologies/externas/{SAREF}/rdf?version=01").status == 422


def test_la_auditoria_registra_cada_sustitucion_sin_secretos(stack: Stack, history: dict) -> None:
    rows = [
        json.loads(line)
        for line in stack.psql(
            "select row_to_json(a) from audit_events a "
            "where a.action = 'external_ontology_replaced' order by a.id"
        )
    ]
    assert len(rows) >= 2
    details = rows[-1]["details"]
    assert details["version"] == str(history["base"] + 2)
    assert details["previous_version"] == history["first"]["version_uri"]
    serialized = json.dumps(rows)
    for secret in stack.sensitive.values():
        assert secret not in serialized
    assert "Marcador" not in serialized  # nada del contenido del fichero


# --- Resolución de URIs ----------------------------------------------------------------


def test_la_uri_de_una_version_negocia_el_contenido(stack: Stack, history: dict) -> None:
    n = history["base"] + 2
    path = f"/onto/externas/{SAREF}/{n}"
    expected = _frontend(stack, f"/ontologias/externas/{SAREF}?version={n}")
    for accept in (None, "*/*", "text/html", HTML["Accept"]):
        headers = {"Accept": accept} if accept else {}
        response = _get(stack, path, headers=headers, follow_redirects=False)
        assert response.status == 303, (accept, response.text)
        assert response.headers["location"] == expected
    for accept, marker in (
        ("text/turtle", f"Marcador{history['second_tag']}"),
        ("application/ld+json", f"Marcador{history['second_tag']}"),
        ("application/rdf+xml", f"Marcador{history['second_tag']}"),
    ):
        response = _get(stack, path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status == 200, (accept, response.text[:200])
        assert accept in response.headers["content-type"]
        assert marker in response.text
    first = _get(
        stack,
        f"/onto/externas/{SAREF}/{n - 1}",
        headers={"Accept": "text/turtle"},
        follow_redirects=False,
    )
    assert first.status == 200 and f"Marcador{history['first_tag']}" in first.text
    for missing in (f"/onto/externas/{SAREF}/{n + 5}", "/onto/externas/no-existe/1"):
        for accept in ("text/turtle", "text/html"):
            response = _get(stack, missing, headers={"Accept": accept}, follow_redirects=False)
            assert response.status == 404, (missing, accept)


def test_la_uri_de_la_serie_lleva_a_la_ficha_o_a_la_version_actual(
    stack: Stack, history: dict
) -> None:
    path = f"/onto/externas/{SAREF}"
    ficha_url = _frontend(stack, f"/ontologias/externas/{SAREF}")
    for accept in (None, "*/*", "text/html", HTML["Accept"]):
        response = _get(
            stack, path, headers={"Accept": accept} if accept else {}, follow_redirects=False
        )
        assert response.status == 303, accept
        assert response.headers["location"] == ficha_url
    n = history["base"] + 2
    for accept in ("text/turtle", "application/ld+json", "application/rdf+xml"):
        response = _get(stack, path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status == 303, accept
        assert response.headers["location"] == _version_uri(stack, SAREF, n)
        assert "accept" in response.headers.get("vary", "").lower()
    # Una externa sin versiones: la ficha en HTML; sin versión que servir en RDF, 404.
    html = _get(stack, f"/onto/externas/{D3F}", headers=HTML, follow_redirects=False)
    assert html.status == 303
    assert html.headers["location"] == _frontend(stack, f"/ontologias/externas/{D3F}")
    rdf = _get(
        stack, f"/onto/externas/{D3F}", headers={"Accept": "text/turtle"}, follow_redirects=False
    )
    assert rdf.status == 404
    assert _get(stack, "/onto/externas/no-existe", headers=HTML, follow_redirects=False).status == 404


def test_las_versiones_se_ven_en_sparql(stack: Stack, history: dict) -> None:
    n = history["base"] + 2
    version = _version_uri(stack, SAREF, n)
    ask = f"ASK {{ GRAPH <{version}> {{ <{version}> a <{PROV}Entity> }} }}"
    public = http("POST", f"{stack.api}/sparql", raw_body=ask.encode(), headers=SPARQL_QUERY)
    assert public.status == 200, public.text
    assert _json(public)["boolean"] is True
    select = (
        "SELECT ?g WHERE { GRAPH ?g { ?v a <" + PROV + "Entity> } "
        'FILTER(STRSTARTS(STR(?g), "' + _base(stack) + f'onto/externas/{SAREF}/")) }}'
    )
    rows = http("POST", f"{stack.api}/sparql", raw_body=select.encode(), headers=SPARQL_QUERY)
    assert rows.status == 200, rows.text
    graphs = {b["g"]["value"] for b in _json(rows)["results"]["bindings"]}  # type: ignore[index]
    assert {_version_uri(stack, SAREF, k) for k in range(1, n + 1)} <= graphs
    # Los datos del fichero oficial también se consultan (la versión actual).
    marker = f"{SAREF_IRI}Marcador{history['second_tag']}"
    ask_class = f"ASK {{ GRAPH <{version}> {{ <{marker}> a <http://www.w3.org/2002/07/owl#Class> }} }}"
    assert _json(
        http("POST", f"{stack.api}/sparql", raw_body=ask_class.encode(), headers=SPARQL_QUERY)
    )["boolean"] is True


# --- Prefijo reservado -----------------------------------------------------------------


def test_el_prefijo_que_una_version_deja_de_usar_queda_reservado(
    stack: Stack, history: dict, editor: Account
) -> None:
    """``saref`` dejó de usar su prefijo en la 2ª: otra externa no puede tomarlo, ni una
    ontología propia, pero la propia ``saref`` sí puede volver a él."""
    state = _state(stack)
    response = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=SAREF)
    assert response.status == 409, response.text
    assert _json(response)["kind"] in ("prefix_in_use", "prefix_withdrawn")
    assert _json(response)["issues"][0]["value"] == SAREF_IRI
    assert _state(stack) == state

    # Una propia que pida ese prefijo también recibe 409 (QA-50-06: reglas 7 y 14).
    catalog = f"g7-{secrets.token_hex(3)}"
    assert create_catalog(stack, editor.token, catalog).status == 201
    own = f"g7o{secrets.token_hex(3)}"
    ttl = f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
<onto/{own}> a owl:Ontology ; owl:versionIRI <onto/{own}/1.0.0> ; owl:versionInfo "1.0.0" ;
    dct:type <vocab/tipo-dataset/sintetico> ; adms:status <http://purl.org/adms/status/UnderDevelopment> ;
    dct:title "Ontología {own}"@es ; dct:description "Prueba de la 51."@es ;
    vann:preferredNamespacePrefix "{SAREF}" ; vann:preferredNamespaceUri <onto/{own}#> .
"""
    clash = http(
        "POST",
        f"{stack.api}/ontologies?catalog={catalog}",
        raw_body=ttl.encode(),
        headers=TURTLE,
        token=editor.token,
    )
    assert clash.status == 409, clash.text
    assert _json(clash)["kind"] == "prefix_in_use"

    # Volver al suyo es una sustitución más, con el slug de siempre.
    n = last_number(stack, SAREF)
    back = replace(stack, SAREF, editor.token, iri=SAREF_IRI, prefix=SAREF)
    assert back.status == 201, back.text
    assert _json(back)["number"] == n + 1 and _json(back)["slug"] == SAREF
    assert ficha(stack, SAREF)["prefix"] == SAREF
    # Y el prefijo intermedio, que ya no usa, sigue reservado para ella.
    other = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=history["new_prefix"])
    assert other.status == 409 and _json(other)["kind"] == "prefix_in_use"


def test_prefijo_de_un_recurso_propio_vivo_o_dado_de_baja(stack: Stack, editor: Account) -> None:
    catalog = f"g7b-{secrets.token_hex(3)}"
    assert create_catalog(stack, editor.token, catalog).status == 201
    own = f"g7p{secrets.token_hex(3)}"
    prefix = _prefix("own")
    ttl = f"""
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix dct: <http://purl.org/dc/terms/> .
@prefix adms: <http://www.w3.org/ns/adms#> .
@prefix vann: <http://purl.org/vocab/vann/> .
<onto/{own}> a owl:Ontology ; owl:versionIRI <onto/{own}/1.0.0> ; owl:versionInfo "1.0.0" ;
    dct:type <vocab/tipo-dataset/sintetico> ; adms:status <http://purl.org/adms/status/UnderDevelopment> ;
    dct:title "Ontología {own}"@es ; dct:description "Prueba de la 51."@es ;
    vann:preferredNamespacePrefix "{prefix}" ; vann:preferredNamespaceUri <onto/{own}#> .
"""
    created = http(
        "POST",
        f"{stack.api}/ontologies?catalog={catalog}",
        raw_body=ttl.encode(),
        headers=TURTLE,
        token=editor.token,
    )
    assert created.status == 201, created.text
    state = _state(stack)
    live = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=prefix)
    assert live.status == 409 and _json(live)["kind"] == "prefix_in_use", live.text
    assert _json(live)["issues"][0]["value"].endswith(f"onto/{own}")
    withdrawn = http("DELETE", f"{stack.api}/ontologies/{own}", token=editor.token)
    assert withdrawn.status == 204, withdrawn.text
    gone = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=prefix)
    assert gone.status == 409 and _json(gone)["kind"] == "prefix_withdrawn", gone.text
    assert _state(stack) == state


# --- Errores y roles -------------------------------------------------------------------


def test_errores_de_la_sustitucion_y_rechazos_sin_escribir(
    stack: Stack, editor: Account, history: dict
) -> None:
    state = _state(stack)
    pfx = _prefix("err")

    def kind(response: Response, status: int, expected: str | None = None) -> dict:
        assert response.status == status, response.text
        body = _json(response)
        if expected:
            assert body["kind"] == expected, body
        return body

    # 404: una externa que no existe (con un fichero válido).
    kind(replace(stack, "no-existe", editor.token, iri=D3F_IRI, prefix=pfx), 404)

    # 422 syntax: Turtle que no se analiza; JSON-LD roto.
    syntax = kind(
        replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, text="esto no es turtle {{"),
        422,
        "syntax",
    )
    assert syntax["issues"] is not None
    kind(
        replace(
            stack,
            D3F,
            editor.token,
            iri=D3F_IRI,
            prefix=pfx,
            text='{"@id": ',
            filename="o.jsonld",
            ctype="application/ld+json",
        ),
        422,
        "syntax",
    )

    # 422 structure: el fichero no declara la ontología (o declara otra IRI oficial).
    kind(
        replace(
            stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, text=ontology_file(SOSA_IRI, "x")
        ),
        422,
        "structure",
    )
    kind(
        replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, text="<urn:a:a> a <urn:a:B> ."),
        422,
        "structure",
    )
    # Un fichero vacío no es RDF: syntax.
    kind(replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, text=""), 422, "syntax")

    # 422 structure: campos del formulario, con un problema por campo.
    for field, value in (
        ("title", "   "),
        ("prefix", "Mal Prefijo"),
        ("prefix", "9abc"),
        ("namespace", "no es una uri"),
        ("namespace", "http://x.example/>"),
        ("title", "con\x07control"),
        ("description", "x" * 6000),
    ):
        body = kind(
            replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, extra={field: value}),
            422,
            "structure",
        )
        assert field in {issue["path"] for issue in body["issues"]}, (field, body)
    for missing in ("title", "prefix", "namespace"):
        body = kind(
            replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, omit=(missing,)),
            422,
            "structure",
        )
        assert missing in {issue["path"] for issue in body["issues"]}

    # 422 uri: el fichero describe recursos bajo BASE_URI.
    inside = f"{_base(stack)}onto/externas/saref/1"
    forged = ontology_file(D3F_IRI, "uri") + f"<{inside}> a <http://www.w3.org/ns/prov#Entity> .\n"
    body = kind(replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, text=forged), 422, "uri")
    assert any(issue["focus_node"] == inside for issue in body["issues"])
    own_graph = f"{_base(stack)}dataset/x"
    kind(
        replace(
            stack,
            D3F,
            editor.token,
            iri=D3F_IRI,
            prefix=pfx,
            text=ontology_file(D3F_IRI, "uri") + f"<{own_graph}> a <urn:t:T> .\n",
        ),
        422,
        "uri",
    )

    # 400: sin fichero, campos repetidos o no admitidos, multipart mal formado.
    kind(replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, omit=("file",)), 400)
    kind(replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, extra={"intruso": "x"}), 400)
    body, headers = multipart(
        [
            ("file", ontology_file(D3F_IRI, "d"), "o.ttl", "text/turtle"),
            ("file", ontology_file(D3F_IRI, "d"), "o.ttl", "text/turtle"),
            ("title", "t", None, None),
            ("prefix", pfx, None, None),
            ("namespace", D3F_IRI, None, None),
        ]
    )
    dup_file = http(
        "POST",
        f"{stack.api}/ontologies/externas/{D3F}/versions",
        raw_body=body,
        headers=headers,
        token=editor.token,
    )
    kind(dup_file, 400)
    body, headers = multipart(
        [
            ("file", ontology_file(D3F_IRI, "d"), "o.ttl", "text/turtle"),
            ("title", "t", None, None),
            ("title", "otra", None, None),
            ("prefix", pfx, None, None),
            ("namespace", D3F_IRI, None, None),
        ]
    )
    dup_title = http(
        "POST",
        f"{stack.api}/ontologies/externas/{D3F}/versions",
        raw_body=body,
        headers=headers,
        token=editor.token,
    )
    kind(dup_title, 400)
    broken = http(
        "POST",
        f"{stack.api}/ontologies/externas/{D3F}/versions",
        raw_body=b"--e2eBoundary7\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nx",
        headers={"Content-Type": "multipart/form-data; boundary=e2eBoundary7"},
        token=editor.token,
    )
    assert broken.status in (400, 422), broken.text

    # 415: no es multipart, o el fichero no es Turtle ni JSON-LD.
    wrong_type = http(
        "POST",
        f"{stack.api}/ontologies/externas/{D3F}/versions",
        json_body={"title": "x"},
        token=editor.token,
    )
    assert wrong_type.status == 415, wrong_type.text
    for filename, ctype in (
        ("o.rdf", "application/rdf+xml"),
        ("o.exe", "application/octet-stream"),
        ("o.txt", "text/plain"),
        ("o", None),
    ):
        kind(
            replace(
                stack, D3F, editor.token, iri=D3F_IRI, prefix=pfx, filename=filename, ctype=ctype
            ),
            415,
        )

    assert _state(stack) == state
    assert ficha(stack, D3F)["versions"] == []


def test_la_sustitucion_exige_editor_o_admin(stack: Stack, editor: Account, member: Account) -> None:
    state = _state(stack)
    pfx = _prefix("rol")
    anonymous = replace(stack, D3F, None, iri=D3F_IRI, prefix=pfx)
    assert anonymous.status == 401
    forbidden = replace(stack, D3F, member.token, iri=D3F_IRI, prefix=pfx)
    assert forbidden.status == 403
    assert "kind" not in _json(forbidden) or _json(forbidden)["kind"] is None
    # Token manipulado: firma alterada, sin firma (alg none) y basura.
    token = editor.token or ""
    head, payload, signature = token.split(".")
    tampered = f"{head}.{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    for bad in (tampered, f"{head}.{payload}.", "no.es.un-jwt", "x"):
        assert replace(stack, D3F, bad, iri=D3F_IRI, prefix=pfx).status == 401, bad
    # La comprobación de rol va antes que el cuerpo: sin permiso, ni se lee un cuerpo enorme.
    huge = b"x" * (11 * 1024 * 1024)
    try:
        big = replace(stack, D3F, member.token, iri=D3F_IRI, prefix=pfx, text=huge)
    except OSError:
        pass  # el servidor cierra la conexión sin leer el cuerpo: tampoco vale como lectura
    else:
        assert big.status == 403, big.status
    assert _state(stack) == state


def test_patch_y_delete_de_una_externa_son_siempre_not_managed(
    stack: Stack, admin: Account, editor: Account, member: Account
) -> None:
    state = _state(stack)
    for slug in (SAREF, D3F, "no-existe"):
        for method, body in (("PATCH", {"title": "Otro"}), ("DELETE", None)):
            path = f"{stack.api}/ontologies/externas/{slug}"
            assert http(method, path, json_body=body).status == 401, (method, slug)
            forbidden = http(method, path, json_body=body, token=member.token)
            assert forbidden.status == 403
            assert _json(forbidden).get("kind") != "not_managed", "el miembro no llega a ver no_managed"
            for account in (editor, admin):
                response = http(method, path, json_body=body, token=account.token)
                assert response.status == 403, (method, slug, account.role, response.text)
                assert _json(response)["kind"] == "not_managed"
    assert _state(stack) == state
    assert ficha(stack, SAREF)["title"] is not None  # sigue en pie
    assert _reference_value(stack, D3F_IRI, f"{DCT}title")  # y D3FEND, sin tocar


# --- load-semantic ---------------------------------------------------------------------


def test_load_semantic_despues_de_una_sustitucion_no_la_pisa(
    stack: Stack, history: dict
) -> None:
    del history
    before = ficha(stack, SAREF)
    graphs = _external_graphs(stack)
    audit = _audit_count(stack, "external_ontology_replaced")
    d3f_before = _reference_value(stack, D3F_IRI, f"{DCT}title")
    sample = _graph_triples(stack, before["versions"][-1]["uri"])
    result = stack.compose("exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=900)
    assert result.returncode == 0, result.stdout + result.stderr
    after = ficha(stack, SAREF)
    for key in ("title", "prefix", "namespace", "description", "publisher", "version", "uri"):
        assert after[key] == before[key], key
    assert [v["uri"] for v in after["versions"]] == [v["uri"] for v in before["versions"]]
    assert after["current_version"]["uri"] == before["current_version"]["uri"]
    assert after["current_version"]["metrics"] == before["current_version"]["metrics"]
    # La semilla (externas.ttl) no devuelve el título de saref ni quita sus versiones.
    assert "SAREF · Smart Applications" not in json.dumps(after["title"])
    assert _external_graphs(stack) == graphs
    assert _graph_triples(stack, before["versions"][-1]["uri"]) == sample
    assert len(_reference_value(stack, SAREF_IRI, f"{DCAT}hasVersion")) == len(before["versions"])
    assert _reference_value(stack, SAREF_IRI, f"{DCAT}hasCurrentVersion") == [
        before["current_version"]["uri"]
    ]
    assert len(_reference_value(stack, SAREF_IRI, f"{DCT}title")) == 1
    # No crea ni cambia versiones (ni auditoría de sustituciones) y deja intactas las externas
    # sin versiones.
    assert _audit_count(stack, "external_ontology_replaced") == audit
    assert _reference_value(stack, D3F_IRI, f"{DCT}title") == d3f_before
    assert ficha(stack, D3F)["versions"] == []
    # Idempotente: una segunda carga sigue sin tocarla.
    again = stack.compose("exec", "-T", "backend", "python", "-m", "app.cli", "load-semantic", timeout=900)
    assert again.returncode == 0, again.stdout + again.stderr
    assert ficha(stack, SAREF)["title"] == before["title"]


# --- Robustez y concurrencia -----------------------------------------------------------


def test_un_grafo_huerfano_de_una_sustitucion_a_medias_se_sobrescribe(
    stack: Stack, editor: Account
) -> None:
    """Un grafo ``n+1`` que ninguna referencia lista (fallo a medias) no aparece en la API y la
    siguiente sustitución lo reemplaza (reintento seguro)."""
    n = last_number(stack, SOSA) + 1
    orphan = _version_uri(stack, SOSA, n)
    put = http(
        "PUT",
        f"{stack.fuseki}/{stack.env['FUSEKI_DATASET']}/data?graph={urllib.parse.quote(orphan, safe='')}",
        raw_body=b"<urn:qa:huerfano> <urn:qa:p> 'residuo' .\n",
        headers={
            "Content-Type": "text/turtle",
            "Authorization": "Basic "
            + __import__("base64")
            .b64encode(f"admin:{stack.env['FUSEKI_ADMIN_PASSWORD']}".encode())
            .decode(),
        },
    )
    assert put.status in (200, 201, 204), put.text
    assert [v["number"] for v in ficha(stack, SOSA)["versions"]].count(n) == 0
    response = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=SOSA)
    assert response.status == 201, response.text
    assert _json(response)["number"] == n
    triples = _graph_triples(stack, orphan)
    assert not any(s == "urn:qa:huerfano" for s, _, _ in triples)
    assert [v["number"] for v in ficha(stack, SOSA)["versions"]][0] == n


def test_dos_sustituciones_concurrentes_no_dejan_un_estado_roto(
    stack: Stack, editor: Account, admin: Account
) -> None:
    base = last_number(stack, SOSA)
    results: list[Response] = []
    barrier = threading.Barrier(2)

    def run(account: Account, tag: str) -> None:
        barrier.wait()
        results.append(
            replace(stack, SOSA, account.token, iri=SOSA_IRI, prefix=SOSA, tag=tag, timeout=240)
        )

    threads = [
        threading.Thread(target=run, args=(editor, "ca" + _tag())),
        threading.Thread(target=run, args=(admin, "cb" + _tag())),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    codes = sorted(r.status for r in results)
    assert all(code in (201, 409, 503) for code in codes), [r.text for r in results]
    assert 201 in codes, [r.text for r in results]
    created = [_json(r)["number"] for r in results if r.status == 201]
    assert len(set(created)) == len(created), "dos sustituciones con el mismo n"
    assert sorted(created) == list(range(base + 1, base + 1 + len(created)))

    detail = ficha(stack, SOSA)
    numbers = sorted(v["number"] for v in detail["versions"])
    assert numbers == list(range(1, base + 1 + len(created)))
    assert detail["current_version"]["number"] == numbers[-1]
    for version in detail["versions"]:
        assert _graph_exists(stack, version["uri"]), version["uri"]
        expected = _version_uri(stack, SOSA, version["number"] - 1) if version["number"] > 1 else None
        assert version["previous_version"] == expected
        assert version["metrics"] is not None
    assert sorted(_reference_value(stack, SOSA_IRI, f"{DCAT}hasVersion")) == sorted(
        v["uri"] for v in detail["versions"]
    )
    assert len(_reference_value(stack, SOSA_IRI, f"{DCAT}hasCurrentVersion")) == 1
    assert len(_reference_value(stack, SOSA_IRI, f"{DCT}title")) == 1
    # Ningún grafo de más en el triplestore.
    sosa_graphs = [g for g in _external_graphs(stack) if f"/externas/{SOSA}/" in g]
    assert sorted(sosa_graphs) == sorted(v["uri"] for v in detail["versions"])
    # Y se puede seguir sustituyendo (no queda ningún bloqueo retenido).
    follow = replace(stack, SOSA, editor.token, iri=SOSA_IRI, prefix=SOSA)
    assert follow.status == 201, follow.text
    assert _json(follow)["number"] == numbers[-1] + 1


# --- Seguridad -------------------------------------------------------------------------


def test_un_fichero_demasiado_grande_se_rechaza_con_413(stack: Stack, editor: Account) -> None:
    limit = int(stack.env.get("INGEST_MAX_BYTES", 10 * 1024 * 1024))
    state = _state(stack)
    filler = "# " + "x" * 1000 + "\n"
    text = ontology_file(D3F_IRI, "big") + filler * (limit // len(filler) + 20)
    assert len(text) > limit
    response = replace(stack, D3F, editor.token, iri=D3F_IRI, prefix=_prefix("big"), text=text)
    assert response.status == 413, response.status
    assert _state(stack) == state


def test_los_campos_no_inyectan_sparql_ni_turtle(stack: Stack, editor: Account) -> None:
    graphs_before = _external_graphs(stack)
    hostile = [
        'Título " . } ; DELETE WHERE { GRAPH ?g { ?s ?p ?o } } # ',
        'Triple """ comillas """ \\ barra \\" y \' simples',
        "} DROP ALL ; INSERT DATA { <urn:qa:pwned> <urn:qa:p> 'x' } #",
        "Línea 1\nLínea 2 \"con comillas\"@en",
        "<urn:qa:pwned> a <urn:qa:Hack>",
        "Ünïcödé ñ 日本語 ‮",
    ]
    n = last_number(stack, SAREF)
    for i, text in enumerate(hostile):
        response = replace(
            stack,
            SAREF,
            editor.token,
            iri=SAREF_IRI,
            prefix=SAREF,
            title=text if "\n" not in text else text.replace("\n", " "),
            extra={
                "description": text,
                "publisher": text.replace("\n", " "),
                "version_notes": text,
                "version_info": text.replace("\n", " "),
            },
        )
        assert response.status == 201, (i, response.text)
        n += 1
        assert _json(response)["number"] == n
        detail = ficha(stack, SAREF)
        assert detail["title"] == (text if "\n" not in text else text.replace("\n", " ")).strip()
        assert detail["description"] == text.strip()
        assert detail["publisher"] == text.replace("\n", " ").strip()
        assert detail["current_version"]["notes"] == text.strip()
    # Nada se ejecutó como SPARQL: no hay recursos inventados y los grafos son los esperados.
    assert not _ask(stack, "ASK { GRAPH ?g { <urn:qa:pwned> ?p ?o } }")
    assert not _ask(stack, "ASK { GRAPH ?g { ?s a <urn:qa:Hack> } }")
    assert set(graphs_before) <= set(_external_graphs(stack))
    assert len(_reference_value(stack, SAREF_IRI, f"{DCT}title")) == 1
    assert _reference_value(stack, D3F_IRI, f"{DCT}title")
    # Un namespace con la IRI rota y un prefijo con caracteres de SPARQL no llegan a escribirse.
    for field, value in (
        ("namespace", "http://x.example/> } ; DROP ALL #"),
        ("namespace", "javascript:alert(1)"),
        ("prefix", 'a" ; DROP ALL #'),
        ("prefix", "a\nb"),
    ):
        bad = replace(
            stack, SAREF, editor.token, iri=SAREF_IRI, prefix=SAREF, extra={field: value}
        )
        assert bad.status == 422, (field, value, bad.status, bad.text)
    assert last_number(stack, SAREF) == n
    # Y el nombre de fichero (cabecera del multipart) no se refleja ni se usa como ruta.
    odd = replace(
        stack, SAREF, editor.token, iri=SAREF_IRI, prefix=SAREF, filename="../../etc/passwd.ttl"
    )
    assert odd.status == 201, odd.text
    assert "passwd" not in odd.text


def test_el_fichero_no_hace_salir_al_backend_a_buscar_urls(stack: Stack, editor: Account) -> None:
    """``owl:imports`` y un ``@context`` JSON-LD remoto: el backend no descarga nada."""
    marker_imports = f"g7imp{secrets.token_hex(4)}"
    marker_context = f"g7ctx{secrets.token_hex(4)}"
    probe = fuseki_probe_url(stack, marker_imports)
    # Control: la sonda deja huella en el log de Fuseki si alguien la pide.
    assert http("GET", fuseki_probe_url(stack, "g7control", from_host=True)).status == 200
    assert fuseki_logged(stack, "g7control")
    with_import = ontology_file(SOSA_IRI, "imp") + (
        f"<{SOSA_IRI}> <http://www.w3.org/2002/07/owl#imports> <{probe}> .\n"
    )
    response = replace(
        stack, SOSA, editor.token, iri=SOSA_IRI, prefix=SOSA, text=with_import
    )
    assert response.status == 201, response.text
    assert _json(response)["metrics"]["imports"] == 1
    context_url = fuseki_probe_url(stack, marker_context)
    jsonld = json.dumps(
        {"@context": context_url, "@id": SOSA_IRI, "@type": "http://www.w3.org/2002/07/owl#Ontology"}
    )
    remote = replace(
        stack,
        SOSA,
        editor.token,
        iri=SOSA_IRI,
        prefix=SOSA,
        text=jsonld,
        filename="o.jsonld",
        ctype="application/ld+json",
    )
    assert remote.status == 422, remote.text
    assert not fuseki_logged(stack, marker_imports)
    assert not fuseki_logged(stack, marker_context)


@pytest.mark.parametrize(
    "path",
    [
        "/onto/externas/saref/..%2f..%2f..%2fetc%2fpasswd",
        "/onto/externas/..%2f..%2fetc/1",
        "/onto/externas/%2e%2e/%2e%2e/1",
        "/onto/externas/saref/%2e%2e",
        "/onto/externas/saref/1%2f..%2f..",
        "/onto/externas/saref/01",
        "/onto/externas/saref/-1",
        "/onto/externas/saref/0",
        "/onto/externas/saref/1.0",
        "/onto/externas/saref/1;DROP",
        "/onto/externas/saref/1%00",
        "/onto/externas/saref/99999999999999999999999999999",
        "/onto/externas/SAREF/1",
        "/onto/externas/saref%00/1",
        "/onto/externas/saref/1/extra",
        "/onto/externas/%24%7Bjndi%3Aldap%3A%2F%2Fx%7D/1",
        "/ontologies/externas/..%2f..%2fetc%2fpasswd",
        "/ontologies/externas/saref/rdf?version=..%2f..%2fetc",
        "/ontologies/externas/saref/rdf?version=1%27%20OR%20%271",
        "/ontologies/externas/saref/rdf?version=%2e%2e",
    ],
)
def test_la_ruta_de_una_version_no_recorre_rutas(stack: Stack, path: str) -> None:
    for accept in ("text/turtle", "text/html"):
        response = _get(stack, path, headers={"Accept": accept}, follow_redirects=False)
        assert response.status in (400, 404, 405, 422), (path, accept, response.status, response.text[:200])
        assert "root:" not in response.text and "/bin/" not in response.text
    # Y la escritura con el slug manipulado tampoco llega a ningún sitio.


@pytest.mark.parametrize(
    "slug",
    ["..%2f..%2fetc", "%2e%2e", "SAREF", "saref%00", "a_b", "-saref", "x" * 250],
)
def test_el_slug_manipulado_en_la_sustitucion_se_rechaza(
    stack: Stack, editor: Account, slug: str
) -> None:
    state = _state(stack)
    response = replace(stack, slug, editor.token, iri=SAREF_IRI, prefix=_prefix("slg"))
    assert response.status in (404, 422), (slug, response.status, response.text[:200])
    assert _state(stack) == state


def test_la_sustitucion_no_crea_externas_nuevas(stack: Stack, editor: Account) -> None:
    """Una externa que no está en la semilla no se da de alta por la sustitución: 404."""
    state = _state(stack)
    response = http(
        "POST",
        f"{stack.api}/ontologies/externas/nueva-externa/versions",
        raw_body=multipart([("file", ontology_file("https://x.example/o/", "n"), "o.ttl", "text/turtle")])[0],
        headers=multipart([])[1],
        token=editor.token,
    )
    assert response.status in (404, 422), response.text
    assert _state(stack) == state
