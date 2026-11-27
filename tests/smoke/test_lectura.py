"""Humo de solo lectura: salud, versión, frontend, catálogo, URIs persistentes, SPARQL y docs."""

from __future__ import annotations

import os
import re
import secrets
import urllib.parse

from smokelib import Config, api_path, request, warn

TURTLE = {"Accept": "text/turtle"}
JSON_RESULTS = {"Accept": "application/sparql-results+json"}


# --- API: salud y versión ---------------------------------------------------------------


def test_la_api_esta_sana(get) -> None:
    response = get("/health")
    assert response.status == 200, response.text[:300]
    assert response.json()["status"] == "ok"  # type: ignore[index]


def test_la_api_esta_lista_con_sus_dependencias(get) -> None:
    response = get("/health/ready")
    assert response.status == 200, response.text[:300]
    checks = response.json()["checks"]  # type: ignore[index]
    assert checks, "sin comprobaciones de dependencias"
    assert all(item["status"] == "ok" for item in checks.values()), checks


def test_la_version_de_la_api_se_conoce(get) -> None:
    spec = get("/openapi.json")
    assert spec.status == 200, f"/openapi.json: {spec.status}"
    data = spec.json()
    version = data["info"]["version"]  # type: ignore[index]
    assert re.fullmatch(r"\d+\.\d+\.\d+\S*", version), version
    health = get("/health").json()
    schema = data["components"]["schemas"].get("HealthStatus", {})  # type: ignore[index]
    if "version" in schema.get("properties", {}):
        # La API ya declara el campo (PR #57): /health debe traerlo.
        assert isinstance(health.get("version"), str), f"/health sin version: {health}"  # type: ignore[union-attr]
        assert "commit" in health, f"/health sin commit: {health}"  # type: ignore[operator]
        print(f"versión {health['version']}, commit {health['commit']}")  # type: ignore[index]
        if health["commit"] is None:  # type: ignore[index]
            warn(
                "/health devuelve commit null: APP_COMMIT no está definida en el despliegue"
            )
        expected = os.environ.get("SMOKE_EXPECT_COMMIT")
        if expected:
            assert health["commit"] == expected, (  # type: ignore[index]
                f"commit desplegado {health['commit']!r}, esperado {expected!r}"
            )
    else:
        warn(
            "/health aún no informa de version ni commit (API anterior a la PR #57); "
            f"solo se conoce info.version del OpenAPI: {version}"
        )
        if os.environ.get("SMOKE_EXPECT_COMMIT"):
            pytest.fail("SMOKE_EXPECT_COMMIT definida pero la API no expone el commit")


def test_docs_responde(get) -> None:
    # Decisión 24: /docs público.
    response = get("/docs")
    assert response.status == 200, f"/docs: {response.status}"
    assert "swagger" in response.text.lower() or "openapi" in response.text.lower()


# --- Frontend ---------------------------------------------------------------------------


def test_el_frontend_carga_la_app(cfg: Config) -> None:
    response = request(cfg, "GET", f"{cfg.frontend}/", headers={"Accept": "text/html"})
    assert response.status == 200, response.status
    assert "text/html" in response.headers.get("content-type", "")
    assert 'id="root"' in response.text, "el HTML no contiene el contenedor de la app"
    assert "<script" in response.text


def test_el_frontend_sirve_sus_assets(cfg: Config) -> None:
    html = request(cfg, "GET", f"{cfg.frontend}/").text
    refs = re.findall(r'<(?:script|link)\b[^>]*?(?:src|href)="([^"]+)"', html)
    assets = [r for r in refs if not r.startswith(("http:", "https:", "//", "data:"))]
    assets = [r for r in assets if re.search(r"\.(js|mjs|css|tsx?)(\?|$)|^/@", r)]
    assert assets, f"el HTML no referencia assets propios: {refs}"
    for ref in assets[:6]:
        response = request(cfg, "GET", urllib.parse.urljoin(f"{cfg.frontend}/", ref))
        assert response.status == 200, f"{ref}: {response.status}"
        content_type = response.headers.get("content-type", "")
        # Un asset inexistente suele caer en el index.html del SPA con un 200.
        assert "text/html" not in content_type, f"{ref} devuelve HTML ({content_type})"
        assert response.content, f"{ref} vacío"


def test_una_ruta_del_frontend_sirve_la_app(cfg: Config) -> None:
    response = request(cfg, "GET", f"{cfg.frontend}/datasets/ruta-inventada-smoke")
    assert response.status == 200, "el SPA debe servir index.html en sus rutas"
    assert 'id="root"' in response.text


# --- Catálogo ---------------------------------------------------------------------------


def test_el_catalogo_y_las_listas_no_estan_vacios(get, datasets, vocabularies) -> None:
    catalogs = get("/catalogs")
    assert catalogs.status == 200
    assert catalogs.json()["total"] > 0, "sin catálogos"  # type: ignore[index]
    assert datasets, "lista de datasets vacía"
    kinds = {item["kind"] for item in vocabularies}
    assert "own" in kinds or "external" in kinds, f"sin ontologías: {kinds}"
    assert any(k.startswith("skos") for k in kinds), f"sin vocabularios SKOS: {kinds}"


