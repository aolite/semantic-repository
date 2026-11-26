import { useCallback } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  fetchOntology,
  ontologyRdfUrl,
  type Alignment,
  type DatasetUse,
  type ImportRef,
  type OntologyDetail,
  type OntologyVersioning,
  type SubjectRef,
} from '../api'
import { lastSegment, NOT_STATED, PLACEHOLDERS, resourceLabel } from '../catalog/labels'
import { GoneView } from '../components/GoneView'
import { OntologyActions } from '../crud/OntologyActions'
import { useApiLoad } from '../hooks/useApiLoad'
import {
  compactIri,
  isLinkableIri,
  plural,
  prefixLabel,
  RDF_SERIALIZATIONS,
  VOCAB_PLACEHOLDERS,
} from '../vocab/labels'
import { DescriptionPanel, MetricsPanel, OntologyBreadcrumbs, OntologyHeader, VersionHistory } from '../vocab/OntologyParts'
import { conceptRouteFromUri, ontologyRoute, schemeRoute } from '../vocab/routes'
import '../styles/dataset.css'
import '../styles/vocab.css'
import '../styles/crud.css'

/** Pantalla «Ficha de ontología» (`/ontologias/:slug`, con `?version=`). */
export function OntologyPage() {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const version = searchParams.get('version')
  const loader = useCallback((signal: AbortSignal) => fetchOntology(slug, version, signal), [slug, version])
  const { state, lastData, retry } = useApiLoad(loader)
  // Tras mover la ontología se vuelve a pedir la ficha: mientras tanto se sigue mostrando la anterior.
  const shown =
    state.status === 'ok' ? state.data : state.status === 'loading' && lastData?.slug === slug ? lastData : null

  if (state.status === 'gone') {
    return (
      <GoneView
        gone={state.gone}
        note={version ? `La versión ${version} se dio de baja con la ontología.` : undefined}
      />
    )
  }

  if (!shown && (state.status === 'loading' || state.status === 'idle')) {
    return (
      <p role="status" className="state">
        Cargando ontología…
      </p>
    )
  }

  if (state.status === 'not-found') {
    return (
      <div className="dataset">
        <OntologyBreadcrumbs kind="own" current={slug} />
        <h1 className="page-title">Ontología no encontrada</h1>
        <p className="muted">
          No existe ninguna ontología{version ? ` con la versión ${version}` : ''} en esta dirección.{' '}
          <Link to="/vocabularios">Volver a Vocabularios</Link>
        </p>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="dataset">
        <OntologyBreadcrumbs kind="own" current={slug} />
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar la ontología.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      </div>
    )
  }

  if (!shown) return null
  return <OntologyView data={shown} onChanged={retry} />
}

function OntologyView({ data, onChanged }: { data: OntologyDetail; onChanged: () => void }) {
  const v = data.versioning
  const isCurrent = !v.current_version || v.version === v.current_version
  // Las descargas y la URI de una versión antigua llevan la versión; las de la actual, no.
  const shownVersion = isCurrent ? null : v.version
  const uri = isCurrent ? data.uri : v.version_iri
  const title = data.title ?? data.metadata.title ?? data.slug

  return (
    <div className="dataset">
      <OntologyBreadcrumbs kind="own" current={data.slug} />

      <OntologyActions ontology={data} onChanged={onChanged}>
        <OntologyHeader
          kind="own"
          status={data.status}
          synthetic={data.synthetic}
          versionTag={v.version ? `v${v.version}${isCurrent ? ' · actual' : ''}` : null}
          title={title}
          prefix={data.metadata.prefix}
          namespace={data.metadata.namespace}
          uri={uri}
          catalog={data.catalog}
          turtleHref={ontologyRdfUrl(data.slug, 'turtle', shownVersion)}
        />
      </OntologyActions>

      <div className="dataset__columns">
        <div className="dataset__main">
          <DescriptionPanel description={data.description} />
          <MetricsPanel
            metrics={data.metrics}
            profile={data.profile}
            consistency={data.consistency}
            documentation={data.documentation}
            hint={`calculadas en backend${v.version ? ` · v${v.version}` : ''}`}
          />
          <ImportsSection imports={data.imports} alignments={data.alignments} />
          <VersioningSection slug={data.slug} versioning={v} />
          <UsageSection uses={data.used_by_datasets} />
        </div>

        <div className="dataset__side">
          <MetadataAside data={data} version={shownVersion} />
        </div>
      </div>
    </div>
  )
}

