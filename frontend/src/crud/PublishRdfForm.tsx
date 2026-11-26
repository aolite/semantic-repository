import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { publishOntology, publishScheme, type CatalogRef, type CatalogSummary } from '../api'
import { describeError, ONTOLOGY_INGEST_TEXT, SCHEME_INGEST_TEXT, type FormErrorInfo } from './errors'
import { PUBLISH_TEXT, type PublishKind, type PublishResult } from './publish'
import { mediaTypeForFile, VALIDATION_TEXT } from './validation'

interface PublishRdfFormProps {
  kind: PublishKind
  /** Título del panel («Importar SKOS», «Nueva ontología», «Nueva versión»…). */
  heading: string
  /** Explicación bajo el título. */
  intro: ReactNode
  /** Catálogo fijo (republicar un esquema o una versión de una ontología que ya está en uno). */
  catalog?: CatalogRef | null
  /** Catálogos para elegir, si no hay uno fijo. */
  catalogs?: CatalogSummary[]
  /** `true` mientras se cargan los catálogos. */
  catalogsLoading?: boolean
  submitLabel: string
  token: string
  onPublished: (published: PublishResult) => void
  onCancel: () => void
}

/**
 * Publicar un esquema SKOS (`POST /schemes?catalog=`, también «Importar
 * SKOS») o una versión de ontología (`POST /ontologies?catalog=`) desde un
 * fichero Turtle o JSON-LD (decisión 50). El backend lo valida con SHACL (y,
 * en las ontologías, calcula métricas y consistencia) antes de escribir nada.
 * No está en el prototipo: usa los campos y botones del formulario «Nueva
 * versión» de la Ficha de dataset.
 */
export function PublishRdfForm(props: PublishRdfFormProps) {
  const { kind, heading, intro, catalog, catalogs, catalogsLoading, submitLabel, token, onPublished, onCancel } = props
  const id = useId()
  const [file, setFile] = useState<File | null>(null)
  const [chosenCatalog, setChosenCatalog] = useState('')
  const [fileError, setFileError] = useState<string | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<FormErrorInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const catalogSelect = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    fileInput.current?.focus()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setApiError(null)
    const mediaType = file ? mediaTypeForFile(file.name) : null
    const catalogSlug = catalog?.slug ?? chosenCatalog
    const nextFileError = !file || !mediaType ? VALIDATION_TEXT.file : null
    const nextCatalogError = catalogSlug ? null : PUBLISH_TEXT.catalogRequired
    setFileError(nextFileError)
    setCatalogError(nextCatalogError)
    if (nextFileError || !file || !mediaType) {
      fileInput.current?.focus()
      return
    }
    if (nextCatalogError) {
      catalogSelect.current?.focus()
      return
    }
    setSubmitting(true)
    try {
      if (kind === 'scheme') {
        onPublished({ kind, result: await publishScheme(file, mediaType, catalogSlug, token) })
      } else {
        onPublished({ kind, result: await publishOntology(file, mediaType, catalogSlug, token) })
      }
    } catch (error) {
      const info = describeError(error, {
        notFound: 'El catálogo no existe.',
        fallback: kind === 'scheme' ? 'No se ha podido publicar el esquema.' : 'No se ha podido publicar la ontología.',
        ingestText: kind === 'scheme' ? SCHEME_INGEST_TEXT : ONTOLOGY_INGEST_TEXT,
      })
      setApiError(info)
      if (info.fields.file) setFileError(info.fields.file)
      if (info.fields.catalog) setCatalogError(info.fields.catalog)
      setSubmitting(false)
    }
  }

  const fileId = `${id}-file`
  const catalogId = `${id}-catalog`
  const fileDescribedBy = [`${fileId}-hint`, fileError ? `${fileId}-error` : null].filter(Boolean).join(' ')
  const catalogDescribedBy = [`${catalogId}-hint`, catalogError ? `${catalogId}-error` : null].filter(Boolean).join(' ')
  const summary = apiError?.message ?? fileError ?? catalogError

  return (
    <section aria-labelledby={`${id}-heading`} className="panel crud-panel">
      <h2 id={`${id}-heading`} className="panel__title">
        {heading}
      </h2>
      <div className="panel__text">{intro}</div>
      <form
        className="form form--wide"
        onSubmit={handleSubmit}
        noValidate
        aria-describedby={summary ? `${id}-error` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel()
        }}
      >
        {summary && (
          <div id={`${id}-error`} role="alert" className="form__error">
            <p>{summary}</p>
            {apiError && apiError.issues.length > 0 && (
              <ul className="form__issues">
                {apiError.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="form__field">
          <label htmlFor={fileId}>Fichero RDF (Turtle o JSON-LD)</label>
          <input
            ref={fileInput}
            id={fileId}
            name="file"
            type="file"
            accept=".ttl,.jsonld,.json,text/turtle,application/ld+json"
            aria-invalid={fileError ? true : undefined}
            aria-describedby={fileDescribedBy}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p id={`${fileId}-hint`} className="form__hint">
            Extensiones .ttl, .jsonld o .json.
          </p>
          {fileError && (
            <p id={`${fileId}-error`} className="form__field-error">
              {fileError}
            </p>
          )}
        </div>

        {catalog ? (
          <p className="form__hint">
            Catálogo: <strong>{catalog.title ?? catalog.slug}</strong>
          </p>
        ) : (
          <div className="form__field">
            <label htmlFor={catalogId}>Catálogo</label>
            <select
              ref={catalogSelect}
              id={catalogId}
              name="catalog"
              value={chosenCatalog}
              aria-invalid={catalogError ? true : undefined}
              aria-describedby={catalogDescribedBy}
              onChange={(e) => setChosenCatalog(e.target.value)}
            >
              <option value="">{catalogsLoading ? 'Cargando catálogos…' : 'Elige un catálogo'}</option>
              {(catalogs ?? []).map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.title ?? c.slug}
                </option>
              ))}
            </select>
            <p id={`${catalogId}-hint`} className="form__hint">
              {!catalogsLoading && catalogs && catalogs.length === 0
                ? PUBLISH_TEXT.noCatalogs
                : kind === 'scheme'
                  ? 'Cada esquema está en un solo catálogo. Después se puede mover sin cambiar sus URIs.'
                  : 'Cada ontología está en un solo catálogo. Después se puede mover sin cambiar sus URIs.'}
            </p>
            {catalogError && (
              <p id={`${catalogId}-error`} className="form__field-error">
                {catalogError}
              </p>
            )}
          </div>
        )}

        <div className="form__actions">
          <button type="submit" className="button button--primary" aria-busy={submitting || undefined}>
            {submitting ? 'Publicando…' : submitLabel}
          </button>
          <button type="button" className="button button--secondary" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </section>
  )
}

