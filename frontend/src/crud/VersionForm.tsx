import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { publishDatasetRdf, type CatalogRef, type CatalogSummary, type IngestResult } from '../api'
import { describeError, type FormErrorInfo } from './errors'
import { mediaTypeForFile, VALIDATION_TEXT } from './validation'

interface VersionFormProps {
  /** Catálogo de la serie: se manda como `?catalog=`. */
  catalog: CatalogRef | null
  /** Si la serie no tiene catálogo, se puede elegir uno. */
  catalogs?: CatalogSummary[]
  token: string
  onPublished: (result: IngestResult) => void
  onCancel: () => void
}

/**
 * «Nueva versión» de la Ficha de dataset. Una versión DCAT-AP (distribuciones,
 * procedencia PROV, temas) no cabe en un formulario plano, así que se sube el
 * RDF de la serie (Turtle o JSON-LD) a `POST /datasets?catalog=`, que lo
 * valida con SHACL y comprueba que las versiones publicadas no cambian.
 */
export function VersionForm({ catalog, catalogs, token, onPublished, onCancel }: VersionFormProps) {
  const id = useId()
  const [file, setFile] = useState<File | null>(null)
  const [chosenCatalog, setChosenCatalog] = useState('')
  const [fileError, setFileError] = useState<string | null>(null)
  const [apiError, setApiError] = useState<FormErrorInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    fileInput.current?.focus()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setApiError(null)
    const mediaType = file ? mediaTypeForFile(file.name) : null
    if (!file || !mediaType) {
      setFileError(VALIDATION_TEXT.file)
      fileInput.current?.focus()
      return
    }
    setFileError(null)
    setSubmitting(true)
    try {
      const result = await publishDatasetRdf(file, mediaType, catalog?.slug ?? (chosenCatalog || null), token)
      onPublished(result)
    } catch (error) {
      const info = describeError(error, {
        notFound: 'El dataset no existe.',
        fallback: 'No se ha podido publicar la versión.',
      })
      setApiError(info)
      if (info.fields.file) setFileError(info.fields.file)
      setSubmitting(false)
    }
  }

  const fileId = `${id}-file`
  const describedBy = [`${fileId}-hint`, fileError ? `${fileId}-error` : null].filter(Boolean).join(' ')

  return (
    <section aria-labelledby={`${id}-heading`} className="panel crud-panel">
      <h2 id={`${id}-heading`} className="panel__title">
        Nueva versión
      </h2>
      <p className="panel__text">
        Sube el RDF de la serie completa: sus metadatos, <strong>todas las versiones ya publicadas sin cambios</strong> y la
        versión nueva, con sus distribuciones, procedencia PROV-O y temas. El repositorio lo valida con las formas SHACL
        antes de publicarlo; las versiones publicadas no se pueden modificar.
      </p>
      <form
        className="form form--wide"
        onSubmit={handleSubmit}
        noValidate
        aria-describedby={apiError || fileError ? `${id}-error` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel()
        }}
      >
        {(apiError || fileError) && (
          <div id={`${id}-error`} role="alert" className="form__error">
            <p>{apiError?.message ?? fileError}</p>
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
            aria-describedby={describedBy}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p id={`${fileId}-hint`} className="form__hint">
            Extensiones .ttl, .jsonld o .json. Los ficheros de las distribuciones se suben aparte.
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
          catalogs && (
            <div className="form__field">
              <label htmlFor={`${id}-catalog`}>Catálogo</label>
              <select
                id={`${id}-catalog`}
                name="catalog"
                value={chosenCatalog}
                onChange={(e) => setChosenCatalog(e.target.value)}
              >
                <option value="">Sin indicar (lo declara el RDF)</option>
                {catalogs.map((c) => (
                  <option key={c.slug} value={c.slug}>
                    {c.title ?? c.slug}
                  </option>
                ))}
              </select>
            </div>
          )
        )}

        <div className="form__actions">
          <button type="submit" className="button button--primary" aria-busy={submitting || undefined}>
            {submitting ? 'Publicando…' : 'Publicar versión'}
          </button>
          <button type="button" className="button button--secondary" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </section>
  )
}
