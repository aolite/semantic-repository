"""SPARQL público de solo lectura a través del backend (decisión 42).

Validación **antes** de enviar nada a Fuseki, con el analizador de rdflib:

- Como mucho ``MAX_QUERY_BYTES`` (20 KB; si no, 413).
- Solo ``SELECT``, ``ASK``, ``CONSTRUCT`` y ``DESCRIBE``. Una actualización
  (``INSERT``, ``DELETE``, ``LOAD``, ``DROP``…) da 400, y lo que no se puede analizar,
  400 con un mensaje legible y sin trazas.
- Sin ``SERVICE`` en ningún punto de la consulta (evita SSRF y federación): 400.
- ``FROM`` y ``FROM NAMED`` solo hacia grafos del repositorio: IRIs bajo ``BASE_URI``
  (todos los grafos del triplestore que escribe el backend están ahí y son públicos). Fuseki
  no descarga IRIs remotas en ``FROM``, pero así ni siquiera se le piden.

Ejecución contra el endpoint de **consulta** de Fuseki (``/{dataset}/query``, anónimo y de
solo lectura), con ``SPARQL_TIMEOUT_SECONDS`` como tiempo máximo total (504 al
superarlo). El grafo por defecto es el de Fuseki (``tdb2:unionDefaultGraph true`` en la
configuración de ``infra``): las consultas sin ``GRAPH`` ven la unión de los grafos, como
esperan las consultas de referencia de ``semantic/consultas/``.

Resultados acotados a ``SPARQL_MAX_ROWS`` filas (SELECT) o triples (CONSTRUCT/DESCRIBE);
si se recortan, ``truncated=True`` (cabecera ``X-Result-Truncated: true``). Todo se lee
en streaming y se corta la conexión al llegar al límite: los triples en N-Triples, línea a
línea; las filas en JSON, fila a fila (``_SelectStream``). ``MAX_RESPONSE_BYTES`` acota lo
que se procesa: si se alcanza antes de ``SPARQL_MAX_ROWS`` filas, el resultado también se
recorta (con la misma cabecera); solo da 400 si ni siquiera se puede leer la cabecera o
una sola fila con ese tope.
"""

import codecs
import csv
import io
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import pyparsing
from rdflib import BNode, Dataset, Graph, URIRef
from rdflib import Literal as RdfLiteral
from rdflib.plugins.sparql.algebra import translateQuery
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate
from rdflib.plugins.sparql.parserutils import CompValue

QueryKind = Literal["SELECT", "ASK", "CONSTRUCT", "DESCRIBE"]

MAX_QUERY_BYTES = 20 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 3.0
READ_CHUNK_BYTES = 64 * 1024

_KINDS: dict[str, QueryKind] = {
    "SelectQuery": "SELECT",
    "AskQuery": "ASK",
    "ConstructQuery": "CONSTRUCT",
    "DescribeQuery": "DESCRIBE",
}