/** Nombre de una ontología enlazada: a su IRI oficial si se puede abrir. */
function OntologyName({ title, uri }: { title: string; uri: string | null }) {
  if (uri && isLinkableIri(uri)) {
    return (
      <a href={uri} className="strong" rel="noopener noreferrer">
        {title}
      </a>
    )
  }
  return <span className="strong">{title}</span>
}

function ImportsSection({ imports, alignments }: { imports: ImportRef[]; alignments: Alignment[] }) {
  return (
    <section aria-labelledby="h-imp" className="panel">
      <div className="panel__head panel__head--wrap">
        <h2 id="h-imp" className="panel__title">
          Imports y alineamientos
        </h2>
        <span className="panel__hint mono">owl:imports · owl:equivalentClass · rdfs:subClassOf</span>
      </div>
      {imports.length === 0 && alignments.length === 0 ? (
        <p className="muted">Esta versión no declara imports ni alineamientos.</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--stack">
            <thead>
              <tr>
                <th scope="col">Ontología</th>
                <th scope="col">Relación</th>
                <th scope="col">Alcance</th>
                <th scope="col">Versión</th>
              </tr>
            </thead>
            <tbody>
              {imports.map((imp) => (
                <tr key={`import-${imp.uri}`}>
                  <th scope="row" data-label="Ontología">
                    <OntologyName title={imp.title ?? imp.uri} uri={imp.uri} />
                    {imp.prefix && <span className="cell-sub mono">{prefixLabel(imp.prefix)}</span>}
                  </th>
                  <td data-label="Relación" className="mono">
                    owl:imports
                  </td>
                  <td data-label="Alcance">{imp.known ? '' : 'Ontología no descrita en el repositorio'}</td>
                  <td data-label="Versión" className="mono">
                    {imp.version ?? VOCAB_PLACEHOLDERS.version}
                  </td>
                </tr>
              ))}
              {alignments.map((a) => (
                <tr key={`align-${a.target_ontology ?? 'desconocida'}-${a.relation}`}>
                  <th scope="row" data-label="Ontología">
                    <OntologyName title={a.title ?? a.target_ontology ?? 'Ontología no reconocida'} uri={a.target_ontology} />
                    {a.prefix && <span className="cell-sub mono">{prefixLabel(a.prefix)}</span>}
                  </th>
                  <td data-label="Relación" className="mono">
                    {compactIri(a.relation)}
                  </td>
                  <td data-label="Alcance">
                    {a.scope && <span>{a.scope}</span>}
                    <span className="cell-sub">{plural(a.count, 'axioma', 'axiomas')}</span>
                    {a.mappings.length > 0 && (
                      <details className="mappings">
                        <summary>Ver correspondencias</summary>
                        <ul className="field-list mono">
                          {a.mappings.map((mp) => (
                            <li key={`${mp.source}-${mp.target}`}>
                              {mp.source} → {mp.target}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </td>
                  <td data-label="Versión" className="mono">
                    {a.version ?? VOCAB_PLACEHOLDERS.version}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function VersioningSection({ slug, versioning: v }: { slug: string; versioning: OntologyVersioning }) {
  const shown = v.version
  return (
    <section aria-labelledby="h-ver" className="panel">
      <div className="panel__head">
        <h2 id="h-ver" className="panel__title">
          Versionado
        </h2>
        <span className="panel__hint mono">owl:versionIRI · owl:priorVersion</span>
      </div>
      <dl className="fields fields--grid">
        <div>
          <dt className="mono">owl:versionIRI</dt>
          <dd className="mono small">{v.version_iri}</dd>
        </div>
        <div>
          <dt className="mono">owl:priorVersion</dt>
          <dd>
            {v.prior_version ? (
              <Link className="mono small" to={ontologyRoute(slug, v.prior_version.version)}>
                {slug}/{v.prior_version.version ?? lastSegment(v.prior_version.version_iri)}
              </Link>
            ) : (
              'Ninguna'
            )}
          </dd>
        </div>
        <div>
          <dt className="mono">Compatibilidad</dt>
          <dd>
            {v.backward_compatible_with.length > 0
              ? `owl:backwardCompatibleWith ${v.backward_compatible_with
                  .map((r) => r.version ?? lastSegment(r.version_iri))
                  .join(', ')}`
              : 'Sin declarar'}
          </dd>
        </div>
      </dl>
      {v.history.length > 0 && (
        <VersionHistory
          rows={v.history.map((h) => {
            const label = h.version ?? lastSegment(h.version_iri)
            return {
              key: h.version_iri,
              label,
              ariaLabel: `Versión ${label}`,
              to: h.described ? ontologyRoute(slug, h.current ? null : h.version) : null,
              current: h.current,
              selected: h.version === shown,
              date: h.issued ?? PLACEHOLDERS.date,
              note: h.notes,
            }
          })}
        />
      )}
    </section>
  )
}

function UsageSection({ uses }: { uses: DatasetUse[] }) {
  return (
    <section aria-labelledby="h-uso" className="panel">
      <div className="panel__head">
        <h2 id="h-uso" className="panel__title">
          Uso en el catálogo
        </h2>
        <span className="panel__hint mono">dct:conformsTo</span>
      </div>
      {uses.length === 0 ? (
        <p className="muted">Ningún dataset del catálogo la usa todavía.</p>
      ) : (
        <ul className="link-list">
          {uses.map((u) => (
            <li key={u.uri}>
              <Link to={`/datasets/${encodeURIComponent(u.slug)}`} className="link-row">
                <span className="strong">{u.title ?? u.slug}</span>
                <span className="mono link-row__meta">
                  dcat:Dataset
                  {u.versions.length > 0 &&
                    ` · ${u.versions.map((dv) => (dv.version ? `v${dv.version}` : lastSegment(dv.uri))).join(', ')}`}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="panel__hint">Proyectos que la aplican: {PLACEHOLDERS.project}</p>
    </section>
  )
}

/** Destino de un `dct:subject`: el esquema o, si es un concepto, el concepto en el navegador. */
function subjectRoute(s: SubjectRef): string | null {
  if (s.type === 'concept') return conceptRouteFromUri(s.uri) ?? (s.scheme ? schemeRoute(s.scheme.slug, s.scheme.corp) : null)
  if (s.scheme) return schemeRoute(s.scheme.slug, s.scheme.corp)
  return null
}

function MetadataAside({ data, version }: { data: OntologyDetail; version: string | null }) {
  const m = data.metadata
  return (
    <aside aria-labelledby="h-meta" className="panel">
      <h2 id="h-meta" className="panel__title">
        Metadatos
      </h2>
      <dl className="fields">
        <div>
          <dt className="mono">vann:preferredNamespacePrefix</dt>
          <dd className="mono">{m.prefix ?? NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">vann:preferredNamespaceUri</dt>
          <dd className="mono small">{m.namespace ?? NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">dct:creator</dt>
          <dd>
            {m.creators.length > 0
              ? m.creators.map((c) => resourceLabel(c, VOCAB_PLACEHOLDERS.authors)).join(', ')
              : VOCAB_PLACEHOLDERS.authors}
          </dd>
        </div>
        {m.contributors.length > 0 && (
          <div>
            <dt className="mono">dct:contributor</dt>
            <dd>{m.contributors.map((c) => resourceLabel(c, NOT_STATED)).join(', ')}</dd>
          </div>
        )}
        <div>
          <dt className="mono">dct:publisher</dt>
          <dd>{resourceLabel(m.publisher, NOT_STATED)}</dd>
        </div>
        <div>
          <dt className="mono">dct:license</dt>
          <dd>{resourceLabel(m.license, PLACEHOLDERS.license)}</dd>
        </div>
        {m.rights && (
          <div>
            <dt className="mono">dct:rights</dt>
            <dd>{m.rights}</dd>
          </div>
        )}
        <div>
          <dt className="mono">dct:issued · dct:modified</dt>
          <dd>
            {m.issued ?? PLACEHOLDERS.date} · {m.modified ?? PLACEHOLDERS.date}
          </dd>
        </div>
        <div>
          <dt className="mono">Repositorio</dt>
          <dd className="mono small">{VOCAB_PLACEHOLDERS.repository}</dd>
        </div>
        <div>
          <dt className="mono">Serializaciones</dt>
          <dd className="pills">
            {RDF_SERIALIZATIONS.map((s) => (
              <a
                key={s.format}
                className="pill pill--brand pill--link"
                href={ontologyRdfUrl(data.slug, s.format, version)}
                download
              >
                {s.label}
              </a>
            ))}
          </dd>
        </div>
        <div>
          <dt className="mono">Vocabularios SKOS usados</dt>
          <dd className="pills">
            {data.subjects.length > 0 ? (
              data.subjects.map((s) => {
                const to = subjectRoute(s)
                const label = s.label ?? s.scheme?.label ?? s.uri
                const className = `pill ${s.scheme?.corp ? 'pill--corp' : 'pill--domain'}`
                return to ? (
                  <Link key={s.uri} to={to} className={`${className} pill--link`}>
                    {label}
                  </Link>
                ) : (
                  <span key={s.uri} className={className}>
                    {label}
                  </span>
                )
              })
            ) : (
              <span className="muted">Ninguno</span>
            )}
          </dd>
        </div>
      </dl>
    </aside>
  )
}
