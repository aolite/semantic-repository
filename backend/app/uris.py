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

# Slugs reservados: ``vocab/corp/`` es el espacio de los esquemas corporativos, y
# ``onto/externas`` el grafo de las ontologías externas.
CORP_SEGMENT = "corp"
EXTERNAL_ONTOLOGIES_SLUG = "externas"
DOMAIN_SCHEME_SLUG = "dominio"
RESERVED_SCHEME_SLUGS = frozenset({CORP_SEGMENT})
RESERVED_ONTOLOGY_SLUGS = frozenset({EXTERNAL_ONTOLOGIES_SLUG})

DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
ADMS = Namespace("http://www.w3.org/ns/adms#")
PROV = Namespace("http://www.w3.org/ns/prov#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
VCARD = Namespace("http://www.w3.org/2006/vcard/ns#")
OWL = Namespace("http://www.w3.org/2002/07/owl#")
VANN = Namespace("http://purl.org/vocab/vann/")
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

    # --- Fase 3: vocabularios y ontologías -------------------------------------------

    @property
    def onto_ns(self) -> str:
        return f"{self.base}onto/"

    @property
    def corp_vocab_ns(self) -> str:
        return f"{self.vocab_ns}corp/"

    @property
    def external_ontologies_graph(self) -> str:
        """Grafo con nombre de las ontologías externas (solo referencia)."""
        return f"{self.onto_ns}{EXTERNAL_ONTOLOGIES_SLUG}"

    @property
    def domain_concepts_scheme(self) -> str:
        """Esquema ``{BASE_URI}vocab/dominio`` con un concepto por dominio del catálogo."""
        return f"{self.vocab_ns}{DOMAIN_SCHEME_SLUG}"

    def domain_concept(self, domain: str) -> str:
        return f"{self.domain_concepts_scheme}/{domain}"

    def domain_of_domain_concept(self, concept_uri: str) -> str | None:
        """Slug de ``{BASE_URI}vocab/dominio/{it|ot|pqc|ia}``, o ``None``."""
        prefix = f"{self.domain_concepts_scheme}/"
        if not concept_uri.startswith(prefix):
            return None
        rest = concept_uri[len(prefix) :]
        return rest if rest in DOMAIN_SLUGS else None

    def ontology(self, slug: str) -> str:
        return f"{self.onto_ns}{slug}"

    def ontology_version(self, slug: str, version: str) -> str:
        return f"{self.onto_ns}{slug}/{version}"

    def ontology_slug(self, uri: str) -> str | None:
        """Slug de ``{BASE_URI}onto/{slug}`` (sin versión ni fragmento), o ``None``."""
        if not uri.startswith(self.onto_ns):
            return None
        rest = uri[len(self.onto_ns) :]
        return rest if is_slug(rest) and rest not in RESERVED_ONTOLOGY_SLUGS else None

    def ontology_version_parts(self, uri: str) -> tuple[str, str] | None:
        """``(slug, version)`` de ``{BASE_URI}onto/{slug}/{version}``, o ``None``."""
        if not uri.startswith(self.onto_ns):
            return None
        slug, _, version = uri[len(self.onto_ns) :].partition("/")
        if self.ontology_slug(f"{self.onto_ns}{slug}") is None or not is_version(version):
            return None
        return slug, version

    def scheme(self, slug: str, *, corp: bool = False) -> str:
        return f"{self.corp_vocab_ns if corp else self.vocab_ns}{slug}"

    def scheme_parts(self, uri: str) -> tuple[str, bool] | None:
        """``(slug, corporativo)`` de ``{BASE_URI}vocab/{slug}`` o ``…/vocab/corp/{slug}``."""
        if uri.startswith(self.corp_vocab_ns):
            rest = uri[len(self.corp_vocab_ns) :]
            return (rest, True) if is_slug(rest) else None
        if uri.startswith(self.vocab_ns):
            rest = uri[len(self.vocab_ns) :]
            if is_slug(rest) and rest not in RESERVED_SCHEME_SLUGS:
                return rest, False
        return None

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
