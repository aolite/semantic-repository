import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  ApiError,
  fetchDataset,
  fetchDatasetRdf,
  isAbortError,
  type DatasetDetail,
  type DcatMetadata,
  type DistributionRead,
  type DomainRef,
  type ProvenanceStep,
  type RdfFormat,
  type ThemeRef,
  type VersionDetail,
  type VersionSummary,
} from '../api'
import {
  accessLabel,
  DOMAINS,
  lastSegment,
  NOT_STATED,
  PLACEHOLDERS,
  resourceLabel,
  themeLabel,
} from '../catalog/labels'
import { DomainTag, SyntheticTag, TypeTag } from '../components/Tags'
import '../styles/dataset.css'

type Load =
  | { key: string; status: 'ok'; data: DatasetDetail }
  | { key: string; status: 'not-found' }
  | { key: string; status: 'error' }

/** Enlace a la ficha de una versión: `?version=` salvo la actual. */
function versionHref(slug: string, version: string | null, current: boolean): string {
  const base = `/datasets/${encodeURIComponent(slug)}`
  return current || !version ? base : `${base}?version=${encodeURIComponent(version)}`
}

export function DatasetPage() {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const version = searchParams.get('version')
  const [reload, setReload] = useState(0)
  const [load, setLoad] = useState<Load | null>(null)
  const key = JSON.stringify({ slug, version, reload })

  useEffect(() => {
    const controller = new AbortController()
    fetchDataset(slug, version, controller.signal)
      .then((data) => setLoad({ key, status: 'ok', data }))
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        const notFound = error instanceof ApiError && (error.status === 404 || error.status === 422)
        setLoad({ key, status: notFound ? 'not-found' : 'error' })
      })
    return () => controller.abort()
  }, [slug, version, key])

  const current = load?.key === key ? load : null

  if (!current) {
    return (
      <p role="status" className="state">
        Cargando dataset…
      </p>
    )
  }

  if (current.status === 'not-found') {
    return (
      <div className="dataset">
        <Breadcrumbs />
        <h1 className="page-title">Dataset no encontrado</h1>
        <p className="muted">
          No existe ningún dataset{version ? ` con la versión ${version}` : ''} en esta dirección.{' '}
          <Link to="/">Volver al catálogo</Link>
        </p>
      </div>
    )
  }

  if (current.status === 'error') {
    return (
      <div className="dataset">
        <Breadcrumbs />
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar el dataset.</p>
          <button type="button" className="button button--secondary" onClick={() => setReload((n) => n + 1)}>
            Reintentar
          </button>
        </div>
      </div>
    )
  }

  return <DatasetView data={current.data} requestedVersion={version} />
}

function Breadcrumbs({ domain }: { domain?: DomainRef | null }) {
  return (
    <nav aria-label="Migas de pan" className="breadcrumbs">
      <Link to="/">Catálogo</Link>
      {domain && (
        <>
          <span aria-hidden="true">/</span>
          <span>{DOMAINS[domain.slug].label}</span>
        </>
      )}
      <span aria-hidden="true">/</span>
      <span aria-current="page">Dataset</span>
    </nav>
  )
}

