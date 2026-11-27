import { useId, useRef, useState, type FormEvent } from 'react'
import { replaceExternalOntology, type ExternalOntologyDetail, type ExternalReplaceResult } from '../api'
import { Dialog } from '../components/Dialog'
import { describeError, EXTERNAL_INGEST_TEXT, ingestError, ingestFieldIssues, type FormErrorInfo } from './errors'
import { mediaTypeForFile, VALIDATION_TEXT } from './validation'

/** Campos del formulario, con los nombres de `POST /ontologies/externas/{slug}/versions`. */
const FIELDS = ['file', 'title', 'description', 'version_info', 'prefix', 'namespace', 'publisher', 'version_notes'] as const
type Field = (typeof FIELDS)[number]
type Values = Record<Exclude<Field, 'file'>, string>
type Errors = Partial<Record<Field, string>>

/** Patrón de `prefix` en el contrato. */
const PREFIX_PATTERN = /^[a-z][a-z0-9]*$/

const EXTERNAL_REPLACE_TEXT = {
  prefix: 'Solo minúsculas sin acentos y dígitos, empezando por una letra.',
  namespace: 'Escribe una URI completa, que empiece por http:// o https://.',
} as const

function isHttpUri(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

function validate(file: File | null, values: Values): Errors {
  const errors: Errors = {}
  if (!file || !mediaTypeForFile(file.name)) errors.file = VALIDATION_TEXT.file
  if (!values.title.trim()) errors.title = VALIDATION_TEXT.required
  const prefix = values.prefix.trim()
  if (!prefix) errors.prefix = VALIDATION_TEXT.required
  else if (!PREFIX_PATTERN.test(prefix)) errors.prefix = EXTERNAL_REPLACE_TEXT.prefix
  const namespace = values.namespace.trim()
  if (!namespace) errors.namespace = VALIDATION_TEXT.required
  else if (!isHttpUri(namespace)) errors.namespace = EXTERNAL_REPLACE_TEXT.namespace
  return errors
}

interface ExternalReplaceDialogProps {
  ontology: ExternalOntologyDetail
  token: string
  onReplaced: (result: ExternalReplaceResult) => void
  onCancel: () => void
}

/**
 * «Sustituir ontología» de una ontología externa (decisión 51): sube el
 * fichero completo (Turtle o JSON-LD) con sus metadatos de referencia y el
 * backend crea la versión n+1. El prototipo no lo dibuja: usa los campos y
 * botones de los formularios existentes, dentro de un diálogo modal
 * [PROPUESTA]. Prefijo, espacio de nombres, publicador, título y descripción
 * se rellenan con los actuales.
 */
export function ExternalReplaceDialog({ ontology, token, onReplaced, onCancel }: ExternalReplaceDialogProps) {
  const id = useId()
  const [file, setFile] = useState<File | null>(null)
  const [values, setValues] = useState<Values>({
    title: ontology.title ?? '',
    description: ontology.description ?? '',
    version_info: '',
    prefix: ontology.prefix ?? '',
    namespace: ontology.namespace ?? '',
    publisher: ontology.publisher ?? '',
    version_notes: '',
  })
  const [errors, setErrors] = useState<Errors>({})
  const [apiError, setApiError] = useState<FormErrorInfo | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const form = useRef<HTMLFormElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const last = Math.max(0, ...ontology.versions.map((v) => v.number), ontology.current_version?.number ?? 0)
  const next = last + 1

  function set(field: keyof Values, value: string) {
    setValues((prev) => ({ ...prev, [field]: value }))
  }

  function focusFirst(found: Errors) {
    const first = FIELDS.find((f) => found[f])
    if (first) form.current?.querySelector<HTMLElement>(`[name="${first}"]`)?.focus()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    setApiError(null)
    const found = validate(file, values)
    setErrors(found)
    const mediaType = file ? mediaTypeForFile(file.name) : null
    if (Object.keys(found).length > 0 || !file || !mediaType) {
      focusFirst(found)
      return
    }
    setSubmitting(true)
    try {
      const { title, prefix, namespace, ...optional } = values
      onReplaced(await replaceExternalOntology(ontology.slug, file, mediaType, { title, prefix, namespace, ...optional }, token))
    } catch (error) {
      const info = describeError(error, {
        notFound: 'La ontología externa no existe.',
        fallback: 'No se ha podido sustituir la ontología.',
        ingestText: EXTERNAL_INGEST_TEXT,
      })
      const fieldErrors: Errors = { ...ingestFieldIssues(error, FIELDS) }
      if (info.fields.file) fieldErrors.file = info.fields.file
      const kind = ingestError(error)?.kind
      if (kind === 'prefix_in_use' || kind === 'prefix_withdrawn') fieldErrors.prefix = info.message
      if (kind === 'syntax') fieldErrors.file = info.message
      setApiError(info)
      setErrors(fieldErrors)
      setSubmitting(false)
      focusFirst(fieldErrors)
    }
  }

  const fieldId = (field: Field) => `${id}-${field}`
  const errorId = (field: Field) => `${id}-${field}-error`
  const hintId = (field: Field) => `${id}-${field}-hint`
  const summary = apiError?.message ?? (Object.keys(errors).length > 0 ? 'Revisa los campos marcados.' : null)

  function fieldProps(field: Field, hint = false) {
    const describedBy = [hint ? hintId(field) : null, errors[field] ? errorId(field) : null].filter(Boolean)
    return {
      id: fieldId(field),
      name: field,
      'aria-invalid': errors[field] ? true : undefined,
      'aria-describedby': describedBy.length > 0 ? describedBy.join(' ') : undefined,
    }
  }

  function fieldError(field: Field) {
    return errors[field] ? (
      <p id={errorId(field)} className="form__field-error">
        {errors[field]}
      </p>
    ) : null
  }

  function textField(field: keyof Values, label: string, options: { hint?: string; required?: boolean; mono?: boolean } = {}) {
    return (
      <div className="form__field">
        <label htmlFor={fieldId(field)}>{label}</label>
        <input
          {...fieldProps(field, !!options.hint)}
          type="text"
          required={options.required}
          autoComplete="off"
          spellCheck={options.mono ? false : undefined}
          className={options.mono ? 'mono' : undefined}
          value={values[field]}
          onChange={(e) => set(field, e.target.value)}
        />
        {options.hint && (
          <p id={hintId(field)} className="form__hint">
            {options.hint}
          </p>
        )}
        {fieldError(field)}
      </div>
    )
  }

  return (
    <Dialog
      title="Sustituir ontología"
      onClose={onCancel}
      busy={submitting}
      initialFocus={fileInput}
      describedBy={`${id}-help`}
      className="dialog--form"
    >
      <div className="dialog__body">
        <p id={`${id}-help`}>
          Se sustituye la ontología <strong>entera</strong> por el fichero que subas y se genera la{' '}
          <strong>versión {next}</strong>. Las versiones anteriores no cambian.
        </p>
        <p className="form__hint">
          El repositorio comprueba que el fichero declara la ontología con su IRI oficial (
          <span className="mono">{ontology.uri}</span>) y calcula sus métricas y su consistencia.
        </p>
      </div>
      <form
        ref={form}
        className="form form--wide"
        onSubmit={handleSubmit}
        noValidate
        aria-describedby={summary ? `${id}-error` : undefined}
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
          <label htmlFor={fieldId('file')}>Fichero de la ontología (Turtle o JSON-LD)</label>
          <input
            ref={fileInput}
            {...fieldProps('file', true)}
            type="file"
            required
            accept=".ttl,.jsonld,.json,text/turtle,application/ld+json"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <p id={hintId('file')} className="form__hint">
            El fichero completo, tal como lo publica su organismo. Extensiones .ttl, .jsonld o .json.
          </p>
          {fieldError('file')}
        </div>

        {textField('title', 'Título (en español)', { required: true })}

        <div className="form__field">
          <label htmlFor={fieldId('description')}>Descripción (en español, opcional)</label>
          <textarea
            {...fieldProps('description')}
            rows={3}
            value={values.description}
            onChange={(e) => set('description', e.target.value)}
          />
          {fieldError('description')}
        </div>

        {textField('version_info', 'Versión del publicador (opcional)', {
          hint: 'La versión que le da su organismo (owl:versionInfo).',
        })}
        {textField('prefix', 'Prefijo', {
          required: true,
          mono: true,
          hint: 'vann:preferredNamespacePrefix: minúsculas sin acentos y dígitos, empezando por una letra.',
        })}
        {textField('namespace', 'Espacio de nombres', {
          required: true,
          mono: true,
          hint: 'vann:preferredNamespaceUri: sus entidades cuentan como propias en las métricas.',
        })}
        {textField('publisher', 'Publicador (opcional)')}

        <div className="form__field">
          <label htmlFor={fieldId('version_notes')}>Notas de la versión (en español, opcional)</label>
          <textarea
            {...fieldProps('version_notes', true)}
            rows={3}
            value={values.version_notes}
            onChange={(e) => set('version_notes', e.target.value)}
          />
          <p id={hintId('version_notes')} className="form__hint">
            Qué cambia respecto a la versión anterior.
          </p>
          {fieldError('version_notes')}
        </div>

        <div className="form__actions">
          <button type="submit" className="button button--primary" aria-busy={submitting || undefined}>
            {submitting ? 'Sustituyendo…' : 'Sustituir ontología'}
          </button>
          <button
            type="button"
            className="button button--secondary"
            onClick={() => !submitting && onCancel()}
            aria-disabled={submitting || undefined}
          >
            Cancelar
          </button>
        </div>
      </form>
    </Dialog>
  )
}
