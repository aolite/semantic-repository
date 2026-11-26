/**
 * Piezas de la pantalla «Ficha de ontología» que comparten la ficha de una
 * ontología propia (`OntologyPage`) y la de una externa
 * (`ExternalOntologyPage`, decisión 51): migas, cabecera, descripción,
 * métricas e historial de versiones. El prototipo solo dibuja la propia; la
 * externa reutiliza estas piezas con sus datos.
 */
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type {
  CatalogRef,
  ConsistencyRead,
  DocumentationCoverageRead,
  OntologyMetricsRead,
  OwlProfile,
  VocabularyKind,
  VocabularyStatus,
} from '../api'
import { NOT_STATED } from '../catalog/labels'
import { CopyUriButton } from '../components/CopyUriButton'
import { KindTag, StatusTag, SyntheticTag, TypeTag } from '../components/Tags'
import { catalogRoute } from '../crud/navigation'
import { KINDS, plural, prefixLabel } from './labels'

/** Migas «Vocabularios / {tipo} / {actual}». */
export function OntologyBreadcrumbs({ kind, current }: { kind: 'own' | 'external'; current: string }) {
  return (
    <nav aria-label="Migas de pan" className="breadcrumbs">
      <Link to="/vocabularios">Vocabularios</Link>
      <span aria-hidden="true">/</span>
      <span>{KINDS[kind].short}</span>
      <span aria-hidden="true">/</span>
      <span aria-current="page">{current}</span>
    </nav>
  )
}

interface OntologyHeaderProps {
  kind: VocabularyKind
  status: VocabularyStatus
  synthetic?: boolean
  /** Etiqueta de versión («v1.2.0 · actual»); sin ella no se muestra. */
  versionTag?: string | null
  title: string
  prefix: string | null
  namespace: string | null
  /** URI que se muestra y se copia. */
  uri: string
  catalog?: CatalogRef | null
  /** Enlace de «Descargar Turtle»; sin él no se muestra el botón. */
  turtleHref?: string | null
}

/** Cabecera de la ficha: etiquetas, título, prefijo y espacio de nombres, URI y acciones. */
export function OntologyHeader(props: OntologyHeaderProps) {
  const { kind, status, synthetic, versionTag, title, namespace, uri, catalog, turtleHref } = props
  const prefix = prefixLabel(props.prefix)
  return (
    <header className="vocab-header">
      <div className="dataset__header">
        <div className="dataset__tags">
          <TypeTag>owl:Ontology</TypeTag>
          <KindTag kind={kind} />
          <StatusTag status={status} />
          {synthetic && <SyntheticTag label="Sintético" />}
          {versionTag && <span className="tag tag--version mono">{versionTag}</span>}
        </div>
        <h1 className="page-title dataset__title">{title}</h1>
        {(prefix || namespace) && (
          <span className="mono vocab-header__ns">
            {prefix && <span className="card__prefix">{prefix}</span>} {namespace}
          </span>
        )}
        <span className="mono dataset__uri">{uri}</span>
        {catalog && (
          <p className="catalog-link">
            Catálogo: <Link to={catalogRoute(catalog.slug)}>{catalog.title ?? catalog.slug}</Link>
          </p>
        )}
      </div>
      <div className="vocab-header__actions">
        <CopyUriButton uri={uri} />
        {turtleHref && (
          <a className="button button--primary" href={turtleHref} download>
            Descargar Turtle
          </a>
        )}
      </div>
    </header>
  )
}

/** Panel «Descripción». */
export function DescriptionPanel({ description }: { description: string | null }) {
  return (
    <section aria-labelledby="h-desc" className="panel">
      <h2 id="h-desc" className="panel__title">
        Descripción
      </h2>
      {description ? <p className="panel__text">{description}</p> : <p className="muted">{NOT_STATED}</p>}
    </section>
  )
}

interface MetricsPanelProps {
  metrics: OntologyMetricsRead | null
  profile: OwlProfile | null
  consistency: ConsistencyRead | null
  documentation: DocumentationCoverageRead | null
  /** Texto junto al título («calculadas en backend · v1.2.0»). */
  hint: string
  /** Sustituye todo el contenido (p. ej. una externa sin versiones). */
  empty?: ReactNode
}

