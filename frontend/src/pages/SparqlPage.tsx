import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  createSavedQuery,
  isAbortError,
  listSavedQueries,
  runSparql,
  type SavedQuery,
  type SparqlRunResult,
} from '../api'
import { useAuth } from '../auth/useAuth'
import { getSparqlEndpointUrl } from '../config'
import { useApiLoad } from '../hooks/useApiLoad'
import {
  RESULT_FORMATS,
  resultCountLabel,
  resultRows,
  resultVars,
  saveErrorMessage,
  sortSavedQueries,
  SPARQL_TEXT,
  sparqlErrorMessage,
  termText,
  toCsv,
  type ResultFormat,
} from '../sparql/results'
import '../styles/sparql.css'

type RunState =
  | { status: 'idle' }
  | { status: 'running' }
  | { status: 'ok'; result: SparqlRunResult }
  | { status: 'error'; message: string }

/**
 * Consola SPARQL (prototipo, pantalla Consulta SPARQL): consultas guardadas
 * (las de referencia y, con sesión, las personales), editor, «Guardar» (solo
 * con sesión), «Ejecutar» contra `/sparql` y resultados en Tabla, JSON o CSV.
 */
export function SparqlPage() {
  const { token } = useAuth()

  const loader = useCallback((signal: AbortSignal) => listSavedQueries(token, signal), [token])
  const { state: savedState, lastData, retry: reloadSaved } = useApiLoad(loader)
  const queries = sortSavedQueries(savedState.status === 'ok' ? savedState.data : (lastData ?? []))

  // Sin selección explícita, la primera consulta (como el prototipo).
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [draft, setDraft] = useState('')
  const selected = queries.find((q) => q.id === selectedId) ?? queries[0] ?? null
  const text = selected ? (edits[selected.id] ?? selected.query) : draft

  const [run, setRun] = useState<RunState>({ status: 'idle' })
  const [format, setFormat] = useState<ResultFormat>('table')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])

  function handleEdit(value: string) {
    if (selected) setEdits((prev) => ({ ...prev, [selected.id]: value }))
    else setDraft(value)
  }

  function pick(query: SavedQuery) {
    if (query.id === selected?.id) return
    controller.current?.abort()
    setSelectedId(query.id)
    setRun({ status: 'idle' })
  }

  async function execute() {
    if (!text.trim()) {
      setRun({ status: 'error', message: SPARQL_TEXT.emptyQuery })
      return
    }
    controller.current?.abort()
    const current = new AbortController()
    controller.current = current
    setRun({ status: 'running' })
    try {
      const result = await runSparql(text, token, current.signal)
      setRun({ status: 'ok', result })
    } catch (error) {
      if (isAbortError(error) || current.signal.aborted) return
      setRun({ status: 'error', message: sparqlErrorMessage(error) })
    }
  }

  function handleEditorKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Ctrl+Intro (Cmd+Intro en macOS) ejecuta, como en otras consolas SPARQL.
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      void execute()
    }
  }

  function handleSaved(query: SavedQuery) {
    setSelectedId(query.id)
    reloadSaved()
  }

  return (
    <div className="sparql">
      <header className="sparql__header">
        <h1 className="page-title sparql__title">Consulta SPARQL</h1>
        <span className="mono sparql__endpoint">Endpoint · {getSparqlEndpointUrl()}</span>
      </header>

      <div className="sparql__columns">
        <section aria-label="Consultas guardadas" className="sparql__saved">
          <span className="sparql__saved-label">Consultas guardadas</span>
          {savedState.status === 'loading' && queries.length === 0 && (
            <p role="status" className="sparql__saved-state">
              {SPARQL_TEXT.queriesLoading}
            </p>
          )}
          {(savedState.status === 'error' || savedState.status === 'not-found') && (
            <div role="alert" className="sparql__saved-state sparql__saved-state--error">
              <p>{SPARQL_TEXT.queriesError}</p>
              <button type="button" className="button button--secondary" onClick={reloadSaved}>
                Reintentar
              </button>
            </div>
          )}
          {savedState.status === 'ok' && queries.length === 0 && (
            <p className="sparql__saved-state">{SPARQL_TEXT.queriesEmpty}</p>
          )}
          {queries.map((query) => (
            <button
              key={query.id}
              type="button"
              className="saved-query"
              aria-pressed={query.id === selected?.id}
              onClick={() => pick(query)}
            >
              <span className="saved-query__title">{query.title}</span>
              {query.hint && <span className="saved-query__hint">{query.hint}</span>}
            </button>
          ))}
        </section>

        <div className="sparql__work">
          <Editor
            text={text}
            onEdit={handleEdit}
            onKeyDown={handleEditorKeyDown}
            onRun={() => void execute()}
            running={run.status === 'running'}
            token={token}
            onSaved={handleSaved}
          />
          <Results run={run} format={format} onFormat={setFormat} />
        </div>
      </div>
    </div>
  )
}

