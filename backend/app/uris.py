"""Patrón de URIs persistentes (contrato ``semantic/uris.md``) y espacios de nombres RDF.

Todas las URIs propias se construyen a partir de ``BASE_URI``: aquí no hay ningún dominio
escrito a mano.
"""

import re
from typing import Literal

from rdflib import Namespace

SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
VERSION_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"
_SLUG_RE = re.compile(SLUG_PATTERN)
_VERSION_RE = re.compile(VERSION_PATTERN)

# Esquemas SKOS de dominio (contrato del orquestador para la fase 2).
DomainSlug = Literal["it", "ot", "pqc", "ia"]
DOMAIN_SLUGS: tuple[str, ...] = ("it", "ot", "pqc", "ia")

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
ADMS = Namespace("http://www.w3.org/ns/adms#")
PROV = Namespace("http://www.w3.org/ns/prov#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
IANA_MEDIA_TYPES = "http://www.iana.org/assignments/media-types/"
EU_ACCESS_RIGHT = "http://publications.europa.eu/resource/authority/access-right/"


def is_slug(value: str) -> bool:
    return bool(_SLUG_RE.fullmatch(value))


def is_version(value: str) -> bool:
    return bool(_VERSION_RE.fullmatch(value))


def version_key(value: str | None) -> tuple[int, int, int]:
    """Clave de orden semver. Lo que no es semver va al final (como ``-1``)."""
    if value and is_version(value):
        major, minor, patch = (int(part) for part in value.split("."))
        return (major, minor, patch)
    return (-1, -1, -1)


class Uris:
    """Constructor de URIs para una ``BASE_URI`` dada (que termina en ``/``)."""

    def __init__(self, base_uri: str) -> None:
        self.base = base_uri

    @property
    def dataset_ns(self) -> str:
        return f"{self.base}dataset/"

    @property
    def activity_ns(self) -> str:
        return f"{self.base}actividad/"

    @property
    def vocab_ns(self) -> str:
        return f"{self.base}vocab/"

    @property
    def vocab_graph(self) -> str:
        """Grafo con nombre del vocabulario mínimo de la fase 2 [PROPUESTA]."""
        return f"{self.base}vocab/"

    @property
    def catalog(self) -> str:
        """``dcat:Catalog`` único; también es el nombre de su grafo."""
        return f"{self.base}catalogo"

    @property
    def synthetic_type(self) -> str:
        return f"{self.base}vocab/tipo-dataset/sintetico"

    def series(self, slug: str) -> str:
        return f"{self.dataset_ns}{slug}"

    def version(self, slug: str, version: str) -> str:
        return f"{self.dataset_ns}{slug}/{version}"

    def domain_scheme(self, domain: str) -> str:
        return f"{self.vocab_ns}{domain}"

    def series_slug(self, uri: str) -> str | None:
        """Slug de una URI de serie, o ``None`` si no sigue el patrón."""
        if not uri.startswith(self.dataset_ns):
            return None
        rest = uri[len(self.dataset_ns) :]
        return rest if is_slug(rest) else None

    def domain_of_scheme(self, scheme_uri: str) -> str | None:
        if not scheme_uri.startswith(self.vocab_ns):
            return None
        rest = scheme_uri[len(self.vocab_ns) :]
        return rest if rest in DOMAIN_SLUGS else None

    def domain_of_concept_uri(self, concept_uri: str) -> str | None:
        """Dominio deducido del patrón ``{BASE_URI}vocab/{esquema}/{slug}`` (respaldo)."""
        if not concept_uri.startswith(self.vocab_ns):
            return None
        scheme, _, rest = concept_uri[len(self.vocab_ns) :].partition("/")
        return scheme if scheme in DOMAIN_SLUGS and rest else None

    def version_from_uri(self, series_uri: str, version_uri: str) -> str | None:
        """Número de versión según el patrón ``{serie}/{version}``."""
        prefix = f"{series_uri}/"
        if not version_uri.startswith(prefix):
            return None
        rest = version_uri[len(prefix) :]
        return rest if is_version(rest) else None