function DatasetView({ data, requestedVersion }: { data: DatasetDetail; requestedVersion: string | null }) {
  const v = data.version
  const isCurrent = !!v && (v.version === data.current_version || !requestedVersion)
  const title = v?.title ?? data.title ?? data.slug
  const description = v?.description ?? data.description
  const access = accessLabel(v?.metadata.access_rights ?? null)
  const synthetic = data.synthetic || !!v?.synthetic
  // URI persistente: la de la serie si se ve la versión actual; la de la versión si es antigua.
  const uri = v && !isCurrent ? v.uri : data.uri

  return (
    <div className="dataset">
      <Breadcrumbs domain={data.domain} />

      <header className="dataset__header">
        <div className="dataset__tags">
          <TypeTag>dcat:Dataset</TypeTag>
          {data.domain && <DomainTag slug={data.domain.slug} />}
          {access && <span className="tag tag--neutral">Acceso {access.toLowerCase()}</span>}
          {synthetic && <SyntheticTag />}
          {v?.version && (
            <span className="tag tag--version mono">
              v{v.version}
              {isCurrent ? ' · actual' : ''}
            </span>
          )}
        </div>
        <h1 className="page-title dataset__title">{title}</h1>
        <div className="dataset__uri-row">
          <span className="mono dataset__uri">{uri}</span>
          <CopyUriButton uri={uri} />
        </div>
      </header>

      <div className="dataset__columns">
        <div className="dataset__main">
          <section aria-labelledby="h-desc" className="panel">
            <h2 id="h-desc" className="panel__title">
              Descripción
            </h2>
            {description ? <p className="panel__text">{description}</p> : <p className="muted">{NOT_STATED}</p>}
            <p className="panel__keywords">
              Palabras clave: {v && v.keywords.length > 0 ? v.keywords.join(', ') : 'sin palabras clave en esta versión'}
            </p>
          </section>

          <VersioningSection data={data} version={v} />
          <DistributionsSection distributions={v?.distributions ?? []} />
          <ProvenanceSection steps={v?.provenance ?? []} version={v?.version ?? null} />
          {v && <RdfSection slug={data.slug} version={isCurrent ? null : v.version} />}
        </div>

        <div className="dataset__side">
          <section aria-labelledby="h-fair" className="panel">
            <div className="panel__head">
              <h2 id="h-fair" className="panel__title">
                Evaluación FAIR
              </h2>
              {v?.version && <span className="panel__hint">v{v.version}</span>}
            </div>
            <p className="muted">Disponible en la fase 4</p>
          </section>

          {v && <MetadataAside metadata={v.metadata} domains={data.domains} />}
        </div>
      </div>
    </div>
  )
}

type CopyState = 'idle' | 'copied' | 'failed'

function CopyUriButton({ uri }: { uri: string }) {
  const [state, setState] = useState<CopyState>('idle')

  async function copy() {
    try {
      await navigator.clipboard.writeText(uri)
      setState('copied')
    } catch {
      setState('failed')
    }
  }

  return (
    <>
      <button type="button" className="button button--secondary" onClick={copy}>
        Copiar URI
      </button>
      <span role="status" className="dataset__copy-status">
        {state === 'copied' ? 'URI copiada' : state === 'failed' ? 'No se ha podido copiar la URI' : ''}
      </span>
    </>
  )
}

function VersioningSection({ data, version: v }: { data: DatasetDetail; version: VersionDetail | null }) {
  const shownIssued = data.versions.find((s) => s.version === v?.version)?.issued ?? v?.metadata.issued ?? null
  return (
    <section aria-labelledby="h-ver" className="panel">
      <div className="panel__head">
        <h2 id="h-ver" className="panel__title">
          Versionado
        </h2>
        <span className="panel__hint mono">dcat:version · adms:versionNotes</span>
      </div>
      {v ? (
        <>
          <dl className="fields fields--grid">
            <div>
              <dt className="mono">dcat:version</dt>
              <dd className="strong">{v.version ?? NOT_STATED}</dd>
            </div>
            <div>
              <dt className="mono">dct:issued (versión)</dt>
              <dd>{shownIssued ?? PLACEHOLDERS.date}</dd>
            </div>
            <div>
              <dt className="mono">dcat:previousVersion</dt>
              <dd>
                {v.previous_version ? (
                  <Link className="mono small" to={versionHref(data.slug, v.previous_version.version, false)}>
                    {data.slug}/{v.previous_version.version ?? lastSegment(v.previous_version.uri)}
                  </Link>
                ) : (
                  'Ninguna'
                )}
              </dd>
            </div>
            <div>
              <dt className="mono">dcat:inSeries</dt>
              <dd>
                <Link className="mono small" to={versionHref(data.slug, null, true)}>
                  {lastSegment(v.in_series)}
                </Link>
              </dd>
            </div>
          </dl>
          <div className="fields__block">
            <span className="mono field-label">adms:versionNotes</span>
            <p className="panel__text">{v.version_notes ?? NOT_STATED}</p>
          </div>
        </>
      ) : (
        <p className="muted">La serie no tiene versiones publicadas.</p>
      )}
      {data.versions.length > 0 && <VersionHistory data={data} shown={v?.version ?? null} />}
    </section>
  )
}

