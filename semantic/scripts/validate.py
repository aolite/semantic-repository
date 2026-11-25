# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "rdflib==7.6.0",
#     "pyshacl==0.40.2",
#     "pyarrow==26.0.0",
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
  4. Que cada ejemplo de semantic/examples/invalid/ (y de su subcarpeta
     ontologias-vocabularios/) NO las cumple y que las
     formas que fallan son exactamente las de sus líneas
     «# expect-violation: <NombreLocal>».
  5. Que cada fichero de semantic/data/sintetico/ (lo que ingesta el backend,
     un fichero por dataset) cumple las formas por sí solo.
  6. Que todo semantic/data/**/*.ttl junto (datos, catálogo y esquemas
     auxiliares en un grafo) cumple las formas y es coherente: temas que son
     conceptos de esquemas de dominio (semantic/vocabularios/) y de un único
     dominio, marca de sintético, referencias entre series, versiones y
     distribuciones, URIs según semantic/uris.md y catálogos (el raíz
     agrupa con dcat:catalog los de data/catalogos/{slug}.ttl, que listan
     las series; un fichero por catálogo) y los esquemas SKOS y ontologías
     propias que listan con dcat:resource (decisión 50).
  7. Que cada esquema de semantic/vocabularios/ (un fichero, un esquema, un
     grafo con nombre), junto con el triple de pertenencia a su catálogo que
     da semantic/data/catalogos/ (como hace el backend en la ingesta),
     cumple las formas y es coherente: URI
     según la ruta del fichero, dominio (dct:subject) en los de dominio y no
     en los corporativos, marca de sintético y prefijos VANN únicos.
  8. Que cada versión de semantic/ontologias/{slug}/{version}.ttl (con el
     triple de pertenencia de su ontología) y semantic/ontologias/externas.ttl
     cumplen las formas y son
     coherentes: URIs según la ruta, cadena de owl:priorVersion, términos en
     su espacio de nombres, imports y alineamientos hacia ontologías
     externas catalogadas y dct:subject hacia conceptos existentes.
  9. Que semantic/data/sintetico/ficheros/ tiene un fichero por cada
     distribución PUBLIC o RESTRICTED (salvo los formatos pendientes de
     ficheros_sinteticos.PENDIENTES, hoy ninguno) y ninguno para las NON_PUBLIC, y que
     cada fichero es exactamente el que genera
     semantic/scripts/ficheros_sinteticos.py: tipo según dcat:mediaType,
     marca SINTETICO y como mucho 64 KB.
 10. Que cada consulta de referencia de semantic/consultas/{id}.rq tiene la
     cabecera «# title:» y «# hint:», usa el marcador {BASE_URI} en lugar
     del dominio y, con el marcador sustituido, se analiza y se ejecuta sin
     error sobre los datos, vocabularios y ontologías de semantic/.

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
from rdflib.plugins.sparql import prepareQuery
from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, SKOS

import ficheros_sinteticos  # mismo directorio: semantic/scripts/

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
CATALOGS_DIR = DATA_DIR / "catalogos"
AUX_VOCAB_FILE = DATA_DIR / "vocab-minimo.ttl"
VOCAB_DIR = SEMANTIC_DIR / "vocabularios"
CORP_DIR = VOCAB_DIR / "corp"
ONTO_DIR = SEMANTIC_DIR / "ontologias"
EXTERNAL_FILE = ONTO_DIR / "externas.ttl"
QUERIES_DIR = SEMANTIC_DIR / "consultas"

VANN = Namespace("http://purl.org/vocab/vann/")
ADMS = Namespace("http://www.w3.org/ns/adms#")

