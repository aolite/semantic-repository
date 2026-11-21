"""Acceso al triplestore.

``TripleStore`` es la interfaz que usa el resto del backend. Tiene dos implementaciones:

- ``FusekiStore``: Apache Jena Fuseki por HTTP, con timeouts.
  - Lectura: ``CONSTRUCT`` contra ``{FUSEKI_URL}/{FUSEKI_DATASET}/query``, sin credenciales.
  - Escritura: ``PUT``/``GET`` del Graph Store Protocol en ``/data?graph=<iri>``, con
    autenticación Basic (``FUSEKI_USER`` y ``FUSEKI_PASSWORD``). Sin credenciales, toda
    escritura lanza ``TriplestoreConfigError`` con un mensaje claro.
- ``MemoryStore``: un ``rdflib.Dataset`` en memoria con la misma semántica. Lo usan las
  pruebas unitarias (y sirve para desarrollo sin Fuseki).

Las consultas no dependen de ``tdb2:unionDefaultGraph``: siempre usan ``GRAPH ?g``.
"""

from threading import Lock
from typing import Protocol

import httpx
from rdflib import Dataset, Graph, URIRef

from app.config import Settings
from app.sparql import iri

CONNECT_TIMEOUT_SECONDS = 3.0
GRAPH_NAMES_QUERY = "SELECT DISTINCT ?g WHERE { GRAPH ?g { } }"


class TriplestoreError(RuntimeError):
    """El triplestore no responde o devuelve un error."""


class TriplestoreConfigError(TriplestoreError):
    """Falta configuración para operar (p. ej. credenciales de escritura)."""


class TripleStore(Protocol):
    def construct(self, query: str) -> Graph:
        """Ejecuta un ``CONSTRUCT`` y devuelve el grafo resultante."""
        ...

    def get_graph(self, graph_uri: str) -> Graph:
        """Contenido del grafo con nombre (vacío si no existe)."""
        ...

    def put_graph(self, graph_uri: str, graph: Graph) -> None:
        """Sustituye por completo el grafo con nombre (lo crea si no existe)."""
        ...

    def delete_graph(self, graph_uri: str) -> None:
        """Borra el grafo con nombre (no falla si no existe)."""
        ...

    def graph_names(self) -> set[str]:
        """Nombres de los grafos con nombre que tienen algún triple."""
        ...

    def ensure_writable(self) -> object:
        """Falla con ``TriplestoreConfigError`` si no se puede escribir (sin credenciales)."""
        ...


def _graph_query(graph_uri: str) -> str:
    # La IRI se valida y se escapa con app.sparql.iri: nunca se concatena tal cual.
    return f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH {iri(graph_uri)} {{ ?s ?p ?o }} }}"


