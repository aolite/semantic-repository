# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib>=7.1,<8",
# ]
# ///
"""Prepara la publicación de una versión de ontología o vocabulario.

Uso (desde la raíz del repositorio, también en CI):

    uv run infra/scripts/publicar.py --tag onto/itot/v1.2.0 --out build

1. Deduce tipo, slug y versión de la etiqueta de Git y localiza el fichero:
     onto/{slug}/v{version}         -> semantic/ontologias/{slug}/{version}.ttl
     vocab/{slug}/v{version}        -> semantic/vocabularios/{slug}.ttl
     vocab/corp/{slug}/v{version}   -> semantic/vocabularios/corp/{slug}.ttl
2. Comprueba que la versión de la etiqueta coincide con la del RDF.
3. Expande las IRIs relativas con BASE_URI (rdflib, `publicID`) y escribe en
   --out los artefactos de la Release: Turtle, JSON-LD y, solo ontologías,
   RDF/XML. Los .ttl del repositorio no declaran @base, así que sin este paso
   WIDOCO y los consumidores verían IRIs relativas.
4. Para vocabularios SKOS genera una página HTML sencilla en --out/docs.
   (Para ontologías la documentación la genera WIDOCO en el workflow.)
5. Si existe GITHUB_OUTPUT, escribe en él: kind, slug, version, name, source.

Variables de entorno:
  BASE_URI                  Por defecto https://semantic.example.org/itot/
  SKOS_VERSION_PREDICATE    IRI de la propiedad del skos:ConceptScheme que lleva
                            la versión. Por defecto owl:versionInfo. «none» o vacía =
                            no se comprueba la versión del vocabulario (aviso).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, SKOS

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"
SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
TAG_PATTERNS = (
    ("onto", re.compile(rf"^onto/({SLUG})/v({VERSION})$")),
    ("vocab-corp", re.compile(rf"^vocab/corp/({SLUG})/v({VERSION})$")),
    ("vocab", re.compile(rf"^vocab/({SLUG})/v({VERSION})$")),
)
# REPO_ROOT solo sirve para probar el script contra un árbol de prueba.
ROOT = Path(os.environ.get("REPO_ROOT") or Path(__file__).resolve().parents[2])


def fail(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def parse_tag(tag: str) -> tuple[str, str, str]:
    for kind, rx in TAG_PATTERNS:
        m = rx.match(tag)
        if m:
            return kind, m.group(1), m.group(2)
    fail(f"etiqueta no válida: {tag!r} (ver infra/README.md)")


def source_path(kind: str, slug: str, version: str) -> Path:
    sem = ROOT / "semantic"
    if kind == "onto":
        return sem / "ontologias" / slug / f"{version}.ttl"
    if kind == "vocab-corp":
        return sem / "vocabularios" / "corp" / f"{slug}.ttl"
    return sem / "vocabularios" / f"{slug}.ttl"


def check_ontology_version(g: Graph, version: str) -> None:
    onts = list(g.subjects(RDF.type, OWL.Ontology))
    if len(onts) != 1:
        fail(f"se esperaba exactamente un owl:Ontology y hay {len(onts)}")
    ont = onts[0]
    info = [str(o) for o in g.objects(ont, OWL.versionInfo)]
    iris = [str(o) for o in g.objects(ont, OWL.versionIRI)]
    if not info and not iris:
        fail(f"{ont} no declara owl:versionInfo ni owl:versionIRI")
    for v in info:
        if v != version:
            fail(f"owl:versionInfo={v!r} no coincide con la etiqueta ({version!r})")
    for iri in iris:
        if not iri.rstrip("/").endswith("/" + version):
            fail(f"owl:versionIRI={iri} no termina en /{version}")


def check_scheme_version(g: Graph, version: str) -> None:
    pred = os.environ.get("SKOS_VERSION_PREDICATE", str(OWL.versionInfo)).strip()
    if not pred or pred.lower() == "none":
        print("AVISO: SKOS_VERSION_PREDICATE desactivada; no se comprueba la versión")
        return
    schemes = list(g.subjects(RDF.type, SKOS.ConceptScheme))
    if not schemes:
        fail("el fichero no contiene ningún skos:ConceptScheme")
    for s in schemes:
        vals = [str(o) for o in g.objects(s, URIRef(pred))]
        if not vals:
            fail(f"{s} no declara <{pred}> (propiedad de versión configurada)")
        for v in vals:
            if v != version:
                fail(f"<{pred}>={v!r} en {s} no coincide con la etiqueta ({version!r})")


def label(g: Graph, node) -> str:
    labels = list(g.objects(node, SKOS.prefLabel))
    for lang in ("es", "en"):
        for lab in labels:
            if isinstance(lab, Literal) and lab.language == lang:
                return str(lab)
    return str(labels[0]) if labels else str(node)


def skos_page(g: Graph, title: str, version: str) -> str:
    rows = []
    for c in sorted(g.subjects(RDF.type, SKOS.Concept), key=lambda n: label(g, n).lower()):
        broader = ", ".join(html.escape(label(g, b)) for b in g.objects(c, SKOS.broader))
        defs = " ".join(html.escape(str(d)) for d in g.objects(c, SKOS.definition))
        rows.append(
            f"<tr><td>{html.escape(label(g, c))}</td>"
            f'<td><a href="{html.escape(str(c))}">{html.escape(str(c))}</a></td>'
            f"<td>{broader}</td><td>{defs}</td></tr>"
        )
    return (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)} {html.escape(version)}</title></head><body>"
        f"<h1>{html.escape(title)}</h1><p>Versión {html.escape(version)}</p>"
        '<table border="1" cellpadding="4"><thead><tr><th>Concepto</th><th>IRI</th>'
        "<th>Más general</th><th>Definición</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></body></html>"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base = os.environ.get("BASE_URI", "").strip() or DEFAULT_BASE_URI
    if not base.endswith("/"):
        base += "/"

    kind, slug, version = parse_tag(args.tag)
    src = source_path(kind, slug, version)
    if not src.is_file():
        fail(f"no existe {src.relative_to(ROOT)} para la etiqueta {args.tag}")

    g = Graph()
    g.parse(src, format="turtle", publicID=base)
    if kind == "onto":
        check_ontology_version(g, version)
    else:
        check_scheme_version(g, version)

    name = args.tag.rsplit("/v", 1)[0].replace("/", "-") + "-" + version
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    g.serialize(out / f"{name}.ttl", format="turtle")
    g.serialize(out / f"{name}.jsonld", format="json-ld", indent=2)
    if kind == "onto":
        g.serialize(out / f"{name}.rdf", format="pretty-xml")
    else:
        docs = out / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "index.html").write_text(skos_page(g, slug, version), encoding="utf-8")

    print(f"OK {kind} {slug} {version}: {len(g)} tripletas, base {base}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"kind={kind}\nslug={slug}\nversion={version}\nname={name}\n")
            f.write(f"source={src.relative_to(ROOT)}\n")


if __name__ == "__main__":
    main()