interface EditorProps {
  text: string
  onEdit: (value: string) => void
  onKeyDown: (event: KeyboardEvent<HTMLTextAreaElement>) => void
  onRun: () => void
  running: boolean
  token: string | null
  onSaved: (query: SavedQuery) => void
}

function Editor({ text, onEdit, onKeyDown, onRun, running, token, onSaved }: EditorProps) {
  const [saving, setSaving] = useState(false)
  const [savedMessage, setSavedMessage] = useState<string | null>(null)
  const saveButton = useRef<HTMLButtonElement>(null)

  function closeForm() {
    setSaving(false)
    saveButton.current?.focus()
  }

  return (
    <section aria-label="Editor" className="sparql__editor">
      <div className="sparql__toolbar">
        <label htmlFor="consulta" className="sparql__editor-label">
          Consulta
        </label>
        <div className="sparql__actions">
          {/* Sin sesión no se muestra «Guardar»: guardar exige ser miembro. */}
          {token && (
            <button
              ref={saveButton}
              type="button"
              className="sparql__button"
              aria-expanded={saving}
              aria-controls={saving ? 'guardar-consulta' : undefined}
              onClick={() => {
                setSavedMessage(null)
                setSaving((open) => !open)
              }}
            >
              Guardar
            </button>
          )}
          <button
            type="button"
            className="sparql__button sparql__button--run"
            onClick={onRun}
            aria-busy={running || undefined}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
              <path d="M7 4l13 8-13 8z" />
            </svg>
            Ejecutar
          </button>
        </div>
      </div>

      {token && saving && (
        <SaveForm
          query={text}
          token={token}
          onCancel={closeForm}
          onSaved={(query) => {
            setSavedMessage('Consulta guardada.')
            closeForm()
            onSaved(query)
          }}
        />
      )}
      {savedMessage && (
        <p role="status" className="sparql__saved-message">
          {savedMessage}
        </p>
      )}

      <textarea
        id="consulta"
        className="sparql__textarea"
        spellCheck={false}
        value={text}
        onChange={(e) => onEdit(e.target.value)}
        onKeyDown={onKeyDown}
      />
    </section>
  )
}

interface SaveFormProps {
  query: string
  token: string
  onCancel: () => void
  onSaved: (query: SavedQuery) => void
}

/**
 * Formulario para guardar la consulta del editor como personal. El prototipo
 * solo tiene el botón «Guardar»: los campos y sus textos son del frontend.
 */
