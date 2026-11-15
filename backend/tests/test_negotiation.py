import pytest

from app.negotiation import HTML, JSONLD, TURTLE, negotiate

OFFERED = [TURTLE, JSONLD, HTML]
BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


@pytest.mark.parametrize(
    ("accept", "expected"),
    [
        (None, TURTLE),
        ("", TURTLE),
        ("*/*", TURTLE),
        (BROWSER, HTML),
        ("text/turtle", TURTLE),
        ("application/ld+json", JSONLD),
        ("application/ld+json;q=0.9, text/turtle;q=0.5", JSONLD),
        ("text/*", TURTLE),
        ("text/html;q=0.1, text/turtle;q=0", HTML),
        ("application/xml", None),
        ("text/turtle;q=0", None),
        ("basura", TURTLE),
    ],
)
def test_negotiate(accept: str | None, expected: str | None) -> None:
    assert negotiate(accept, OFFERED) == expected
