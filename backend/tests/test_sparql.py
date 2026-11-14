"""Escapado de valores en SPARQL (``app.sparql``): base de la defensa contra inyección."""

import pytest
from rdflib import Dataset, Literal, URIRef

from app.sparql import SparqlTerm, iri, literal, render

HOSTILE = [
    'x" } ; DROP ALL ; #',
    "x' } UNION { ?s ?p ?o } #",
    'a\\" . } INSERT DATA { <urn:x> <urn:y> "z" } #',
    "línea\nnueva\r\tcon controles\x00\x07\x1f",
    '"""triple"""',
    "barra \\ suelta y \\\\ doble",
]


@pytest.mark.parametrize("value", ["\\u0022 } #", "\\U00000022", "a\\\\u005C"])
def test_literal_rejects_codepoint_escapes(value: str) -> None:
    with pytest.raises(ValueError, match=r"\\u"):
        literal(value)


@pytest.mark.parametrize("value", HOSTILE)
def test_literal_roundtrips_as_a_single_literal(value: str) -> None:
    # El literal escapado, evaluado por un motor SPARQL real, devuelve exactamente el
    # valor original: no se puede salir de las comillas.
    query = render("SELECT ?v WHERE { BIND($value AS ?v) }", value=literal(value))
    rows = list(Dataset().query(query))
    assert len(rows) == 1
    assert rows[0][0] == Literal(value)


@pytest.mark.parametrize("value", HOSTILE)
def test_literal_has_no_raw_quote_or_newline(value: str) -> None:
    text = literal(value).text
    inner = text[1:-1]
    assert text.startswith('"') and text.endswith('"')
    # Toda comilla interior va escapada y no hay saltos de línea en bruto.
    assert '"' not in inner.replace('\\"', "")
    assert "\n" not in inner and "\r" not in inner


@pytest.mark.parametrize(
    "value",
    [
        "https://example.org/a> } ; DROP ALL ; <x",
        "https://example.org/a b",
        'https://example.org/"x"',
        "https://example.org/{x}",
        "https://example.org/a\\b",
        "https://example.org/a\nb",
        "javascript:alert(1)",
        "urn:x",
        "",
    ],
)
def test_iri_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        iri(value)


def test_iri_accepts_valid_http_iris() -> None:
    assert iri("https://semantic.example.org/itot/dataset/x").text == (
        "<https://semantic.example.org/itot/dataset/x>"
    )
    term = iri("https://semantic.example.org/itot/dataset/ñandú")
    assert URIRef(term.text[1:-1]) == URIRef("https://semantic.example.org/itot/dataset/ñandú")


def test_render_refuses_raw_strings() -> None:
    with pytest.raises(TypeError):
        render("SELECT * WHERE { ?s ?p $x }", x="texto del usuario")  # type: ignore[arg-type]


def test_render_requires_every_placeholder() -> None:
    with pytest.raises(KeyError):
        render("SELECT * WHERE { GRAPH $graph { ?s ?p ?o } }")


def test_render_substitutes_terms() -> None:
    query = render("ASK { GRAPH $g { ?s ?p $o } }", g=iri("https://a.example/g"), o=literal("x"))
    assert query == 'ASK { GRAPH <https://a.example/g> { ?s ?p "x" } }'
    assert isinstance(literal("x"), SparqlTerm)