# Dominios del catálogo: conceptos {BASE_URI}vocab/dominio/{slug}
# (semantic/uris.md) y marca de sintético.
DOMAIN_SLUGS = ("it", "ot", "pqc", "ia")
SYNTHETIC_TYPE = "vocab/tipo-dataset/sintetico"
# Segmentos de vocab/ que no pueden ser slug de un esquema de dominio.
RESERVED_VOCAB_SLUGS = ("corp", "dominio", "tipo-dataset")
# Mientras todo el contenido de ontologias/ y vocabularios/ sea sintético
# (hasta el piloto), cada ontología propia y cada esquema lleva la marca.
REQUIRE_SYNTHETIC_MARK = True

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEMVER = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")

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

    def run(path: Path, membership: Graph | None = None) -> tuple[bool, Graph, str] | None:
        """Valida un fichero. ``membership`` son los triples «<catálogo>
        dcat:resource <recurso>» de semantic/data/catalogos/: si se pasa, se
        añaden los que apuntan a un sujeto del fichero, igual que el backend
        añade el del catálogo elegido antes de validar (decisión 50)."""
        try:
            data = parse(path, base)
        except Exception:  # noqa: BLE001 - ya informado en el paso 1
            return None
        if membership is not None:
            subjects = set(data.subjects())
            for triple in membership.triples((None, DCAT.resource, None)):
                if triple[2] in subjects:
                    data.add(triple)
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
    # Raíz: datasets (los que el backend pasa por su ingesta de datasets).
    # Subcarpeta ontologias-vocabularios/: esquemas SKOS y ontologías.
    invalid_files = sorted(INVALID_DIR.rglob("*.ttl"))
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

    # 6. Todo semantic/data/ en un grafo: formas y coherencia. Los ficheros de
    # distribución (data/sintetico/ficheros/) son contenido, no metadatos.
    data_files = sorted(p for p in DATA_DIR.rglob("*.ttl") if ficheros_sinteticos.FILES_DIR not in p.parents)
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
    for problem in catalog_files(base):
        errors.append(problem)
        print(f"  FALLO  {problem}")
    synthetic_subjects: set[URIRef] = set()
    for path in synthetic_files:
        graph = parse(path, base)
        for cls in (DCAT.Dataset, DCAT.DatasetSeries):
            synthetic_subjects.update(s for s in graph.subjects(RDF.type, cls) if isinstance(s, URIRef))
    # Vocabulario completo (esquemas auxiliares y todos los de vocabularios/),
    # para comprobar los temas de los datasets y los dct:subject.
    vocab_files = sorted(VOCAB_DIR.rglob("*.ttl"))
    vocab = Graph()
    try:
        vocab += parse(AUX_VOCAB_FILE, base)
        for path in vocab_files:
            vocab += parse(path, base)
    except Exception as exc:  # noqa: BLE001 - ya informado en el paso 1
        errors.append(f"semantic/vocabularios/: no se puede cargar: {exc}")
        return report(errors)

    problems = coherence(combined, base, synthetic_subjects, vocab)
    for problem in problems:
        errors.append(f"semantic/data/: {problem}")
        print(f"  FALLO  {problem}")
    if not problems:
        print("  ok     coherencia (dominios, marca de sintético, referencias y URIs)")

    # Pertenencia de esquemas y ontologías a su catálogo (decisión 50): vive
    # solo en el grafo del catálogo, no en los ficheros de vocabularios/ ni de
    # ontologias/. Para validarlos se les añade su triple.
    membership = Graph()
    for triple in combined.triples((None, DCAT.resource, None)):
        membership.add(triple)

    # 7. Esquemas SKOS, uno a uno: formas y coherencia.
    print(f"\n[7] Esquemas SKOS de semantic/vocabularios/, uno a uno ({len(vocab_files)} ficheros)")
    if not vocab_files:
        errors.append("no hay esquemas en semantic/vocabularios/")
    prefixes: dict[str, list[str]] = {}
    for path in vocab_files:
        outcome = run(path, membership)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        problems = scheme_coherence(path, parse(path, base), base, vocab, prefixes)
        if not conforms:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")
        for problem in problems:
            errors.append(f"{rel(path)}: {problem}")
            print(f"  FALLO  {rel(path)}: {problem}")
        if conforms and not problems:
            print(f"  ok     {rel(path)}")

    # 8. Ontologías, versión a versión, y externas: formas y coherencia.
    onto_files = sorted(p for p in ONTO_DIR.rglob("*.ttl") if p != EXTERNAL_FILE)
    print(f"\n[8] Ontologías de semantic/ontologias/ ({len(onto_files)} versiones y externas.ttl)")
    if not onto_files:
        errors.append("no hay ontologías propias en semantic/ontologias/")
    if not EXTERNAL_FILE.exists():
        errors.append(f"falta {rel(EXTERNAL_FILE)}")
        return report(errors)
    external = parse(EXTERNAL_FILE, base)
    for path in [*onto_files, EXTERNAL_FILE]:
        outcome = run(path, membership)
        if outcome is None:
            errors.append(f"{rel(path)}: no se puede validar (sintaxis)")
            continue
        conforms, _, text = outcome
        graph = parse(path, base)
        if path == EXTERNAL_FILE:
            problems = external_coherence(graph, base, prefixes)
        else:
            problems = ontology_coherence(path, graph, base, vocab, external, onto_files, prefixes)
        if not conforms:
            errors.append(f"{rel(path)}: debería cumplir las formas y no las cumple")
            print(f"  FALLO  {rel(path)}\n{text}")
        for problem in problems:
            errors.append(f"{rel(path)}: {problem}")
            print(f"  FALLO  {rel(path)}: {problem}")
        if conforms and not problems:
            print(f"  ok     {rel(path)}")

    # Catálogos de los esquemas y las ontologías (decisión 50).
    problems = resource_catalogs(combined, base, vocab_files, onto_files, external)
    for problem in problems:
        errors.append(f"semantic/data/catalogos/: {problem}")
        print(f"  FALLO  {problem}")
    if not problems:
        print("  ok     cada esquema y cada ontología propia, en exactamente un catálogo")

    # Prefijos VANN únicos entre esquemas y ontologías (las versiones de una
    # misma ontología comparten el suyo).
    for prefix, owners in sorted(prefixes.items()):
        if len(set(owners)) > 1:
            errors.append(f"prefijo VANN «{prefix}» repetido en {', '.join(sorted(set(owners)))}")
            print(f"  FALLO  prefijo VANN «{prefix}» repetido en {', '.join(sorted(set(owners)))}")

    # 9. Ficheros sintéticos de distribución.
    print(f"\n[9] Ficheros de distribución de {rel(ficheros_sinteticos.FILES_DIR)}/")
    for problem in distribution_files(base):
        errors.append(problem)
        print(f"  FALLO  {problem}")

    # 10. Consultas de referencia.
    knowledge = Graph()
    for path in [*data_files, *vocab_files, *onto_files, EXTERNAL_FILE]:
        knowledge += parse(path, base)
    query_files = sorted(QUERIES_DIR.glob("*.rq"))
    print(f"\n[10] Consultas de referencia de {rel(QUERIES_DIR)}/ ({len(query_files)} ficheros)")
    if not query_files:
        errors.append(f"no hay consultas en {rel(QUERIES_DIR)}/")
    for path in query_files:
        problems, rows = reference_query(path, base, knowledge)
        for problem in problems:
            errors.append(f"{rel(path)}: {problem}")
            print(f"  FALLO  {rel(path)}: {problem}")
        if not problems:
            print(f"  ok     {rel(path)} ({rows} filas con los datos de semantic/)")

    return report(errors)


