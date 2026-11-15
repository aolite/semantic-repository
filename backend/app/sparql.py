"""Construcción segura de consultas SPARQL.

El protocolo SPARQL por HTTP no tiene parámetros enlazados como SQL, así que los valores
se insertan ya serializados como términos SPARQL y escapados según la gramática de
SPARQL 1.1:

- ``iri(value)``: ``<...>``. Rechaza (``ValueError``) cualquier carácter que la regla
  ``IRIREF`` no admite (``<>"{}|^`\\``, espacios y controles) y lo que no sea http(s).
- ``literal(value)``: ``"..."``. Escapa ``\\``, ``"``, saltos de línea, retornos y el
  resto de controles con las secuencias ``ECHAR`` o ``\\uXXXX``. Rechaza los valores con
  ``\\u`` o ``\\U`` (secuencias que SPARQL procesa antes de analizar la consulta).

El texto libre del usuario (``q`` del catálogo) ni siquiera llega a SPARQL: se filtra en
Python (``app.catalog``). Los slugs y versiones se validan con su patrón antes de usarse.

``render(template, **params)`` sustituye ``$nombre`` en la plantilla y **solo acepta**
objetos ``SparqlTerm`` (los que devuelven ``iri`` y ``literal``): pasar un ``str`` es un
``TypeError``. Así es imposible concatenar texto del usuario por error.
"""

import re
from dataclasses import dataclass
from string import Template

# Caracteres que la regla IRIREF de SPARQL 1.1 no admite, más los de control y espacio.
_IRI_FORBIDDEN = re.compile(r'[<>"{}|^`\\\x00-\x20\x7f]')

_CODEPOINT_ESCAPE = re.compile(r"\\[uU]")

# La comilla simple no se escapa: el literal va entre comillas dobles.
_ECHAR = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
    "\b": "\\b",
    "\f": "\\f",
}


@dataclass(frozen=True, slots=True)
class SparqlTerm:
    """Un término SPARQL ya serializado y seguro para insertarlo en una consulta."""

    text: str

    def __str__(self) -> str:
        return self.text


def iri(value: str) -> SparqlTerm:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        raise ValueError("IRI no válida para SPARQL: debe ser http(s)")
    if _IRI_FORBIDDEN.search(value):
        raise ValueError("IRI no válida para SPARQL: contiene caracteres no permitidos")
    return SparqlTerm(f"<{value}>")


def iri_list(values: list[str]) -> SparqlTerm:
    """Lista de IRIs para un bloque ``VALUES ?x { $lista }``. Cada una pasa por ``iri()``.

    Una lista vacía es un error (``UNDEF`` dejaría la variable libre y la consulta casaría
    con todo): quien llama no debe lanzar la consulta."""
    if not values:
        raise ValueError("iri_list() necesita al menos una IRI")
    return SparqlTerm(" ".join(iri(value).text for value in sorted(set(values))))


def _escape_char(char: str) -> str:
    if char in _ECHAR:
        return _ECHAR[char]
    if ord(char) < 0x20 or ord(char) == 0x7F:
        return f"\\u{ord(char):04X}"
    return char


def literal(value: str) -> SparqlTerm:
    if not isinstance(value, str):
        raise TypeError("literal() solo acepta str")
    if _CODEPOINT_ESCAPE.search(value):
        # SPARQL 1.1 (sección 19.2) procesa \uXXXX y \UXXXXXXXX ANTES del análisis, y los
        # motores lo aplican de forma distinta ante una barra escapada (rdflib la ignora,
        # Jena no). Para no depender de eso, estos valores se rechazan.
        raise ValueError("literal() no admite secuencias \\u o \\U en el valor")
    return SparqlTerm('"' + "".join(_escape_char(c) for c in value) + '"')


class _QueryTemplate(Template):
    delimiter = "$"
    # Solo identificadores simples: ``$graph``, ``$dataset_ns``.
    idpattern = r"[a-z][a-z0-9_]*"


def render(template: str, **params: SparqlTerm) -> str:
    """Rellena ``$nombre`` con términos ya serializados. Falla si falta alguno."""
    for name, value in params.items():
        if not isinstance(value, SparqlTerm):
            raise TypeError(
                f"El parámetro SPARQL '{name}' debe ser un SparqlTerm, no {type(value)}"
            )
    return _QueryTemplate(template).substitute({k: v.text for k, v in params.items()})
