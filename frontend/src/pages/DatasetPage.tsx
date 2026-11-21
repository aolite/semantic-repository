import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  ApiError,
  fetchDataset,
  fetchDatasetRdf,
  isAbortError,
  listCatalogs,
  updateDataset,
  withdrawDataset,
  type CatalogRef,
  type DatasetDetail,
  type DatasetUpdate,
  type GoneResponse,
  type IngestResult,
  type DcatMetadata,
  type DomainRef,
  type ProvenanceStep,
  type RdfFormat,
  type ResourceRef,
  type ThemeRef,
  type VersionDetail,
  type VersionSummary,
} from '../api'
import {
  accessLabel,
  domainStyle,
  lastSegment,
  NOT_STATED,
  PLACEHOLDERS,
  resourceLabel,
  themeLabel,
} from '../catalog/labels'
import { useAuth } from '../auth/useAuth'
import { canEdit } from '../auth/roles'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { CopyUriButton } from '../components/CopyUriButton'
import { GoneView } from '../components/GoneView'
import { Notice } from '../components/Notice'
import { describeError, goneFromError } from '../crud/errors'
import { catalogRoute, datasetRoute, noticeState } from '../crud/navigation'
import { ResourceForm, type ResourceFormValues } from '../crud/ResourceForm'
import { VersionForm } from '../crud/VersionForm'
import { useApiLoad } from '../hooks/useApiLoad'
import { DistributionsSection } from '../dataset/DistributionsSection'
import { FairSection } from '../dataset/FairSection'
import { DomainTag, SyntheticTag, TypeTag } from '../components/Tags'
import { conceptRouteFromUri, ontologyRouteFromUri } from '../vocab/routes'
import '../styles/dataset.css'
import '../styles/crud.css'

type Load =
  | { key: string; base: string; status: 'ok'; data: DatasetDetail }
  | { key: string; status: 'not-found' }
  | { key: string; status: 'gone'; gone: GoneResponse }
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
  const base = JSON.stringify({ slug, version })
  const key = JSON.stringify({ slug, version, reload })

  useEffect(() => {
    const controller = new AbortController()
    fetchDataset(slug, version, controller.signal)
      .then((data) => setLoad({ key, base, status: 'ok', data }))
      .catch((error: unknown) => {
        if (isAbortError(error) || controller.signal.aborted) return
        const gone = goneFromError(error)
        if (gone) {
          setLoad({ key, status: 'gone', gone })
          return
        }
        const notFound = error instanceof ApiError && (error.status === 404 || error.status === 422)
        setLoad({ key, status: notFound ? 'not-found' : 'error' })
      })
    return () => controller.abort()
  }, [slug, version, key, base])

  // Tras editar o publicar se vuelve a pedir la ficha: mientras tanto se sigue mostrando la anterior.
  const current = load?.key === key ? load : load?.status === 'ok' && load.base === base ? load : null

  if (!current) {
    return (
      <p role="status" className="state">
        Cargando dataset…
      </p>
    )
  }

  // 410: dataset dado de baja (decisión 49), con su ficha mínima.
  if (current.status === 'gone') return <GoneView gone={current.gone} />

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

  return (
    <DatasetView data={current.data} requestedVersion={version} onChanged={() => setReload((n) => n + 1)} />
  )
}

function Breadcrumbs({ domain, catalog }: { domain?: DomainRef | null; catalog?: CatalogRef | null }) {
  return (
    <nav aria-label="Migas de pan" className="breadcrumbs">
      <Link to="/">Catálogo</Link>
      {catalog && (
        <>
          <span aria-hidden="true">/</span>
          <Link to={catalogRoute(catalog.slug)}>{catalog.title ?? catalog.slug}</Link>
        </>
      )}
      {domain && (
        <>
          <span aria-hidden="true">/</span>
          <span>{domainStyle(domain.slug).label}</span>
        </>
      )}
      <span aria-hidden="true">/</span>
      <span aria-current="page">Dataset</span>
    </nav>
  )
}

interface DatasetViewProps {
  data: DatasetDetail
  requestedVersion: string | null
  /** Vuelve a pedir la ficha tras editarla o publicar una versión. */
  onChanged: () => void
}

