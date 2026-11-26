import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { CatalogSummary } from '../api'
import { describeError, type ErrorContext, type FormErrorInfo } from './errors'

interface CatalogMoveFormProps {
  heading: string
  intro: ReactNode
  /** Slug del catálogo actual (preseleccionado). */
  current: string
  catalogs: CatalogSummary[] | undefined
  catalogsLoading?: boolean
  errorContext: ErrorContext
  /** Solo se llama si el destino es otro catálogo. */
  onSubmit: (catalog: string) => Promise<void>
  onCancel: () => void
}

/**
 * Mover un recurso de catálogo (decisión 50: `PATCH /ontologies/{slug}` con
 * `catalog`). Sus URIs y versiones no cambian. No está en el prototipo: usa
 * los campos y botones de los demás formularios.
 */
export function CatalogMoveForm(props: CatalogMoveFormProps) {
  const { heading, intro, current, catalogs, catalogsLoading, errorContext, onSubmit, onCancel } = props
  const id = useId()
  const [value, setValue] = useState(current)
  const [error, setError] = useState<FormErrorInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const select = useRef<HTMLSelectElement>(null)

  useEffect(() => {
    select.current?.focus()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setError(null)
    if (!value || value === current) {
      setError({ message: 'Elige un catálogo distinto del actual.', fields: { catalog: 'Elige otro catálogo.' }, issues: [] })
      select.current?.focus()
      return
    }
    setSubmitting(true)
    try {
      await onSubmit(value)
    } catch (err) {
      setError(describeError(err, errorContext))
      setSubmitting(false)
    }
  }

  const selectId = `${id}-catalog`
  const fieldError = error?.fields.catalog
  const describedBy = [`${selectId}-hint`, fieldError ? `${selectId}-error` : null].filter(Boolean).join(' ')

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
        aria-describedby={error ? `${id}-error` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Escape') onCancel()
        }}
      >
        {error && (
          <div id={`${id}-error`} role="alert" className="form__error">
            <p>{error.message}</p>
            {error.issues.length > 0 && (
              <ul className="form__issues">
                {error.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="form__field">
          <label htmlFor={selectId}>Catálogo de destino</label>
          <select
            ref={select}
            id={selectId}
            name="catalog"
            value={value}
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={describedBy}
            onChange={(e) => setValue(e.target.value)}
          >
            {!current && <option value="">Elige un catálogo</option>}
            {catalogsLoading && !catalogs && <option value={current}>Cargando catálogos…</option>}
            {(catalogs ?? []).map((c) => (
              <option key={c.slug} value={c.slug}>
                {c.title ?? c.slug}
                {c.slug === current ? ' (actual)' : ''}
              </option>
            ))}
          </select>
          <p id={`${selectId}-hint`} className="form__hint">
            Moverlo no cambia sus URIs ni sus versiones publicadas.
          </p>
          {fieldError && (
            <p id={`${selectId}-error`} className="form__field-error">
              {fieldError}
            </p>
          )}
        </div>
        <div className="form__actions">
          <button type="submit" className="button button--primary" aria-busy={submitting || undefined}>
            {submitting ? 'Moviendo…' : 'Mover'}
          </button>
          <button type="button" className="button button--secondary" onClick={onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </section>
  )
}