QUERY_HEADER = re.compile(r"^# (title|hint): (.+)$")


def reference_query(path: Path, base: str, knowledge: Graph) -> tuple[list[str], int]:
    """Una consulta de referencia: cabecera, marcador {BASE_URI} y ejecución.

    La cabecera son las primeras líneas «# title: …» y «# hint: …». Los IRIs
    propios se escriben <{BASE_URI}…>: el backend sustituye el marcador al
    servirla (contrato de la fase 4, 3.2).
    """
    problems: list[str] = []
    if not SLUG.match(path.stem):
        problems.append(f"el nombre del fichero no es un slug válido ({path.stem})")
    text = path.read_text(encoding="utf-8")
    header: dict[str, str] = {}
    for line in text.splitlines():
        match = QUERY_HEADER.match(line)
        if not match:
            break
        header[match.group(1)] = match.group(2).strip()
    if not header.get("title"):
        problems.append("falta la cabecera «# title: …» al principio del fichero")
    if not header.get("hint"):
        problems.append("falta la cabecera «# hint: …» tras el título")
    if base in text or DEFAULT_BASE_URI in text:
        problems.append("escribe el dominio; los IRIs propios usan el marcador {BASE_URI}")
    if re.search(r"\{(?!BASE_URI\})[A-Za-z_]+\}", text):
        problems.append("usa un marcador distinto de {BASE_URI}")
    query = text.replace("{BASE_URI}", base)
    try:
        prepared = prepareQuery(query)
        rows = len(list(knowledge.query(prepared)))
    except Exception as exc:  # noqa: BLE001 - cualquier error de análisis o ejecución cuenta
        problems.append(f"no se ejecuta: {exc}")
        rows = 0
    return problems, rows