class SparqlRequestError(Exception):
    """Consulta rechazada (400 o 413) con un mensaje legible."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SparqlTimeoutError(Exception):
    """La consulta superó ``SPARQL_TIMEOUT_SECONDS``."""


class SparqlBackendError(Exception):
    """Fuseki no responde o falla."""


@dataclass(frozen=True)
class ValidatedQuery:
    text: str
    kind: QueryKind


def _walk(node: Any) -> Any:
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, CompValue):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list | tuple | pyparsing.ParseResults):
            stack.extend(current)


def validate(text: str, base_uri: str) -> ValidatedQuery:
    if len(text.encode("utf-8")) > MAX_QUERY_BYTES:
        raise SparqlRequestError("La consulta supera el máximo de 20 KB", status_code=413)
    if not text.strip():
        raise SparqlRequestError("La consulta está vacía")
    try:
        parsed = parseQuery(text)
    except (pyparsing.ParseException, pyparsing.ParseBaseException) as exc:
        try:
            parseUpdate(text)
        except Exception:  # noqa: BLE001 - no es una actualización: error de sintaxis
            line = getattr(exc, "lineno", None)
            column = getattr(exc, "col", None)
            where = f" (línea {line}, columna {column})" if line and column else ""
            raise SparqlRequestError(f"Error de sintaxis SPARQL{where}") from None
        raise SparqlRequestError(
            "El endpoint es de solo lectura: solo se admiten SELECT, ASK, CONSTRUCT y DESCRIBE"
        ) from None
    except Exception:  # noqa: BLE001 - p. ej. RecursionError en consultas patológicas
        raise SparqlRequestError("Error de sintaxis SPARQL") from None
    query = parsed[1] if len(parsed) > 1 else None
    kind = _KINDS.get(getattr(query, "name", ""))
    if kind is None:
        raise SparqlRequestError("Solo se admiten SELECT, ASK, CONSTRUCT y DESCRIBE")
    if any(node.name == "ServiceGraphPattern" for node in _walk(parsed)):
        raise SparqlRequestError("SERVICE no está permitido (consultas federadas)")
    _check_dataset_clause(parsed, base_uri)
    return ValidatedQuery(text=text, kind=kind)


def _check_dataset_clause(parsed: Any, base_uri: str) -> None:
    if not any(node.name == "DatasetClause" for node in _walk(parsed)):
        return
    try:
        clauses = translateQuery(parsed).algebra.get("datasetClause") or []
    except Exception:  # noqa: BLE001 - sin poder resolver las IRIs, se rechaza
        raise SparqlRequestError("FROM / FROM NAMED no válido") from None
    for clause in clauses:
        target = clause.get("default") or clause.get("named")
        if not isinstance(target, URIRef) or not str(target).startswith(base_uri):
            raise SparqlRequestError(
                "FROM y FROM NAMED solo admiten grafos del repositorio (bajo BASE_URI)"
            )


# --- Resultados ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    kind: QueryKind
    variables: list[str] = field(default_factory=list)
    bindings: list[dict[str, dict[str, str]]] = field(default_factory=list)
    boolean: bool | None = None
    graph: Graph | None = None
    truncated: bool = False

    def to_json(self) -> str:
        if self.kind == "ASK":
            return json.dumps({"head": {}, "boolean": bool(self.boolean)})
        return json.dumps(
            {"head": {"vars": self.variables}, "results": {"bindings": self.bindings}},
            ensure_ascii=False,
        )

    def to_csv(self) -> str:
        """SPARQL 1.1 Query Results CSV: cabecera con las variables y valores sin marcas."""
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        if self.kind == "ASK":
            writer.writerow(["boolean"])
            writer.writerow(["true" if self.boolean else "false"])
            return out.getvalue()
        writer.writerow(self.variables)
        for row in self.bindings:
            values = []
            for var in self.variables:
                term = row.get(var)
                if term is None:
                    values.append("")
                elif term.get("type") == "bnode":
                    values.append(f"_:{term['value']}")
                else:
                    values.append(term.get("value", ""))
            writer.writerow(values)
        return out.getvalue()


def _term_json(term: Any) -> dict[str, str]:
    if isinstance(term, URIRef):
        return {"type": "uri", "value": str(term)}
    if isinstance(term, BNode):
        return {"type": "bnode", "value": str(term)}
    if isinstance(term, RdfLiteral):
        data: dict[str, str] = {"type": "literal", "value": str(term)}
        if term.language:
            data["xml:lang"] = term.language
        elif term.datatype:
            data["datatype"] = str(term.datatype)
        return data
    return {"type": "literal", "value": str(term)}


# --- Ejecución ------------------------------------------------------------------------------


class FusekiQueryRunner:
    """Ejecuta consultas públicas contra ``/{dataset}/query`` de Fuseki (sin credenciales)."""

    def __init__(
        self,
        base_url: str,
        dataset: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = f"{base_url}/{dataset}/query"
        self._transport = transport

    def run(self, query: ValidatedQuery, *, max_rows: int, timeout: float) -> QueryResult:
        deadline = time.monotonic() + timeout
        graph_result = query.kind in ("CONSTRUCT", "DESCRIBE")
        accept = "application/n-triples" if graph_result else "application/sparql-results+json"
        try:
            with (
                httpx.Client(
                    timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT_SECONDS),
                    transport=self._transport,
                ) as client,
                client.stream(
                    "POST",
                    self._endpoint,
                    # ``timeout`` es el parámetro de Fuseki (segundos) para cortar la consulta
                    # en el servidor; el cliente corta igualmente al agotar el plazo.
                    data={"query": query.text, "timeout": f"{timeout:g}"},
                    headers={"Accept": accept},
                ) as response,
            ):
                if response.status_code == 503:
                    raise SparqlTimeoutError()
                if response.status_code == 400:
                    raise SparqlRequestError("Fuseki rechazó la consulta (error de sintaxis)")
                if response.status_code >= 400:
                    raise SparqlBackendError(f"Fuseki respondió {response.status_code}")
                if graph_result:
                    return self._read_triples(response, query.kind, max_rows, deadline)
                return self._read_json(response, query.kind, max_rows, deadline)
        except httpx.TimeoutException as exc:
            raise SparqlTimeoutError() from exc
        except httpx.HTTPError as exc:
            raise SparqlBackendError("Fuseki no responde") from exc

    @staticmethod
    def _check_deadline(deadline: float) -> None:
        if time.monotonic() > deadline:
            raise SparqlTimeoutError()

    def _read_json(
        self, response: httpx.Response, kind: QueryKind, max_rows: int, deadline: float
    ) -> QueryResult:
        chunks = response.iter_bytes(READ_CHUNK_BYTES)
        stream = _SelectStream(chunks, lambda: self._check_deadline(deadline), MAX_RESPONSE_BYTES)
        try:
            return stream.read(kind, max_rows)
        except _TooLargeError:
            raise SparqlRequestError(
                "El resultado es demasiado grande: añade LIMIT o filtra más la consulta"
            ) from None
        except (ValueError, _EndOfStreamError) as exc:
            raise SparqlBackendError("Respuesta de Fuseki no válida") from exc

    def _read_triples(
        self, response: httpx.Response, kind: QueryKind, max_rows: int, deadline: float
    ) -> QueryResult:
        lines: list[str] = []
        truncated = False
        for line in response.iter_lines():
            self._check_deadline(deadline)
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if len(lines) >= max_rows:
                truncated = True  # se deja de leer: la conexión se cierra al salir
                break
            lines.append(line)
        graph = Graph()
        try:
            graph.parse(data="\n".join(lines), format="nt")
        except Exception as exc:
            raise SparqlBackendError("Respuesta de Fuseki no válida") from exc
        return QueryResult(kind=kind, graph=graph, truncated=truncated)


class _TooLargeError(Exception):
    """Se ha procesado más de ``MAX_RESPONSE_BYTES`` (o un solo valor no cabe)."""


class _EndOfStreamError(Exception):
    """La respuesta terminó a mitad del JSON."""


class _SelectStream:
    """Lector incremental de SPARQL 1.1 Query Results JSON.

    Recorre el objeto de primer nivel clave a clave y ``results.bindings`` fila a fila con
    ``json.JSONDecoder.raw_decode``: nunca tiene en memoria más que la fila en curso y las
    ya leídas. Deja de leer (y la conexión se cierra al salir) en cuanto tiene una fila más
    que ``max_rows``, o al haber procesado ``max_bytes`` caracteres, y entonces marca el
    resultado como truncado.
    """

    _WHITESPACE = " \t\r\n"

    def __init__(
        self, chunks: Iterator[bytes], on_chunk: Callable[[], None], max_bytes: int
    ) -> None:
        self._chunks = chunks
        self._on_chunk = on_chunk
        self._decoder = codecs.getincrementaldecoder("utf-8")()
        self._json = json.JSONDecoder()
        self._max_bytes = max_bytes
        self._buffer = ""
        self._pos = 0
        self._consumed = 0
        self._eof = False

    # --- Lectura ------------------------------------------------------------------------

    def _fill(self) -> bool:
        if self._eof:
            return False
        # Se descarta lo ya procesado para no acumular la respuesta entera.
        self._consumed += self._pos
        self._buffer = self._buffer[self._pos :]
        self._pos = 0
        try:
            chunk = next(self._chunks)
        except StopIteration:
            self._buffer += self._decoder.decode(b"", final=True)
            self._eof = True
            return False
        self._on_chunk()
        self._buffer += self._decoder.decode(chunk)
        return True

    def _check_size(self) -> None:
        if self._consumed + self._pos > self._max_bytes:
            raise _TooLargeError()

    def _peek(self) -> str:
        while True:
            while self._pos < len(self._buffer) and self._buffer[self._pos] in self._WHITESPACE:
                self._pos += 1
            if self._pos < len(self._buffer):
                return self._buffer[self._pos]
            if not self._fill():
                raise _EndOfStreamError()

    def _expect(self, *chars: str) -> str:
        char = self._peek()
        if char not in chars:
            raise ValueError(f"Se esperaba {' o '.join(chars)}")
        self._pos += 1
        return char

    def _value(self) -> Any:
        self._peek()
        while True:
            try:
                value, end = self._json.raw_decode(self._buffer, self._pos)
            except json.JSONDecodeError:
                if len(self._buffer) - self._pos > self._max_bytes:
                    raise _TooLargeError() from None
                if not self._fill():
                    raise
                continue
            # Un número o un literal al final del búfer puede seguir en el trozo siguiente.
            if end == len(self._buffer) and not self._eof and self._fill():
                continue
            self._pos = end
            self._check_size()
            return value

    # --- Estructura ---------------------------------------------------------------------

    def read(self, kind: QueryKind, max_rows: int) -> QueryResult:
        head: Any = None
        boolean: Any = None
        bindings: list[Any] = []
        truncated = False
        self._expect("{")
        if self._peek() == "}":
            self._pos += 1
        else:
            while True:
                key = self._value()
                self._expect(":")
                if key == "results" and kind != "ASK":
                    truncated = self._read_results(bindings, max_rows)
                    if truncated:
                        break
                else:
                    value = self._value()
                    if key == "head":
                        head = value
                    elif key == "boolean":
                        boolean = value
                if self._expect(",", "}") == "}":
                    break
        if kind == "ASK":
            return QueryResult(kind=kind, boolean=bool(boolean))
        variables = [str(v) for v in (head or {}).get("vars", [])] if isinstance(head, dict) else []
        if not variables:  # p. ej. «results» antes que «head» y se dejó de leer
            for row in bindings:
                variables.extend(var for var in row if var not in variables)
        return QueryResult(
            kind=kind, variables=variables, bindings=bindings[:max_rows], truncated=truncated
        )

    def _read_results(self, bindings: list[Any], max_rows: int) -> bool:
        """Lee ``results``. Devuelve ``True`` si se ha dejado de leer (resultado truncado)."""
        self._expect("{")
        if self._peek() == "}":
            self._pos += 1
            return False
        while True:
            key = self._value()
            self._expect(":")
            if key == "bindings":
                if self._read_bindings(bindings, max_rows):
                    return True
            else:
                self._value()
            if self._expect(",", "}") == "}":
                return False

    def _read_bindings(self, bindings: list[Any], max_rows: int) -> bool:
        self._expect("[")
        if self._peek() == "]":
            self._pos += 1
            return False
        while True:
            try:
                row = self._value()
            except _TooLargeError:
                if not bindings:
                    raise
                return True
            if not isinstance(row, dict):
                raise ValueError("Fila no válida")
            if len(bindings) >= max_rows:
                return True
            bindings.append(row)
            if self._expect(",", "]") == "]":
                return False


class MemoryQueryRunner:
    """Doble de pruebas: ejecuta la consulta con rdflib sobre un ``Dataset`` en memoria,
    con el grafo por defecto como unión de los grafos (como Fuseki con
    ``unionDefaultGraph``)."""

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset
        self.queries: list[str] = []

    def run(self, query: ValidatedQuery, *, max_rows: int, timeout: float) -> QueryResult:
        self.queries.append(query.text)
        previous = self.dataset.default_union
        self.dataset.default_union = True
        try:
            # rdflib evalúa al iterar: todo se materializa antes de restaurar el grafo
            # por defecto.
            result = self.dataset.query(query.text)
            if query.kind == "ASK":
                return QueryResult(kind="ASK", boolean=bool(result.askAnswer))
            if query.kind == "SELECT":
                variables = [str(v) for v in (result.vars or [])]
                rows = [
                    {
                        var: _term_json(value)
                        for var, value in zip(variables, row, strict=False)
                        if value is not None
                    }
                    for row in result
                ]
                return QueryResult(
                    kind="SELECT",
                    variables=variables,
                    bindings=rows[:max_rows],
                    truncated=len(rows) > max_rows,
                )
            triples = list(result.graph or [])
        finally:
            self.dataset.default_union = previous
        graph = Graph()
        for triple in triples[:max_rows]:
            graph.add(triple)
        return QueryResult(kind=query.kind, graph=graph, truncated=len(triples) > max_rows)