function SaveForm({ query, token, onCancel, onSaved }: SaveFormProps) {
  const [title, setTitle] = useState('')
  const [hint, setHint] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const titleInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    titleInput.current?.focus()
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitting) return
    if (!title.trim()) {
      setError('Escribe un título.')
      titleInput.current?.focus()
      return
    }
    if (!query.trim()) {
      setError('Escribe una consulta antes de guardarla.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await createSavedQuery({ title: title.trim(), hint: hint.trim() || null, query }, token)
      onSaved(created)
    } catch (err) {
      setError(saveErrorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <form
      id="guardar-consulta"
      className="save-form"
      aria-label="Guardar consulta"
      onSubmit={handleSubmit}
      noValidate
      onKeyDown={(e) => {
        if (e.key === 'Escape') onCancel()
      }}
    >
      {error && (
        <p id="guardar-error" role="alert" className="save-form__error">
          {error}
        </p>
      )}
      <div className="save-form__field">
        <label htmlFor="guardar-titulo">Título</label>
        <input
          ref={titleInput}
          id="guardar-titulo"
          type="text"
          required
          maxLength={120}
          value={title}
          aria-invalid={error && !title.trim() ? true : undefined}
          aria-describedby={error ? 'guardar-error' : undefined}
          onChange={(e) => setTitle(e.target.value)}
        />
      </div>
      <div className="save-form__field">
        <label htmlFor="guardar-pista">Pista (opcional)</label>
        <input id="guardar-pista" type="text" maxLength={200} value={hint} onChange={(e) => setHint(e.target.value)} />
      </div>
      <div className="save-form__actions">
        <button type="submit" className="sparql__button sparql__button--run" aria-busy={submitting || undefined}>
          Guardar consulta
        </button>
        <button type="button" className="sparql__button" onClick={onCancel}>
          Cancelar
        </button>
      </div>
    </form>
  )
}

interface ResultsProps {
  run: RunState
  format: ResultFormat
  onFormat: (format: ResultFormat) => void
}

function Results({ run, format, onFormat }: ResultsProps) {
  const result = run.status === 'ok' ? run.result : null
  const tabular = result?.kind === 'results' && typeof result.data.boolean !== 'boolean'
  const rows = tabular && result?.kind === 'results' ? resultRows(result.data) : []

  return (
    <section aria-labelledby="h-res" className="sparql__results" aria-busy={run.status === 'running' || undefined}>
      <div className="sparql__results-head">
        <div className="sparql__results-title">
          <h2 id="h-res" className="panel__title">
            Resultados
          </h2>
          <span className="sparql__count" aria-live="polite">
            {tabular ? resultCountLabel(rows.length) : ''}
          </span>
        </div>
        {result?.kind !== 'graph' && (
          <div role="group" aria-label="Formato" className="segmented sparql__formats">
            {RESULT_FORMATS.map((f) => (
              <button
                key={f.id}
                type="button"
                className="segmented__button"
                aria-pressed={f.id === format}
                onClick={() => onFormat(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {run.status === 'idle' && <p className="sparql__empty">{SPARQL_TEXT.idle}</p>}
      {run.status === 'running' && (
        <p role="status" className="sparql__empty">
          {SPARQL_TEXT.running}
        </p>
      )}
      {run.status === 'error' && (
        <p role="alert" className="sparql__error">
          {run.message}
        </p>
      )}
      {result && <ResultBody result={result} format={format} />}
    </section>
  )
}

function ResultBody({ result, format }: { result: SparqlRunResult; format: ResultFormat }) {
  const truncated = result.truncated && <p className="sparql__note">{SPARQL_TEXT.truncated}</p>

  if (result.kind === 'graph') {
    return (
      <>
        {truncated}
        <pre className="sparql__code" tabIndex={0} aria-label="Grafo resultado">
          {result.text}
        </pre>
      </>
    )
  }

  const { data } = result
  if (format === 'json') {
    return (
      <>
        {truncated}
        <pre className="sparql__code" tabIndex={0} aria-label="Resultados en JSON">
          {JSON.stringify(data, null, 2)}
        </pre>
      </>
    )
  }

  if (typeof data.boolean === 'boolean') {
    return <p className="mono sparql__boolean">{String(data.boolean)}</p>
  }

  const vars = resultVars(data)
  const rows = resultRows(data)
  if (rows.length === 0) return <p className="sparql__empty">{SPARQL_TEXT.empty}</p>

  if (format === 'csv') {
    return (
      <>
        {truncated}
        <pre className="sparql__code" tabIndex={0} aria-label="Resultados en CSV">
          {toCsv(data)}
        </pre>
      </>
    )
  }

  return (
    <>
      {truncated}
      <div className="sparql__table-wrap" tabIndex={0} role="region" aria-label="Tabla de resultados">
        <table className="sparql__table">
          <thead>
            <tr>
              {vars.map((v) => (
                <th key={v} scope="col" className="mono">
                  ?{v}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i}>
                {vars.map((v) => (
                  <td key={v}>{termText(row[v])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