def distribution_files(base: str) -> list[str]:
    """Ficheros de distribución: uno por PUBLIC/RESTRICTED, ninguno NON_PUBLIC."""
    fs = ficheros_sinteticos
    problems: list[str] = []
    expected = fs.expected_files(base)
    for d in fs.distributions(base):
        path = d.path
        if d.access in fs.WITHOUT_FILE:
            print(f"  ok     {d.key}: {d.access}, sin fichero")
        elif not d.needs_file:
            problems.append(f"{d.key}: dct:accessRights {d.access!r} no es PUBLIC, RESTRICTED ni NON_PUBLIC")
        elif d.ext is None:
            problems.append(f"{d.key}: sin extensión conocida para el tipo de medio {d.media_type!r}")
        elif d.ext in fs.PENDIENTES:
            if path.exists():
                problems.append(f"{rel(path)}: el formato está pendiente y no debería tener fichero")
            else:
                print(f"  PENDIENTE  {d.key} ({d.ext}): {fs.PENDIENTES[d.ext]}")
        elif not path.is_file():
            problems.append(f"{d.key}: {d.access} y sin fichero; ejecuta semantic/scripts/ficheros_sinteticos.py")
        else:
            data = path.read_bytes()
            if data != expected[path]:
                problems.append(f"{rel(path)}: no es el que genera ficheros_sinteticos.py; regenéralo")
            elif len(data) > fs.MAX_BYTES:
                problems.append(f"{rel(path)}: ocupa {len(data)} bytes, más de {fs.MAX_BYTES}")
            elif fs.MARK.encode("ascii") not in data:
                problems.append(f"{rel(path)}: falta la marca {fs.MARK}")
            else:
                print(f"  ok     {rel(path)} ({d.access}, {d.media_type or 'sin dcat:mediaType'}, {len(data)} bytes)")
    # Nada más en la carpeta: ni ficheros de distribuciones NON_PUBLIC ni restos.
    if fs.FILES_DIR.is_dir():
        for path in sorted(fs.FILES_DIR.rglob("*")):
            if path.is_file() and path not in expected:
                problems.append(f"{rel(path)}: no corresponde a ninguna distribución PUBLIC o RESTRICTED")
    return problems


def catalog_files(base: str) -> list[str]:
    """data/catalogos/{slug}.ttl describe solo el catálogo {BASE_URI}catalogo/{slug}."""
    problems: list[str] = []
    for path in sorted(CATALOGS_DIR.glob("*.ttl")):
        graph = parse(path, base)
        expected = URIRef(f"{base}catalogo/{path.stem}")
        if not SLUG.match(path.stem):
            problems.append(f"{rel(path)}: el nombre del fichero no es un slug válido")
        found = set(graph.subjects(RDF.type, DCAT.Catalog))
        if found != {expected}:
            problems.append(f"{rel(path)}: tiene que describir exactamente un dcat:Catalog, catalogo/{path.stem}")
        for subject in set(graph.subjects()):
            if isinstance(subject, URIRef) and subject != expected:
                problems.append(f"{rel(path)}: describe {subject}, que no es el catálogo del fichero")
    return problems