function VersionHistory({ data, shown }: { data: DatasetDetail; shown: string | null }) {
  return (
    <div className="history">
      <h3 className="history__title">Historial de versiones</h3>
      <ul className="history__list">
        {data.versions.map((s: VersionSummary) => {
          const isShown = s.version === shown
          const label = s.version ?? lastSegment(s.uri)
          return (
            <li key={s.uri} className="history__item">
              <span className={`history__dot${s.current ? ' history__dot--current' : ''}`} aria-hidden="true" />
              {s.described ? (
                <Link
                  className="mono history__num"
                  to={versionHref(data.slug, s.version, s.current)}
                  aria-current={isShown ? 'page' : undefined}
                  aria-label={`Versión ${label}`}
                >
                  {label}
                </Link>
              ) : (
                <span className="mono history__num">{label}</span>
              )}
              <span className="history__date">{s.issued ?? PLACEHOLDERS.date}</span>
              <span className="history__note">{s.notes ?? ''}</span>
              <span className={`badge${s.current ? ' badge--current' : ''}`}>{s.current ? 'Actual' : 'Sustituida'}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function DistributionsSection({ distributions }: { distributions: DistributionRead[] }) {
  return (
    <section aria-labelledby="h-dist" className="panel">
      <div className="panel__head">
        <h2 id="h-dist" className="panel__title">
          Distribuciones
        </h2>
        <span className="panel__hint mono">dcat:distribution</span>
      </div>
      {distributions.length === 0 ? (
        <p className="muted">Esta versión no declara distribuciones.</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--stack">
            <thead>
              <tr>
                <th scope="col">Distribución</th>
                <th scope="col">dcat:mediaType</th>
                <th scope="col">Acceso</th>
              </tr>
            </thead>
            <tbody>
              {distributions.map((d) => (
                <tr key={d.uri}>
                  <th scope="row" data-label="Distribución">
                    {d.title ?? lastSegment(d.uri)}
                  </th>
                  <td data-label="dcat:mediaType" className="mono">
                    {d.media_type ?? NOT_STATED}
                  </td>
                  <td data-label="Acceso">{accessLabel(d.access_rights) ?? NOT_STATED}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function ProvenanceSection({ steps, version }: { steps: ProvenanceStep[]; version: string | null }) {
  const agents = [
    ...new Set(steps.flatMap((s) => s.agents.map((a) => resourceLabel(a, ''))).filter((label) => label !== '')),
  ]
  return (
    <section aria-labelledby="h-prov" className="panel">
      <div className="panel__head">
        <h2 id="h-prov" className="panel__title">
          Procedencia
        </h2>
        <span className="panel__hint mono">PROV-O</span>
      </div>
      {steps.length === 0 ? (
        <p className="muted">Esta versión no declara procedencia.</p>
      ) : (
        <>
          <ol className="prov" aria-label="Cadena de procedencia">
            {steps.map((step, i) => (
              <li key={step.uri ?? `step-${i}`} className={`prov__step prov__step--${step.kind}`}>
                <span className="mono prov__kind">{step.kind === 'activity' ? 'prov:Activity' : 'prov:Entity'}</span>
                <span className="prov__label">{step.label ?? step.uri ?? NOT_STATED}</span>
              </li>
            ))}
            <li className="prov__step prov__step--self">
              <span className="mono prov__kind">prov:Entity</span>
              <span className="prov__label">Este dataset{version ? ` · v${version}` : ''}</span>
            </li>
          </ol>
          {agents.length > 0 && <p className="panel__hint">prov:wasAssociatedWith · {agents.join(', ')}</p>}
        </>
      )}
    </section>
  )
}

const RDF_TABS: { id: RdfFormat; label: string }[] = [
  { id: 'turtle', label: 'Turtle' },
  { id: 'jsonld', label: 'JSON-LD' },
]

type RdfLoad = { key: string; text?: string; error?: boolean }

function RdfSection({ slug, version }: { slug: string; version: string | null }) {
  const [format, setFormat] = useState<RdfFormat>('turtle')
  const [load, setLoad] = useState<RdfLoad | null>(null)
  const key = JSON.stringify({ slug, version, format })

  useEffect(() => {
    const controller = new AbortController()
    fetchDatasetRdf(slug, format, version, controller.signal)
      .then((text) => setLoad({ key, text }))
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        setLoad({ key, error: true })
      })
    return () => controller.abort()
  }, [slug, version, format, key])

  const current = load?.key === key ? load : null

  return (
    <section aria-labelledby="h-rdf" className="panel panel--dark">
      <div className="panel__head panel__head--wrap">
        <h2 id="h-rdf" className="panel__title">
          Descripción RDF
        </h2>
        <div role="group" aria-label="Serialización" className="segmented segmented--dark">
          {RDF_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className="segmented__button"
              aria-pressed={tab.id === format}
              onClick={() => setFormat(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      {!current && (
        <p role="status" className="rdf__state">
          Cargando RDF…
        </p>
      )}
      {current?.error && (
        <p role="alert" className="rdf__state">
          No se ha podido cargar el RDF.
        </p>
      )}
      {current?.text !== undefined && (
        <pre className="rdf" tabIndex={0} aria-label={`RDF en ${format === 'turtle' ? 'Turtle' : 'JSON-LD'}`}>
          {current.text}
        </pre>
      )}
    </section>
  )
}

function themeStyle(theme: ThemeRef, domains: DomainRef[]) {
  const domain = domains.find((d) => d.uri === theme.scheme)
  return domain ? { background: DOMAINS[domain.slug].tagBg, color: DOMAINS[domain.slug].tagFg } : undefined
}

function MetadataAside({ metadata: m, domains }: { metadata: DcatMetadata; domains: DomainRef[] }) {
  const access = accessLabel(m.access_rights)
  return (
    <aside aria-labelledby="h-meta" className="panel">
      <h2 id="h-meta" className="panel__title">
        Metadatos DCAT-AP
      </h2>
      <dl className="fields">
        <div>
          <dt className="mono">dct:publisher</dt>
          <dd>{resourceLabel(m.publisher, NOT_STATED)}</dd>
        </div>
        <div>
          <dt className="mono">dcat:contactPoint</dt>
          <dd>{resourceLabel(m.contact_point, PLACEHOLDERS.contact)}</dd>
        </div>
        <div>
          <dt className="mono">dct:license</dt>
          <dd>{resourceLabel(m.license, PLACEHOLDERS.license)}</dd>
        </div>
        <div>
          <dt className="mono">dct:accessRights</dt>
          <dd>{access ? (m.access_rights?.code ? `${access} (vocabulario EU Access Right)` : access) : NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">dct:issued · dct:modified</dt>
          <dd>
            {m.issued ?? PLACEHOLDERS.date} · {m.modified ?? PLACEHOLDERS.date}
          </dd>
        </div>
        <div>
          <dt className="mono">dct:isReferencedBy</dt>
          <dd>
            {m.is_referenced_by.length > 0
              ? m.is_referenced_by.map((r) => resourceLabel(r, PLACEHOLDERS.project)).join(', ')
              : PLACEHOLDERS.project}
          </dd>
        </div>
        <div>
          <dt className="mono">dcat:theme</dt>
          <dd className="pills">
            {m.themes.length > 0 ? (
              m.themes.map((t) => (
                <span key={t.uri} className="pill" style={themeStyle(t, domains)}>
                  {themeLabel(t)}
                </span>
              ))
            ) : (
              <span className="muted">Sin temas en esta versión</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="mono">dct:conformsTo</dt>
          <dd className="pills">
            {m.conforms_to.length > 0 ? (
              m.conforms_to.map((c, i) => (
                <span key={c.uri ?? `conforms-${i}`} className="pill pill--brand">
                  {resourceLabel(c, NOT_STATED)}
                </span>
              ))
            ) : (
              <span className="muted">{NOT_STATED}</span>
            )}
          </dd>
        </div>
      </dl>
    </aside>
  )
}