class FusekiStore:
    def __init__(
        self,
        base_url: str,
        dataset: str,
        *,
        credentials: tuple[str, str] | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._endpoint = f"{base_url}/{dataset}"
        self._credentials = credentials
        self._timeout = httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS)
        self._transport = transport

    @classmethod
    def from_settings(
        cls, settings: Settings, transport: httpx.BaseTransport | None = None
    ) -> FusekiStore:
        return cls(
            settings.fuseki_url,
            settings.fuseki_dataset,
            credentials=settings.fuseki_write_credentials,
            timeout_seconds=settings.fuseki_timeout_seconds,
            transport=transport,
        )

    def ensure_writable(self) -> tuple[str, str]:
        if self._credentials is None:
            raise TriplestoreConfigError(
                "No se puede escribir en Fuseki: faltan las variables de entorno "
                "FUSEKI_USER y FUSEKI_PASSWORD"
            )
        return self._credentials

    def _client(self, *, write: bool = False) -> httpx.Client:
        auth = httpx.BasicAuth(*self.ensure_writable()) if write else None
        return httpx.Client(timeout=self._timeout, transport=self._transport, auth=auth)

    @staticmethod
    def _check(response: httpx.Response, action: str) -> None:
        if response.status_code in (401, 403):
            raise TriplestoreConfigError(
                f"Fuseki rechazó {action} ({response.status_code}): revisa FUSEKI_USER y "
                "FUSEKI_PASSWORD"
            )
        if response.status_code >= 400:
            raise TriplestoreError(f"Fuseki respondió {response.status_code} a {action}")

    def construct(self, query: str) -> Graph:
        try:
            with self._client() as client:
                response = client.post(
                    f"{self._endpoint}/query",
                    data={"query": query},
                    headers={"Accept": "application/n-triples"},
                )
        except httpx.HTTPError as exc:
            raise TriplestoreError(f"Fuseki no responde ({type(exc).__name__})") from exc
        self._check(response, "la consulta")
        graph = Graph()
        graph.parse(data=response.text, format="nt")
        return graph

    def get_graph(self, graph_uri: str) -> Graph:
        return self.construct(_graph_query(graph_uri))

    def put_graph(self, graph_uri: str, graph: Graph) -> None:
        iri(graph_uri)  # valida la IRI antes de usarla
        body = graph.serialize(format="nt", encoding="utf-8")
        try:
            with self._client(write=True) as client:
                response = client.put(
                    f"{self._endpoint}/data",
                    params={"graph": graph_uri},
                    content=body,
                    headers={"Content-Type": "application/n-triples; charset=utf-8"},
                )
        except httpx.HTTPError as exc:
            raise TriplestoreError(f"Fuseki no responde ({type(exc).__name__})") from exc
        self._check(response, "la escritura")

    def delete_graph(self, graph_uri: str) -> None:
        iri(graph_uri)
        try:
            with self._client(write=True) as client:
                response = client.delete(f"{self._endpoint}/data", params={"graph": graph_uri})
        except httpx.HTTPError as exc:
            raise TriplestoreError(f"Fuseki no responde ({type(exc).__name__})") from exc
        if response.status_code == 404:  # el grafo no existía
            return
        self._check(response, "el borrado")

    def graph_names(self) -> set[str]:
        try:
            with self._client() as client:
                response = client.post(
                    f"{self._endpoint}/query",
                    data={"query": GRAPH_NAMES_QUERY},
                    headers={"Accept": "application/sparql-results+json"},
                )
        except httpx.HTTPError as exc:
            raise TriplestoreError(f"Fuseki no responde ({type(exc).__name__})") from exc
        self._check(response, "la consulta")
        try:
            rows = response.json()["results"]["bindings"]
            return {row["g"]["value"] for row in rows if row.get("g", {}).get("type") == "uri"}
        except (ValueError, KeyError, TypeError) as exc:
            raise TriplestoreError("Respuesta de Fuseki no válida") from exc


class MemoryStore:
    """Doble en memoria de Fuseki (rdflib). Mismo contrato que ``FusekiStore``."""

    def __init__(self) -> None:
        self.dataset = Dataset()
        self.queries: list[str] = []
        self._lock = Lock()

    def construct(self, query: str) -> Graph:
        with self._lock:
            self.queries.append(query)
            result = self.dataset.query(query)
            graph = Graph()
            if result.graph is not None:
                for triple in result.graph:
                    graph.add(triple)
            return graph

    def get_graph(self, graph_uri: str) -> Graph:
        return self.construct(_graph_query(graph_uri))

    def ensure_writable(self) -> None:
        return None

    def put_graph(self, graph_uri: str, graph: Graph) -> None:
        iri(graph_uri)
        with self._lock:
            self.dataset.remove_graph(URIRef(graph_uri))
            target = self.dataset.graph(URIRef(graph_uri))
            for triple in graph:
                target.add(triple)

    def delete_graph(self, graph_uri: str) -> None:
        iri(graph_uri)
        with self._lock:
            self.dataset.remove_graph(URIRef(graph_uri))

    def graph_names(self) -> set[str]:
        with self._lock:
            return {
                str(g.identifier)
                for g in self.dataset.graphs()
                if len(g)
                and isinstance(g.identifier, URIRef)
                and str(g.identifier) != "urn:x-rdflib:default"
            }