def resource_catalogs(
    g: Graph, base: str, vocab_files: list[Path], onto_files: list[Path], external: Graph
) -> list[str]:
    """dcat:resource de los catálogos (decisión 50) sobre semantic/data/.

    Cada esquema de vocabularios/ y cada ontología propia de ontologias/ está
    en exactamente un catálogo catalogo/{slug}; el raíz no lista recursos; los
    esquemas auxiliares y las ontologías externas no están en ninguno, y
    dcat:resource solo apunta a esquemas u ontologías del repositorio (nunca
    a una versión). SHACL comprueba lo mismo fichero a fichero; aquí se
    cruzan todos los catálogos.
    """
    problems: list[str] = []
    short = short_of(base)
    schemes = {
        URIRef(f"{base}vocab/corp/{p.stem}" if p.parent == CORP_DIR else f"{base}vocab/{p.stem}")
        for p in vocab_files
    }
    ontologies = {URIRef(f"{base}onto/{p.parent.name}") for p in onto_files}
    wanted = schemes | ontologies
    root = URIRef(f"{base}catalogo")
    children = {c for c in g.subjects(RDF.type, DCAT.Catalog) if c != root}
    found: dict[URIRef, set] = {}
    for catalog, item in g.subject_objects(DCAT.resource):
        if catalog not in children:
            problems.append(f"{short(catalog)}: dcat:resource {short(item)} desde algo que no es un catálogo catalogo/{{slug}} descrito")
        if item not in wanted:
            problems.append(f"{short(catalog)}: dcat:resource {short(item)} no es un esquema de vocabularios/ ni una ontología propia de ontologias/")
        found.setdefault(item, set()).add(catalog)
    for item in sorted(wanted, key=str):
        catalogs = found.get(item, set())
        if len(catalogs) != 1:
            problems.append(f"{short(item)}: tiene que estar en exactamente un catálogo y está en {len(catalogs)}")
    for onto in external.subjects(RDF.type, OWL.Ontology):
        if onto in found:
            problems.append(f"{short(onto)}: una ontología externa no está en ningún catálogo")
    return sorted(problems)


def short_of(base: str):
    def short(node) -> str:
        return str(node)[len(base):] if str(node).startswith(base) else str(node)

    return short


def domain_of(vocab: Graph, base: str, concept) -> set[URIRef]:
    """Dominios (conceptos de vocab/dominio) del esquema de un concepto."""
    domains = {URIRef(f"{base}vocab/dominio/{slug}") for slug in DOMAIN_SLUGS}
    found: set[URIRef] = set()
    for scheme in vocab.objects(concept, SKOS.inScheme):
        found |= set(vocab.objects(scheme, DCTERMS.subject)) & domains
    return found


