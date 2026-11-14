# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib>=7.1,<8",
#     "pyshacl>=0.30,<1",
# ]
# ///
"""Valida el RDF de semantic/.

Uso (desde la raíz del repositorio, también en CI):

    uv run semantic/scripts/validate.py

Comprueba:
  1. Que todo .ttl de semantic/ se analiza sin errores y no declara @base
     (las URIs propias son relativas y se resuelven contra BASE_URI).
  2. Que las formas de semantic/shapes/ son SHACL válido (meta-SHACL).
  3. Que cada ejemplo de semantic/examples/valid/ cumple las formas.
  4. Que cada ejemplo de semantic/examples/invalid/ NO las cumple y que las
     formas que fallan son exactamente las de sus líneas
     «# expect-violation: <NombreLocal>».
  5. Que cada fichero de semantic/data/sintetico/ (lo que ingesta el backend,
     un fichero por dataset) cumple las formas por sí solo.
  6. Que todo semantic/data/**/*.ttl junto (datos, catálogo y vocabulario
     mínimo en un grafo) cumple las formas y es coherente: temas en un único
     esquema de dominio, marca de sintético, referencias entre series,
     versiones y distribuciones, y URIs según semantic/uris.md.

Sale con código 0 si todo va bien y 1 si algo falla.

BASE_URI se lee del entorno; si no está, se usa el valor por defecto del
proyecto. Ver semantic/uris.md.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from pyshacl import validate
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS, RDF, SKOS

DEFAULT_BASE_URI = "https://semantic.example.org/itot/"
SH = Namespace("http://www.w3.org/ns/shacl#")
# Namespace propio: el DCAT de rdflib no incluye los términos de DCAT 3.
DCAT = Namespace("http://www.w3.org/ns/dcat#")

SEMANTIC_DIR = Path(__file__).resolve().parent.parent
SHAPES_DIR = SEMANTIC_DIR / "shapes"
VALID_DIR = SEMANTIC_DIR / "examples" / "valid"
INVALID_DIR = SEMANTIC_DIR / "examples" / "invalid"
DATA_DIR = SEMANTIC_DIR / "data"
SYNTHETIC_DIR = DATA_DIR / "sintetico"

# Esquemas de dominio (slugs de semantic/uris.md) y marca de sintético.
DOMAIN_SLUGS = ("it", "ot", "pqc", "ia")
SYNTHETIC_TYPE = "vocab/tipo-dataset/sintetico"

BASE_DECL = re.compile(r"^\s*(@base|BASE)\s", re.IGNORECASE | re.MULTILINE)
EXPECT = re.compile(r"^#\s*expect-violation:\s*(\S+)\s*$", re.MULTILINE)


def base_uri() -> str:
    value = os.environ.get("BASE_URI", "").strip() or DEFAULT_BASE_URI
    return value if value.endswith("/") else value + "/"


def rel(path: Path) -> str:
    return str(path.relative_to(SEMANTIC_DIR.parent))


def parse(path: Path, base: str) -> Graph:
    graph = Graph()
    graph.parse(path, format="turtle", publicID=base)
    return graph


def failing_shapes(results: Graph, shapes_ns: str) -> set[str]:
    """Nombres locales de las formas que han producido algún resultado."""
    names = set()
    for result in results.subjects(RDF.type, SH.ValidationResult):
        shape = results.value(result, SH.sourceShape)
        if isinstance(shape, URIRef) and str(shape).startswith(shapes_ns):
            names.add(str(shape)[len(shapes_ns):])
        else:
            names.add(f"<forma sin nombre: {shape}>")
    return names


def main() -> int:
    base = base_uri()
    shapes_ns = base + "shapes#"
    errors: list[str] = []
    print(f"BASE_URI = {base}")

    # 1. Sintaxis de todo .ttl y ausencia de @base.
    ttl_files = sorted(SEMANTIC_DIR.rglob("*.ttl"))
    print(f"\n[1] Sintaxis Turtle ({len(ttl_files)} ficheros)")
    for path in ttl_files:
        text = path.read_text(encoding="utf-8")
        if BASE_DECL.search(text):
            errors.append(f"{rel(path)}: declara @base; las URIs propias deben ser relativas a BASE_URI")
            print(f"  FALLO  {rel(path)} (declara @base)")
            continue
        try:
            parse(path, base)
            print(f"  ok     {rel(path)}")
        except Exception as exc:  # noqa: BLE001 - cualquier error de análisis cuenta
            errors.append(f"{rel(path)}: error de sintaxis: {exc}")
            print(f"  FALLO  {rel(path)}: {exc}")

    # 2. Formas SHACL.
    shape_files = sorted(SHAPES_DIR.glob("*.ttl"))
    print(f"\n[2] Formas SHACL ({len(shape_files)} ficheros)")
    if not shape_files:
        errors.append("no hay formas en semantic/shapes/")
        return report(errors)
    shapes = Graph()
    try:
        for path in shape_files:
            shapes += parse(path, base)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"no se pueden cargar las formas: {exc}")
        return report(errors)
    empty = Graph()
    try:
        validate(empty, shacl_graph=shapes, meta_shacl=True, inference="none")
        print("  ok     las formas cumplen meta-SHACL")
    except Exception as exc:  # noqa: BLE001 - pyshacl lanza si meta-SHACL falla
        errors.append(f"las formas no son SHACL válido: {exc}")
        print(f"  FALLO  meta-SHACL: {exc}")
        return report(errors)

    def run(path: Path) -> tuple[bool, Graph, str] | None:
        try:
            data = parse(path, base)
        except Exception:  # noqa: BLE001 - ya informado en el paso 1
            return None
        conforms, results, text = validate(
            data,
            shacl_graph=shapes,
            inference="none",
            abort_on_first=False,
            allow_warnings=False,
        )
        return conforms, results, text

    # 3. Ejemplos válidos.
    valid_files = sorted(VALID_DIR.glob("*.ttl"))
    print(f"\n[3] Ejemplos válidos ({len(valid_files)} ficheros)")
    if not valid_files:
        errors.append("no hay ejemplos en semantic/examples/valid/")
    for path in valid_files:
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        if conforms:
            print(f"  ok     {rel(path)}")
        else:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")

    # 4. Ejemplos inválidos.
    invalid_files = sorted(INVALID_DIR.glob("*.ttl"))
    print(f"\n[4] Ejemplos inválidos ({len(invalid_files)} ficheros)")
    if not invalid_files:
        errors.append("no hay ejemplos en semantic/examples/invalid/")
    for path in invalid_files:
        expected = set(EXPECT.findall(path.read_text(encoding="utf-8")))
        if not expected:
            errors.append(f"{rel(path)}: falta la línea «# expect-violation: <NombreLocal>»")
            print(f"  FALLO  {rel(path)} (sin expect-violation)")
            continue
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, results, text = outcome
        if conforms:
            errors.append(f"{rel(path)}: debería fallar y cumple las formas")
            print(f"  FALLO  {rel(path)} (cumple las formas)")
            continue
        got = failing_shapes(results, shapes_ns)
        if got == expected:
            print(f"  ok     {rel(path)} falla en {', '.join(sorted(got))}")
        else:
            errors.append(
                f"{rel(path)}: se esperaba que fallara {sorted(expected)} y falla {sorted(got)}"
            )
            print(f"  FALLO  {rel(path)}: esperado {sorted(expected)}, obtenido {sorted(got)}\n{text}")

    # 5. Datos sintéticos, fichero a fichero.
    synthetic_files = sorted(SYNTHETIC_DIR.glob("*.ttl"))
    print(f"\n[5] Datos sintéticos, uno a uno ({len(synthetic_files)} ficheros)")
    if not synthetic_files:
        errors.append("no hay datos en semantic/data/sintetico/")
    for path in synthetic_files:
        outcome = run(path)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        if conforms:
            print(f"  ok     {rel(path)}")
        else:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")

    # 6. Todo semantic/data/ en un grafo: formas y coherencia.
    data_files = sorted(DATA_DIR.rglob("*.ttl"))
    print(f"\n[6] semantic/data/ en un grafo ({len(data_files)} ficheros)")
    combined = Graph()
    try:
        for path in data_files:
            combined.parse(path, format="turtle", publicID=base)
    except Exception as exc:  # noqa: BLE001 - ya informado en el paso 1
        errors.append(f"semantic/data/: no se puede cargar: {exc}")
        return report(errors)
    conforms, _, text = validate(
        combined, shacl_graph=shapes, inference="none", abort_on_first=False, allow_warnings=False
    )
    if conforms:
        print("  ok     cumple las formas")
    else:
        errors.append("semantic/data/: el grafo conjunto no cumple las formas")
        print(f"  FALLO  formas\n{text}")
    synthetic_subjects: set[URIRef] = set()
    for path in synthetic_files:
        graph = parse(path, base)
        for cls in (DCAT.Dataset, DCAT.DatasetSeries):
            synthetic_subjects.update(s for s in graph.subjects(RDF.type, cls) if isinstance(s, URIRef))
    problems = coherence(combined, base, synthetic_subjects)
    for problem in problems:
        errors.append(f"semantic/data/: {problem}")
        print(f"  FALLO  {problem}")
    if not problems:
        print("  ok     coherencia (dominios, marca de sintético, referencias y URIs)")

    return report(errors)


def coherence(g: Graph, base: str, synthetic: set[URIRef]) -> list[str]:
    """Comprobaciones que no son SHACL porque cruzan datos y vocabulario.

    Son reglas de este repositorio sobre sus propios datos, no contrato de
    ingesta: el backend puede recibir versiones cuyos conceptos están en otro
    grafo.
    """
    problems: list[str] = []
    domains = {URIRef(f"{base}vocab/{slug}") for slug in DOMAIN_SLUGS}
    synthetic_type = URIRef(base + SYNTHETIC_TYPE)
    versions = set(g.subjects(RDF.type, DCAT.Dataset))
    series = set(g.subjects(RDF.type, DCAT.DatasetSeries))

    def short(node) -> str:
        return str(node)[len(base):] if str(node).startswith(base) else str(node)

    # Temas: conceptos de un esquema de dominio, y uno solo por versión.
    for version in versions:
        schemes = set()
        for theme in g.objects(version, DCAT.theme):
            in_scheme = set(g.objects(theme, SKOS.inScheme)) & domains
            if (theme, RDF.type, SKOS.Concept) not in g or not in_scheme:
                problems.append(f"{short(version)}: el tema {short(theme)} no es un skos:Concept de un esquema de dominio")
            schemes |= in_scheme
        if len(schemes) > 1:
            problems.append(f"{short(version)}: temas de varios dominios ({', '.join(sorted(map(short, schemes)))})")

    # Marca de sintético en cada serie y versión de semantic/data/sintetico/,
    # y todo dct:type apunta a un concepto conocido.
    for subject in synthetic:
        if (subject, DCTERMS.type, synthetic_type) not in g:
            problems.append(f"{short(subject)}: falta dct:type <{SYNTHETIC_TYPE}>")
    for subject in versions | series:
        for value in g.objects(subject, DCTERMS.type):
            if (value, RDF.type, SKOS.Concept) not in g:
                problems.append(f"{short(subject)}: dct:type {short(value)} no es un skos:Concept del vocabulario")

    # Cada serie tiene dcat:last y sus extremos son versiones suyas.
    for serie in series:
        if g.value(serie, DCAT.last) is None:
            problems.append(f"{short(serie)}: falta dcat:last")
        for prop in (DCAT.first, DCAT.last):
            for target in g.objects(serie, prop):
                if (target, DCAT.inSeries, serie) not in g:
                    problems.append(f"{short(serie)}: {short(prop)} {short(target)} no es una versión de la serie")

    # Versiones: serie y versión anterior descritas, y URIs según uris.md.
    for version in versions:
        serie = g.value(version, DCAT.inSeries)
        if serie not in series:
            problems.append(f"{short(version)}: dcat:inSeries no apunta a una dcat:DatasetSeries descrita")
            continue
        number = g.value(version, DCAT.version)
        if str(version) != f"{serie}/{number}":
            problems.append(f"{short(version)}: la URI no es la de la serie seguida de /{number}")
        for previous in g.objects(version, DCAT.previousVersion):
            if (previous, DCAT.inSeries, serie) not in g:
                problems.append(f"{short(version)}: dcat:previousVersion {short(previous)} no es una versión descrita de la misma serie")
        for dist in g.objects(version, DCAT.distribution):
            if not str(dist).startswith(f"{version}/"):
                problems.append(f"{short(dist)}: la URI no cuelga de la de su versión")
            # Decisión del responsable (2026-11-14): accessURL = la propia URI.
            if set(g.objects(dist, DCAT.accessURL)) != {dist}:
                problems.append(f"{short(dist)}: dcat:accessURL tiene que ser la URI de la propia distribución")

    # Catálogo: cada dcat:dataset es una serie descrita, y están todas.
    for catalog in g.subjects(RDF.type, DCAT.Catalog):
        listed = set(g.objects(catalog, DCAT.dataset))
        for item in listed - series:
            problems.append(f"{short(catalog)}: dcat:dataset {short(item)} no es una dcat:DatasetSeries descrita")
        for item in series - listed:
            problems.append(f"{short(catalog)}: falta dcat:dataset {short(item)}")

    return sorted(problems)


def report(errors: list[str]) -> int:
    if errors:
        print(f"\nValidación FALLIDA ({len(errors)} errores):")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("\nValidación correcta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
