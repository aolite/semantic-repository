import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import type { CatalogRef, CatalogSummary } from '../api'
import { describeError, type ErrorContext, type FormErrorInfo, type FormField } from './errors'
import { LIMITS, validateResource, VALIDATION_TEXT, type FieldErrors, type ResourceValues } from './validation'

export interface ResourceFormValues extends ResourceValues {
  /** Slug del catálogo (solo al editar un dataset). */
  catalog: string
}

interface ResourceFormProps {
  /** Título del panel (p. ej. «Nuevo catálogo»). */
  heading: string
  mode: 'create' | 'edit'
  initial: ResourceFormValues
  /** En los catálogos el publicador es obligatorio; en la serie, opcional. */
  requirePublisher: boolean
  /** Ayuda bajo el publicador (p. ej. al editar una serie, que la API no devuelve). */
  publisherHint?: string
  /** Prefijo de la URI que se forma con el slug (`{BASE_URI}catalogo/`); vacío si no hay base. */
  uriPrefix?: string
  /** Catálogo fijo en el que se crea (ficha de un catálogo): se muestra, sin selector. */
  catalog?: CatalogRef
  /** Con la lista, se muestra el selector «Catálogo» (mover un dataset o un esquema, o elegir dónde crearlo). */
  catalogs?: CatalogSummary[]
  /** La descripción es obligatoria (por defecto, sí). */
  requireDescription?: boolean
  /** El catálogo es obligatorio (crear un dataset eligiendo su catálogo). */
  requireCatalog?: boolean
  /** Ayuda bajo el selector de catálogo. */
  catalogHint?: string
  /** Explicación bajo el título del panel. */
  intro?: ReactNode
  submitLabel: string
  errorContext: ErrorContext
  onSubmit: (values: ResourceFormValues) => Promise<void>
  onCancel: () => void
}

/**
 * Formulario de alta y edición de catálogos y datasets (decisión 49). No está
 * en el prototipo: usa los campos, botones y colores de las pantallas que ya
 * existen. Título y descripción se guardan en español (`@es`).
 */