def scheme_coherence(path: Path, g: Graph, base: str, vocab: Graph, prefixes: dict[str, list[str]]) -> list[str]:
    """Un fichero de vocabularios/: URI según la ruta, dominio y contenido.

    La ruta decide el tipo: vocabularios/{slug}.ttl es un esquema de dominio
    ({BASE_URI}vocab/{slug}, con dct:subject) y vocabularios/corp/{slug}.ttl,
    uno corporativo ({BASE_URI}vocab/corp/{slug}, sin dct:subject).
    """
    problems: list[str] = []
    short = short_of(base)
    slug = path.stem
    corporate = path.parent == CORP_DIR
    if path.parent not in (VOCAB_DIR, CORP_DIR):
        return [f"ubicación no prevista; los esquemas van en {rel(VOCAB_DIR)}/ o {rel(CORP_DIR)}/"]
    if not SLUG.match(slug):
        problems.append(f"el nombre del fichero no es un slug válido ({slug})")
    if not corporate and slug in RESERVED_VOCAB_SLUGS:
        problems.append(f"«{slug}» es un segmento reservado de vocab/")
    expected = URIRef(f"{base}vocab/corp/{slug}" if corporate else f"{base}vocab/{slug}")
    schemes = set(g.subjects(RDF.type, SKOS.ConceptScheme))
    if schemes != {expected}:
        problems.append(f"tiene que describir exactamente un skos:ConceptScheme, {short(expected)}; describe {sorted(map(short, schemes))}")
        return problems

    domains = {URIRef(f"{base}vocab/dominio/{s}") for s in DOMAIN_SLUGS}
    subjects = set(g.objects(expected, DCTERMS.subject))
    if corporate and subjects:
        problems.append("un esquema corporativo no lleva dominio (dct:subject)")
    if not corporate and (len(subjects) != 1 or not subjects <= domains):
        problems.append(f"un esquema de dominio declara exactamente un dct:subject de vocab/dominio/{{{'|'.join(DOMAIN_SLUGS)}}}")
    for value in g.objects(expected, DCTERMS.type):
        if (value, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:type {short(value)} no es un skos:Concept del vocabulario")
    if REQUIRE_SYNTHETIC_MARK and (expected, DCTERMS.type, URIRef(base + SYNTHETIC_TYPE)) not in g:
        problems.append(f"falta dct:type <{SYNTHETIC_TYPE}>")

    # Todo sujeto con IRI bajo BASE_URI es el esquema o uno de sus conceptos:
    # un fichero no puede describir recursos de otro grafo.
    for subject in set(g.subjects()):
        if isinstance(subject, BNode) or not str(subject).startswith(base) or subject == expected:
            continue
        if (subject, SKOS.inScheme, expected) not in g:
            problems.append(f"describe {short(subject)}, que no es un concepto de este esquema")

    if (None, DCAT.resource, None) in g:
        problems.append("la pertenencia al catálogo (dcat:resource) no va en el fichero, sino en data/catalogos/")

    for prefix in g.objects(expected, VANN.preferredNamespacePrefix):
        prefixes.setdefault(str(prefix), []).append(rel(path))
    return problems


def ontology_coherence(
    path: Path,
    g: Graph,
    base: str,
    vocab: Graph,
    external: Graph,
    all_versions: list[Path],
    prefixes: dict[str, list[str]],
) -> list[str]:
    """Una versión de ontología propia: ontologias/{slug}/{version}.ttl."""
    problems: list[str] = []
    short = short_of(base)
    slug, version = path.parent.name, path.stem
    if path.parent.parent != ONTO_DIR or not SLUG.match(slug) or not SEMVER.match(version):
        return [f"ubicación no prevista; las versiones van en {rel(ONTO_DIR)}/{{slug}}/{{version}}.ttl"]
    onto = URIRef(f"{base}onto/{slug}")
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    if ontologies != {onto}:
        return [f"tiene que describir exactamente una owl:Ontology, {short(onto)}; describe {sorted(map(short, ontologies))}"]

    # versionIRI y versionInfo según la ruta (las formas comprueban que
    # versionIRI = URI/versionInfo).
    if set(g.objects(onto, OWL.versionIRI)) != {URIRef(f"{onto}/{version}")}:
        problems.append(f"owl:versionIRI tiene que ser {short(onto)}/{version}")
    if {str(v) for v in g.objects(onto, OWL.versionInfo)} != {version}:
        problems.append(f"owl:versionInfo tiene que ser «{version}», como el nombre del fichero")
    # Prefijo VANN = slug [PROPUESTA]: así lo hace el prototipo (itot, pqcm, didx).
    prefix_values = {str(v) for v in g.objects(onto, VANN.preferredNamespacePrefix)}
    if prefix_values != {slug}:
        problems.append(f"vann:preferredNamespacePrefix tiene que ser «{slug}», el slug de la ontología")
    for prefix in prefix_values:
        prefixes.setdefault(prefix, []).append(f"{rel(ONTO_DIR)}/{slug}/")

    # Cadena de versiones: la primera no tiene priorVersion y cada una de las
    # siguientes apunta a la inmediatamente anterior que hay en el repositorio.
    def key(v: str) -> tuple[int, ...]:
        return tuple(int(n) for n in v.split("."))

    siblings = sorted((p.stem for p in all_versions if p.parent == path.parent and SEMVER.match(p.stem)), key=key)
    earlier = [v for v in siblings if key(v) < key(version)]
    prior = set(g.objects(onto, OWL.priorVersion))
    expected_prior = {URIRef(f"{onto}/{earlier[-1]}")} if earlier else set()
    if prior != expected_prior:
        want = short(next(iter(expected_prior))) if expected_prior else "ninguna"
        problems.append(f"owl:priorVersion tiene que ser {want} (versión anterior en el repositorio)")
    for prop in (OWL.backwardCompatibleWith, OWL.incompatibleWith):
        for target in g.objects(onto, prop):
            if target not in {URIRef(f"{onto}/{v}") for v in earlier}:
                problems.append(f"{short(prop)} {short(target)} no es una versión anterior de esta ontología")

    # Marca de sintético y estado.
    for value in g.objects(onto, DCTERMS.type):
        if (value, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:type {short(value)} no es un skos:Concept del vocabulario")
    if REQUIRE_SYNTHETIC_MARK and (onto, DCTERMS.type, URIRef(base + SYNTHETIC_TYPE)) not in g:
        problems.append(f"falta dct:type <{SYNTHETIC_TYPE}>")

    # dct:subject: conceptos SKOS existentes.
    for concept in g.objects(onto, DCTERMS.subject):
        if (concept, RDF.type, SKOS.Concept) not in vocab:
            problems.append(f"dct:subject {short(concept)} no es un skos:Concept de semantic/vocabularios/")

    # La pertenencia al catálogo no va en la versión (decisión 50 [PROPUESTA]):
    # las versiones son inmutables (decisión 28) y el catálogo puede cambiar.
    if (None, DCAT.resource, None) in g:
        problems.append("la pertenencia al catálogo (dcat:resource) no va en la versión, sino en data/catalogos/")

    # Términos propios en {URI}#; ningún otro recurso bajo BASE_URI.
    namespace = f"{onto}#"
    for subject in set(g.subjects()):
        if isinstance(subject, BNode) or not str(subject).startswith(base) or subject == onto:
            continue
        if not str(subject).startswith(namespace):
            problems.append(f"describe {short(subject)}, fuera del espacio de nombres {short(namespace)}")

    # owl:imports hacia ontologías externas catalogadas, y clases externas
    # (destinos de alineamiento) en el espacio de nombres de una de ellas.
    catalogued = set(external.subjects(RDF.type, OWL.Ontology))
    for target in g.objects(onto, OWL.imports):
        if target not in catalogued:
            problems.append(f"owl:imports {short(target)} no está en {rel(EXTERNAL_FILE)}")
    external_ns = [str(ns) for ns in external.objects(None, VANN.preferredNamespaceUri)]
    for cls in set(g.subjects(RDF.type, OWL.Class)):
        if isinstance(cls, URIRef) and not str(cls).startswith(namespace):
            if not any(str(cls).startswith(ns) for ns in external_ns):
                problems.append(f"la clase externa {short(cls)} no pertenece a ninguna ontología de {rel(EXTERNAL_FILE)}")
    for cls, parent in g.subject_objects(RDFS.subClassOf):
        if isinstance(parent, URIRef) and not str(parent).startswith(namespace) and (parent, RDF.type, OWL.Class) not in g:
            problems.append(f"{short(cls)} rdfs:subClassOf {short(parent)}: la clase externa no está declarada (owl:Class)")
    return problems


def external_coherence(g: Graph, base: str, prefixes: dict[str, list[str]]) -> list[str]:
    """externas.ttl: solo referencias, con la IRI oficial (fuera de BASE_URI)."""
    problems: list[str] = []
    short = short_of(base)
    ontologies = set(g.subjects(RDF.type, OWL.Ontology))
    if not ontologies:
        problems.append("no describe ninguna owl:Ontology")
    for onto in ontologies:
        if str(onto).startswith(base):
            problems.append(f"{short(onto)}: una ontología externa tiene la IRI oficial, fuera de BASE_URI")
        if g.value(onto, OWL.versionIRI) is not None:
            problems.append(f"{short(onto)}: una ontología externa no lleva owl:versionIRI (identifica las propias)")
        if g.value(onto, ADMS.status) is not None:
            problems.append(f"{short(onto)}: una ontología externa no lleva adms:status (su estado es «Referenciada»)")
        for prefix in g.objects(onto, VANN.preferredNamespacePrefix):
            prefixes.setdefault(str(prefix), []).append(f"{rel(EXTERNAL_FILE)} ({onto})")
    for subject in set(g.subjects()):
        if isinstance(subject, URIRef) and str(subject).startswith(base):
            problems.append(f"describe {short(subject)}, un recurso bajo BASE_URI")
    return problems


def coherence(g: Graph, base: str, synthetic: set[URIRef], vocab: Graph) -> list[str]:
    """Comprobaciones que no son SHACL porque cruzan datos y vocabulario.

    Son reglas de este repositorio sobre sus propios datos, no contrato de
    ingesta: el backend puede recibir versiones cuyos conceptos están en otro
    grafo.
    """
    problems: list[str] = []
    synthetic_type = URIRef(base + SYNTHETIC_TYPE)
    versions = set(g.subjects(RDF.type, DCAT.Dataset))
    series = set(g.subjects(RDF.type, DCAT.DatasetSeries))
    short = short_of(base)

    # Temas: conceptos de un esquema de dominio (con dct:subject hacia
    # vocab/dominio), y de un solo dominio por versión. «PQC e identidad»
    # tiene dos esquemas (pqc y did): lo que cuenta es el dominio, no el
    # esquema.
    for version in versions:
        found = set()
        for theme in g.objects(version, DCAT.theme):
            theme_domains = domain_of(vocab, base, theme)
            if (theme, RDF.type, SKOS.Concept) not in vocab or not theme_domains:
                problems.append(f"{short(version)}: el tema {short(theme)} no es un skos:Concept de un esquema de dominio")
            found |= theme_domains
        if len(found) > 1:
            problems.append(f"{short(version)}: temas de varios dominios ({', '.join(sorted(map(short, found)))})")

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

    # Catálogos (decisión 49) [PROPUESTA]: el raíz {BASE_URI}catalogo agrupa
    # con dcat:catalog los catálogos {BASE_URI}catalogo/{slug}, y solo estos
    # listan series con dcat:dataset. Que cada serie esté en exactamente un
    # catálogo lo comprueba la forma itsh:DatasetSeries-catalog.
    root = URIRef(f"{base}catalogo")
    catalogs = set(g.subjects(RDF.type, DCAT.Catalog))
    children = catalogs - {root}
    if root not in catalogs:
        problems.append("falta el catálogo raíz catalogo (semantic/data/catalogo.ttl)")
    for item in g.objects(root, DCAT.dataset):
        problems.append(f"catalogo: el catálogo raíz no lista series; dcat:dataset {short(item)} va en un catalogo/{{slug}}")
    listed_catalogs = set(g.objects(root, DCAT.catalog))
    for item in listed_catalogs - children:
        problems.append(f"catalogo: dcat:catalog {short(item)} no es un dcat:Catalog descrito")
    for catalog in children:
        slug = str(catalog)[len(f"{base}catalogo/"):] if str(catalog).startswith(f"{base}catalogo/") else ""
        if not SLUG.match(slug):
            problems.append(f"{short(catalog)}: la URI de un catálogo es catalogo/{{slug}}")
        if catalog not in listed_catalogs:
            problems.append(f"catalogo: falta dcat:catalog {short(catalog)}")
        for item in g.objects(catalog, DCAT.catalog):
            problems.append(f"{short(catalog)}: solo el catálogo raíz agrupa catálogos (dcat:catalog {short(item)})")
    for catalog, item in g.subject_objects(DCAT.dataset):
        if catalog not in children and catalog != root:  # el raíz ya se informa arriba
            problems.append(f"{short(catalog)}: dcat:dataset {short(item)} desde algo que no es un catálogo catalogo/{{slug}} descrito")
        if item not in series:
            problems.append(f"{short(catalog)}: dcat:dataset {short(item)} no es una dcat:DatasetSeries descrita")

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
