"""Datos de prueba de la fase 4 (propios del backend, no de ``semantic/``).

Una serie ``prueba`` con una versión 1.0.0 cuyas distribuciones cubren los tres casos de
``dct:accessRights`` de la decisión 40 (los datos sintéticos de ``semantic/`` solo tienen
RESTRICTED) y una distribución sin ``dcat:mediaType`` (como la NPZ).
"""

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.models import Role, User

AR = "http://publications.europa.eu/resource/authority/access-right/"
IANA = "http://www.iana.org/assignments/media-types/"
TURTLE_CT = {"Content-Type": "text/turtle"}

PREFIXES = """
@prefix dcat: <http://www.w3.org/ns/dcat#> .
@prefix dct:  <http://purl.org/dc/terms/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""

V1 = f"""
<dataset/prueba/1.0.0> a dcat:Dataset ;
    dct:title "Prueba"@es ; dct:description "Versión 1"@es ;
    dcat:version "1.0.0" ; dcat:inSeries <dataset/prueba> ;
    dct:accessRights <{AR}RESTRICTED> ;
    prov:wasGeneratedBy [ a prov:Activity ; rdfs:label "Captura"@es ] ;
    dcat:distribution <dataset/prueba/1.0.0/abierta>, <dataset/prueba/1.0.0/restringida>,
        <dataset/prueba/1.0.0/defensa>, <dataset/prueba/1.0.0/npz> .
<dataset/prueba/1.0.0/abierta> a dcat:Distribution ;
    dct:accessRights <{AR}PUBLIC> ;
    dcat:mediaType <{IANA}text/csv> ;
    dcat:accessURL <dataset/prueba/1.0.0/abierta> .
<dataset/prueba/1.0.0/restringida> a dcat:Distribution ;
    dcat:mediaType <{IANA}text/csv> ;
    dcat:accessURL <dataset/prueba/1.0.0/restringida> .
<dataset/prueba/1.0.0/defensa> a dcat:Distribution ;
    dct:accessRights <{AR}NON_PUBLIC> ;
    dcat:mediaType <{IANA}text/csv> ;
    dcat:accessURL <dataset/prueba/1.0.0/defensa> .
<dataset/prueba/1.0.0/npz> a dcat:Distribution ;
    dcat:accessURL <dataset/prueba/1.0.0/npz> .
"""

V2 = f"""
<dataset/prueba/2.0.0> a dcat:Dataset ;
    dct:title "Prueba"@es ; dct:description "Versión 2"@es ;
    dcat:version "2.0.0" ; dcat:inSeries <dataset/prueba> ;
    dcat:previousVersion <dataset/prueba/1.0.0> ;
    dct:accessRights <{AR}PUBLIC> ;
    dcat:distribution <dataset/prueba/2.0.0/csv> .
<dataset/prueba/2.0.0/csv> a dcat:Distribution ;
    dcat:mediaType <{IANA}text/csv> ;
    dcat:accessURL <dataset/prueba/2.0.0/csv> .
"""


def series(*versions: str, last: str = "1.0.0", title: str = "Serie de prueba") -> str:
    return (
        PREFIXES
        + f"""
<dataset/prueba> a dcat:DatasetSeries ;
    dct:title "{title}"@es ; dct:description "Descripción"@es ;
    dcat:last <dataset/prueba/{last}> .
<catalogo/pruebas> dcat:dataset <dataset/prueba> .
"""
        + "".join(versions)
    )


def editor_headers(make_user: Callable[..., User], login: Callable[..., dict[str, str]]):
    make_user("editora", Role.EDITOR)
    return login("editora")


def publish(client: TestClient, headers: dict[str, str], body: str) -> object:
    return client.post("/datasets", content=body.encode(), headers=headers | TURTLE_CT)


def upload(
    client: TestClient, headers: dict[str, str], dist: str, data: bytes, version: str = "1.0.0"
) -> object:
    return client.put(
        f"/datasets/prueba/versions/{version}/distributions/{dist}/file",
        files={"file": ("cualquiera.bin", data, "application/x-cliente")},
        headers=headers,
    )