export function ResourceForm(props: ResourceFormProps) {
  const { heading, mode, initial, requirePublisher, publisherHint, uriPrefix, catalogs, submitLabel, errorContext } =
    props
  const { requireCatalog = false, requireDescription = true, intro } = props
  const catalogHint = props.catalogHint ?? 'Cada dataset está en un solo catálogo. Moverlo no cambia sus URIs.'
  const id = useId()
  const [values, setValues] = useState<ResourceFormValues>(initial)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [apiError, setApiError] = useState<FormErrorInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const form = useRef<HTMLFormElement>(null)

  useEffect(() => {
    form.current?.querySelector<HTMLElement>('input, textarea, select')?.focus()
  }, [])

  function set(field: keyof ResourceFormValues, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }))
  }

  function focusField(field: FormField) {
    form.current?.querySelector<HTMLElement>(`[name="${field}"]`)?.focus()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    const errors = validateResource(values, { requireSlug: mode === 'create', requirePublisher, requireDescription })
    if (requireCatalog && !values.catalog) errors.catalog = VALIDATION_TEXT.required
    setFieldErrors(errors)
    setApiError(null)
    const first = (Object.keys(errors) as FormField[])[0]
    if (first) {
      focusField(first)
      return
    }
    setSubmitting(true)
    try {
      await props.onSubmit(values)
    } catch (error) {
      const info = describeError(error, errorContext)
      setApiError(info)
      setFieldErrors(info.fields)
      setSubmitting(false)
    }
  }

  const fieldId = (field: string) => `${id}-${field}`
  const errorId = (field: string) => `${id}-${field}-error`
  const hasErrors = Object.keys(fieldErrors).length > 0 || apiError !== null

  function fieldProps(field: FormField, hint?: boolean) {
    const message = fieldErrors[field]
    const describedBy = [hint ? `${fieldId(field)}-hint` : null, message ? errorId(field) : null].filter(Boolean)
    return {
      id: fieldId(field),
      name: field,
      'aria-invalid': message ? true : undefined,
      'aria-describedby': describedBy.length > 0 ? describedBy.join(' ') : undefined,
    }
  }

  function fieldError(field: FormField) {
    const message = fieldErrors[field]
    return message ? (
      <p id={errorId(field)} className="form__field-error">
        {message}
      </p>
    ) : null
  }

  return (
    <section aria-labelledby={`${id}-heading`} className="panel crud-panel">
      <h2 id={`${id}-heading`} className="panel__title">
        {heading}
      </h2>
      {intro && <div className="panel__text">{intro}</div>}
      <form
        ref={form}
        className="form form--wide"
        onSubmit={handleSubmit}
        noValidate
        aria-describedby={hasErrors ? `${id}-error` : undefined}
        onKeyDown={(e) => {
          if (e.key === 'Escape') props.onCancel()
        }}
      >
        {(apiError || Object.keys(fieldErrors).length > 0) && (
          <div id={`${id}-error`} role="alert" className="form__error">
            <p>{apiError?.message ?? 'Revisa los campos marcados.'}</p>
            {apiError && apiError.issues.length > 0 && (
              <ul className="form__issues">
                {apiError.issues.map((issue, i) => (
                  <li key={i}>{issue}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {mode === 'create' && (
          <div className="form__field">
            <label htmlFor={fieldId('slug')}>Slug</label>
            <input
              {...fieldProps('slug', true)}
              type="text"
              required
              autoComplete="off"
              spellCheck={false}
              maxLength={LIMITS.slug}
              className="mono"
              value={values.slug}
              onChange={(e) => set('slug', e.target.value)}
            />
            <p id={`${fieldId('slug')}-hint`} className="form__hint">
              Minúsculas sin acentos, dígitos y guiones. Forma parte de la URI y no se puede cambiar
              {uriPrefix ? (
                <>
                  : <span className="mono">{`${uriPrefix}${values.slug.trim() || '…'}`}</span>
                </>
              ) : (
                '.'
              )}
            </p>
            {fieldError('slug')}
          </div>
        )}

        <div className="form__field">
          <label htmlFor={fieldId('title')}>Título (en español)</label>
          <input
            {...fieldProps('title')}
            type="text"
            required
            maxLength={LIMITS.title}
            value={values.title}
            onChange={(e) => set('title', e.target.value)}
          />
          {fieldError('title')}
        </div>

        <div className="form__field">
          <label htmlFor={fieldId('description')}>
            {requireDescription ? 'Descripción (en español)' : 'Descripción (en español, opcional)'}
          </label>
          <textarea
            {...fieldProps('description')}
            required={requireDescription}
            rows={4}
            maxLength={LIMITS.description}
            value={values.description}
            onChange={(e) => set('description', e.target.value)}
          />
          {fieldError('description')}
        </div>

        <div className="form__field">
          <label htmlFor={fieldId('publisher_name')}>{requirePublisher ? 'Publicador' : 'Publicador (opcional)'}</label>
          <input
            {...fieldProps('publisher_name', !!publisherHint)}
            type="text"
            required={requirePublisher}
            maxLength={LIMITS.publisher_name}
            value={values.publisher_name}
            onChange={(e) => set('publisher_name', e.target.value)}
          />
          {publisherHint && (
            <p id={`${fieldId('publisher_name')}-hint`} className="form__hint">
              {publisherHint}
            </p>
          )}
          {fieldError('publisher_name')}
        </div>

        {props.catalog && (
          <p className="form__hint">
            Catálogo: <strong>{props.catalog.title ?? props.catalog.slug}</strong>
          </p>
        )}

        {catalogs && !props.catalog && (
          <div className="form__field">
            <label htmlFor={fieldId('catalog')}>Catálogo</label>
            <select {...fieldProps('catalog', true)} value={values.catalog} onChange={(e) => set('catalog', e.target.value)}>
              {!values.catalog && <option value="">{requireCatalog ? 'Elige un catálogo' : 'Sin catálogo'}</option>}
              {catalogs.map((c) => (
                <option key={c.slug} value={c.slug}>
                  {c.title ?? c.slug}
                </option>
              ))}
            </select>
            <p id={`${fieldId('catalog')}-hint`} className="form__hint">
              {catalogHint}
            </p>
            {fieldError('catalog')}
          </div>
        )}

        <div className="form__actions">
          <button type="submit" className="button button--primary" aria-busy={submitting || undefined}>
            {submitting ? 'Guardando…' : submitLabel}
          </button>
          <button type="button" className="button button--secondary" onClick={props.onCancel}>
            Cancelar
          </button>
        </div>
      </form>
    </section>
  )
}