function DatasetView({ data, requestedVersion, onChanged }: DatasetViewProps) {
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
      <Breadcrumbs domain={data.domain} catalog={data.catalog} />

      <DatasetActions data={data} onChanged={onChanged}>
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
      </DatasetActions>

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
          <DistributionsSection slug={data.slug} version={v?.version ?? null} distributions={v?.distributions ?? []} />
          <ProvenanceSection steps={v?.provenance ?? []} version={v?.version ?? null} />
          {v && <RdfSection slug={data.slug} version={isCurrent ? null : v.version} />}
        </div>

        <div className="dataset__side">
          <FairSection fair={v?.fair ?? null} version={v?.version ?? null} />

          {v && <MetadataAside metadata={v.metadata} domains={data.domains} />}
        </div>
      </div>
    </div>
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

/**
 * Color de los temas: el del dominio de la serie. Desde la fase 3 el dominio
 * es un concepto de `vocab/dominio` y no el esquema de los temas, así que solo
 * se colorean si la serie tiene un único dominio.
 */
function themeStyle(domains: DomainRef[]) {
  if (domains.length !== 1) return undefined
  const style = domainStyle(domains[0].slug)
  return { background: style.tagBg, color: style.tagFg }
}

/** Tema enlazado a su concepto en el navegador SKOS si su URI sigue el patrón. */
function ThemePill({ theme, domains }: { theme: ThemeRef; domains: DomainRef[] }) {
  const to = conceptRouteFromUri(theme.uri)
  const style = themeStyle(domains)
  return to ? (
    <Link to={to} className="pill pill--link" style={style}>
      {themeLabel(theme)}
    </Link>
  ) : (
    <span className="pill" style={style}>
      {themeLabel(theme)}
    </span>
  )
}

/** `dct:conformsTo` enlazado a la ficha de ontología si es una ontología propia (o una versión). */
function ConformsToPill({ resource }: { resource: ResourceRef }) {
  const to = resource.uri ? ontologyRouteFromUri(resource.uri) : null
  const label = resourceLabel(resource, NOT_STATED)
  return to ? (
    <Link to={to} className="pill pill--brand pill--link">
      {label}
    </Link>
  ) : (
    <span className="pill pill--brand">{label}</span>
  )
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
              m.themes.map((t) => <ThemePill key={t.uri} theme={t} domains={domains} />)
            ) : (
              <span className="muted">Sin temas en esta versión</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="mono">dct:conformsTo</dt>
          <dd className="pills">
            {m.conforms_to.length > 0 ? (
              m.conforms_to.map((c, i) => <ConformsToPill key={c.uri ?? `conforms-${i}`} resource={c} />)
            ) : (
              <span className="muted">{NOT_STATED}</span>
            )}
          </dd>
        </div>
      </dl>
    </aside>
  )
}

type Panel = 'none' | 'edit' | 'version'

interface DatasetActionsProps {
  data: DatasetDetail
  onChanged: () => void
  /** Cabecera de la ficha: las acciones van a su derecha. */
  children: ReactNode
}

/**
 * Acciones del editor y el admin en la ficha (decisión 49): «Editar» (metadatos
 * de la serie y catálogo), «Nueva versión» (botón del prototipo, con subida
 * del RDF) y «Dar de baja» con confirmación. El miembro y el anónimo no las
 * ven.
 */