def test_el_catalogo_raiz_sirve_turtle(cfg: Config) -> None:
    response = request(cfg, "GET", f"{cfg.api}/catalogo", headers=TURTLE)
    assert response.status == 200, response.status
    assert "text/turtle" in response.headers["content-type"]
    assert "dcat:Catalog" in response.text or "dcat#Catalog" in response.text
    assert cfg.base_uri in response.text, "el RDF no usa SMOKE_BASE_URI"


# --- URIs persistentes (303 al frontend, Turtle con Accept) -----------------------------


def _check_persistent(cfg: Config, uri: str, frontend_prefix: str) -> None:
    url = api_path(cfg, uri)
    redirect = request(cfg, "GET", url)
    assert redirect.status == 303, f"{url} sin Accept: {redirect.status}"
    location = redirect.headers.get("location", "")
    assert location.startswith(cfg.frontend + "/"), (
        f"{url}: Location {location!r} no apunta a SMOKE_FRONTEND_URL ({cfg.frontend})"
    )
    assert urllib.parse.urlsplit(location).path.startswith(frontend_prefix), location
    rdf = request(cfg, "GET", url, headers=TURTLE)
    assert rdf.status == 200, f"{url} con Accept turtle: {rdf.status}"
    assert "text/turtle" in rdf.headers["content-type"], rdf.headers["content-type"]
    assert uri in rdf.text, f"{url}: el Turtle no menciona {uri}"


def test_uri_persistente_de_dataset(cfg: Config, datasets) -> None:
    _check_persistent(cfg, datasets[0]["uri"], "/datasets/")


def test_uri_persistente_de_ontologia(cfg: Config, vocabularies) -> None:
    own = [
        v
        for v in vocabularies
        if v["kind"] == "own" and v["uri"].startswith(cfg.base_uri)
    ]
    assert own, "ninguna ontología propia bajo SMOKE_BASE_URI"
    _check_persistent(cfg, own[0]["uri"], "/ontologias/")


def test_uri_persistente_de_concepto_skos(cfg: Config, get, vocabularies) -> None:
    schemes = [
        v
        for v in vocabularies
        if v["kind"] == "skos_domain" and (v.get("concepts") or 0) > 0
    ]
    assert schemes, "ningún vocabulario SKOS de dominio con conceptos"
    detail = get(f"/schemes/{schemes[0]['slug']}")
    assert detail.status == 200, detail.status
    tree = detail.json()["tree"]  # type: ignore[index]
    assert tree, "esquema sin conceptos en el árbol"
    _check_persistent(cfg, tree[0]["uri"], "/vocabularios/")


# --- SPARQL público ---------------------------------------------------------------------


def test_sparql_responde_un_select(cfg: Config) -> None:
    query = "SELECT ?s WHERE { ?s a <http://www.w3.org/ns/dcat#Dataset> } LIMIT 1"
    response = request(
        cfg,
        "GET",
        f"{cfg.api}/sparql?" + urllib.parse.urlencode({"query": query}),
        headers=JSON_RESULTS,
    )
    assert response.status == 200, response.text[:300]
    assert response.json()["results"]["bindings"], "SELECT sin resultados"  # type: ignore[index]


def test_sparql_rechaza_las_escrituras_y_no_escribe(cfg: Config) -> None:
    marker = f"urn:smoke:{secrets.token_hex(6)}"
    update = f"INSERT DATA {{ <{marker}> <{marker}> <{marker}> }}"
    attempts = [
        request(cfg, "POST", f"{cfg.api}/sparql", form={"query": update}),
        request(cfg, "POST", f"{cfg.api}/sparql", form={"update": update}),
        request(
            cfg,
            "POST",
            f"{cfg.api}/sparql",
            raw_body=update.encode(),
            headers={"Content-Type": "application/sparql-update"},
        ),
        request(
            cfg, "GET", f"{cfg.api}/sparql?" + urllib.parse.urlencode({"query": update})
        ),
    ]
    for attempt in attempts:
        assert 400 <= attempt.status < 500, (
            f"INSERT aceptado o error de servidor: {attempt.status}"
        )
    ask = f"ASK {{ <{marker}> ?p ?o }}"
    check = request(
        cfg,
        "GET",
        f"{cfg.api}/sparql?" + urllib.parse.urlencode({"query": ask}),
        headers=JSON_RESULTS,
    )
    assert check.status == 200
    assert check.json()["boolean"] is False, (
        "el INSERT llegó a escribir en el triplestore"
    )  # type: ignore[index]


# --- F-UJI (aviso) ----------------------------------------------------------------------


def test_hay_al_menos_una_evaluacion_fair(datasets) -> None:
    if not any(d.get("fair_total") is not None for d in datasets):
        warn(
            "F-UJI: ningún dataset con evaluación FAIR visible en /datasets (sin evaluar o no expuesto)"
        )