/** Panel «Métricas»: recuentos OWL, perfil, expresividad, consistencia y documentación. */
export function MetricsPanel({ metrics: m, profile, consistency, documentation, hint, empty }: MetricsPanelProps) {
  const tiles = m
    ? [
        { n: m.classes, label: 'Clases' },
        { n: m.object_properties, label: 'Propiedades de objeto' },
        { n: m.data_properties, label: 'Propiedades de datos' },
        { n: m.individuals, label: 'Individuos' },
        { n: m.logical_axioms, label: 'Axiomas lógicos' },
        { n: m.imports, label: 'Imports' },
      ]
    : []
  const reasoner = consistency?.reasoner
  return (
    <section aria-labelledby="h-met" className="panel">
      <div className="panel__head">
        <h2 id="h-met" className="panel__title">
          Métricas
        </h2>
        {!empty && <span className="panel__hint mono">{hint}</span>}
      </div>
      {empty ?? (
        <>
          {m ? (
            <ul className="metrics" aria-label="Métricas OWL">
              {tiles.map((t) => (
                <li key={t.label} className="metric">
                  <span className="metric__n">{t.n}</span>
                  <span className="metric__label">{t.label}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Las métricas de esta versión no se han calculado todavía.</p>
          )}
          <dl className="fields fields--grid">
            <div>
              <dt className="mono">Perfil OWL</dt>
              <dd>
                {profile ? profile.name : 'Sin calcular'}
                {profile && profile.compatible.length > 0 && (
                  <span className="field-note">
                    Compatible con {profile.compatible.join(', ')}
                    {profile.approximate !== false ? ' (aproximado)' : ''}
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt className="mono">Expresividad DL</dt>
              <dd>{m?.dl_expressivity ?? 'Sin calcular'}</dd>
            </div>
            <div>
              <dt className="mono">Consistencia{reasoner ? ` (${reasoner})` : ''}</dt>
              <dd>
                <ConsistencyValue consistency={consistency} />
              </dd>
            </div>
            <div>
              <dt className="mono">Cobertura de documentación</dt>
              <dd>{documentationLabel(documentation)}</dd>
            </div>
          </dl>
        </>
      )}
    </section>
  )
}

function ConsistencyValue({ consistency: c }: { consistency: ConsistencyRead | null }) {
  if (!c) return <>Sin calcular</>
  const unsat = c.unsatisfiable_classes
  return (
    <>
      {c.consistent === true && `Consistente · ${plural(unsat ?? 0, 'clase insatisfacible', 'clases insatisfacibles')}`}
      {c.consistent === false && `Inconsistente${c.detail ? ` · ${c.detail}` : ''}`}
      {c.consistent === null && `No se ha podido comprobar: ${c.detail ?? 'motivo no indicado'}`}
      {c.unsatisfiable.length > 0 && (
        <ul className="field-list mono" aria-label="Clases insatisfacibles">
          {c.unsatisfiable.map((iri) => (
            <li key={iri}>{iri}</li>
          ))}
        </ul>
      )}
      {c.includes_imports === false && <span className="field-note">Razonado sin las ontologías importadas</span>}
    </>
  )
}

const percentFormat = new Intl.NumberFormat('es', { maximumFractionDigits: 1 })

function documentationLabel(d: DocumentationCoverageRead | null): string {
  if (!d || d.percent === null) return 'Sin calcular'
  return `rdfs:comment en ${percentFormat.format(d.percent)} % de clases y propiedades`
}

/** Fila del historial de versiones. */
export interface VersionRow {
  key: string
  /** Número o etiqueta visible de la versión. */
  label: string
  /** Nombre accesible del enlace («Versión 1.2.0»). */
  ariaLabel: string
  /** Ruta de la ficha de esa versión; null si no tiene ficha. */
  to: string | null
  current: boolean
  /** Es la versión que muestra la ficha (`aria-current`). */
  selected: boolean
  date: string
  note: string | null
  /** Enlace de descarga del RDF de esa versión. */
  download?: { href: string; label: string; ariaLabel: string }
}

/** «Historial de versiones»: punto, número, fecha, nota y estado («Actual» o «Sustituida»). */
export function VersionHistory({ rows }: { rows: VersionRow[] }) {
  return (
    <div className="history">
      <h3 className="history__title">Historial de versiones</h3>
      <ul className="history__list">
        {rows.map((row) => (
          <li key={row.key} className={`history__item${row.selected ? ' history__item--selected' : ''}`}>
            <span className={`history__dot${row.current ? ' history__dot--current' : ''}`} aria-hidden="true" />
            {row.to ? (
              <Link
                className="mono history__num"
                to={row.to}
                aria-current={row.selected ? 'page' : undefined}
                aria-label={row.ariaLabel}
              >
                {row.label}
              </Link>
            ) : (
              <span className="mono history__num">{row.label}</span>
            )}
            <span className="history__date">{row.date}</span>
            <span className="history__note">{row.note ?? ''}</span>
            <span className={`badge${row.current ? ' badge--current' : ''}`}>{row.current ? 'Actual' : 'Sustituida'}</span>
            {row.download && (
              <a className="history__download" href={row.download.href} download aria-label={row.download.ariaLabel}>
                {row.download.label}
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