function DatasetActions({ data, onChanged, children }: DatasetActionsProps) {
  const { user, token } = useAuth()
  const navigate = useNavigate()
  const editor = canEdit(user?.role) && !!token
  const [panel, setPanel] = useState<Panel>('none')
  const [saved, setSaved] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)
  const editButton = useRef<HTMLButtonElement>(null)
  const versionButton = useRef<HTMLButtonElement>(null)
  // Los catálogos (para mover el dataset) solo se piden si hacen falta.
  const catalogs = useApiLoad(editor && panel !== 'none' ? listCatalogs : null)
  const catalogItems = catalogs.state.status === 'ok' ? catalogs.state.data.items : undefined

  const title = data.title ?? data.slug
  const initial: ResourceFormValues = {
    slug: data.slug,
    title: data.title ?? '',
    description: data.description ?? '',
    publisher_name: '',
    catalog: data.catalog?.slug ?? '',
  }

  function toggle(next: Panel) {
    setSaved(null)
    setPanel(panel === next ? 'none' : next)
  }

  function closePanel(focus: HTMLButtonElement | null) {
    setPanel('none')
    focus?.focus()
  }

  async function handleEdit(values: ResourceFormValues) {
    const body: DatasetUpdate = {}
    if (values.title.trim() !== initial.title) body.title = values.title.trim()
    if (values.description.trim() !== initial.description) body.description = values.description.trim()
    // La API no devuelve el publicador de la serie: solo se manda si se escribe uno.
    if (values.publisher_name.trim()) body.publisher_name = values.publisher_name.trim()
    if (values.catalog && values.catalog !== initial.catalog) body.catalog = values.catalog
    if (Object.keys(body).length > 0) await updateDataset(data.slug, body, token ?? '')
    setSaved(
      Object.keys(body).length === 0
        ? 'No había cambios que guardar.'
        : body.catalog
          ? 'Cambios guardados. El dataset se ha movido de catálogo.'
          : 'Cambios guardados.',
    )
    closePanel(editButton.current)
    onChanged()
  }

  function handlePublished(result: IngestResult) {
    const versions = result.versions.join(', ')
    const message = !result.changed
      ? 'El RDF era idéntico al publicado: no ha cambiado nada.'
      : versions
        ? `RDF publicado. Versiones de la serie: ${versions}.`
        : 'RDF publicado.'
    setPanel('none')
    if (result.slug !== data.slug) {
      navigate(datasetRoute(result.slug), { state: noticeState(message) })
      return
    }
    setSaved(message)
    versionButton.current?.focus()
    onChanged()
  }

  async function handleWithdraw() {
    setWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawDataset(data.slug, token ?? '')
      const notice = noticeState(`Dataset «${title}» dado de baja.`)
      navigate(data.catalog ? catalogRoute(data.catalog.slug) : '/', { state: notice })
    } catch (error) {
      setWithdrawError(
        describeError(error, {
          notFound: 'El dataset no existe.',
          fallback: 'No se ha podido dar de baja el dataset.',
        }).message,
      )
      setWithdrawing(false)
    }
  }

  return (
    <>
      <div className="crud-header">
        <div className="crud-header__text">{children}</div>
        {editor && (
          <div className="crud-actions" role="group" aria-label="Acciones del dataset">
            <button
              ref={editButton}
              type="button"
              className="button button--secondary"
              aria-expanded={panel === 'edit'}
              onClick={() => toggle('edit')}
            >
              Editar
            </button>
            <button
              ref={versionButton}
              type="button"
              className="button button--primary"
              aria-expanded={panel === 'version'}
              onClick={() => toggle('version')}
            >
              Nueva versión
            </button>
            <button
              type="button"
              className="button button--danger-outline"
              onClick={() => {
                setWithdrawError(null)
                setConfirming(true)
              }}
            >
              Dar de baja
            </button>
          </div>
        )}
      </div>

      <Notice />
      {saved && (
        <p role="status" className="notice">
          {saved}
        </p>
      )}

      {editor && panel === 'edit' && (
        <ResourceForm
          heading="Editar dataset"
          mode="edit"
          initial={initial}
          requirePublisher={false}
          publisherHint="Déjalo vacío para no cambiarlo."
          catalogs={catalogItems}
          submitLabel="Guardar cambios"
          errorContext={{ notFound: 'El dataset no existe.', fallback: 'No se han podido guardar los cambios.' }}
          onSubmit={handleEdit}
          onCancel={() => closePanel(editButton.current)}
        />
      )}

      {editor && panel === 'version' && token && (
        <VersionForm
          catalog={data.catalog ?? null}
          catalogs={catalogItems}
          token={token}
          onPublished={handlePublished}
          onCancel={() => closePanel(versionButton.current)}
        />
      )}

      {confirming && (
        <ConfirmDialog
          title="Dar de baja el dataset"
          confirmLabel="Dar de baja"
          busy={withdrawing}
          error={withdrawError && <p>{withdrawError}</p>}
          onConfirm={handleWithdraw}
          onCancel={() => setConfirming(false)}
        >
          <p>
            «{title}» y todas sus versiones dejarán de aparecer en los listados y en las consultas SPARQL, y sus URIs
            responderán que se dio de baja. Su slug no se podrá reutilizar.
          </p>
          <p>
            <strong>Se eliminarán los ficheros de todas sus distribuciones.</strong> Esta acción no se puede deshacer
            desde la aplicación.
          </p>
        </ConfirmDialog>
      )}
    </>
  )
}
