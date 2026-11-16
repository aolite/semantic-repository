// Formato `application/sparql-results+json` del W3C. No es un esquema del OpenAPI del
// backend, así que no vive en `api/types.ts` (que las pruebas de contrato comparan con él).

/** Término RDF de un resultado SPARQL (formato `application/sparql-results+json` del W3C). */
export interface SparqlTerm {
  type: 'uri' | 'literal' | 'typed-literal' | 'bnode' | 'triple'
  value: string
  'xml:lang'?: string
  datatype?: string
}

/** Respuesta `application/sparql-results+json` de `/sparql` (SELECT o ASK). */
export interface SparqlJsonResults {
  head: { vars?: string[]; link?: string[] }
  results?: { bindings: Record<string, SparqlTerm>[] }
  boolean?: boolean
}
