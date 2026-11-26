import { useCallback } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { externalOntologyRdfUrl, fetchExternalOntology, type ExternalOntologyDetail, type ExternalVersionRead } from '../api'
import { NOT_STATED, PLACEHOLDERS } from '../catalog/labels'
import { GoneView } from '../components/GoneView'
import { ExternalOntologyActions } from '../crud/ExternalOntologyActions'
import { useApiLoad } from '../hooks/useApiLoad'
import { formatDate, RDF_SERIALIZATIONS } from '../vocab/labels'
import { DescriptionPanel, MetricsPanel, OntologyBreadcrumbs, OntologyHeader, VersionHistory } from '../vocab/OntologyParts'
import { externalOntologyRoute } from '../vocab/routes'
import '../styles/dataset.css'
import '../styles/vocab.css'
import '../styles/crud.css'

/**
 * Ficha de una ontología externa (`/ontologias/externas/:slug`, con
 * `?version={n}`; destino del 303 de `onto/externas/…`, decisión 51). El
 * prototipo no la dibuja: reutiliza las piezas de la «Ficha de ontología».
 */
export function ExternalOntologyPage() {
  const { slug = '' } = useParams()
  const [searchParams] = useSearchParams()
  const version = searchParams.get('version')
  const loader = useCallback((signal: AbortSignal) => fetchExternalOntology(slug, signal), [slug])
  const { state, lastData, retry } = useApiLoad(loader)
  // Tras sustituirla se vuelve a pedir la ficha: mientras tanto se sigue mostrando la anterior.
  const shown =
    state.status === 'ok' ? state.data : state.status === 'loading' && lastData?.slug === slug ? lastData : null

  if (state.status === 'gone') return <GoneView gone={state.gone} />

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
        <OntologyBreadcrumbs kind="external" current={slug} />
        <h1 className="page-title">Ontología no encontrada</h1>
        <p className="muted">
          No existe ninguna ontología externa en esta dirección. <Link to="/vocabularios">Volver a Vocabularios</Link>
        </p>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="dataset">
        <OntologyBreadcrumbs kind="external" current={slug} />
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
  return <ExternalOntologyView data={shown} version={version} onChanged={retry} />
}

/** «v3.2.1» (versión del publicador) o, si no la tiene, «Versión 2» [PROPUESTA]. */
function versionName(v: ExternalVersionRead): string {
  return v.version_info ? `v${v.version_info}` : `Versión ${v.number}`
}

/** RDF de una versión: la actual sin `version` (su URL no cambia), las anteriores con su número. */
function rdfUrl(slug: string, v: ExternalVersionRead, format: Parameters<typeof externalOntologyRdfUrl>[1]): string {
  return externalOntologyRdfUrl(slug, format, v.current ? null : v.number)
}

function ExternalOntologyView({
  data,
  version,
  onChanged,
}: {
  data: ExternalOntologyDetail
  version: string | null
  onChanged: () => void
}) {
  const title = data.title ?? data.prefix ?? data.slug
  const breadcrumb = data.prefix ?? data.slug
  const selected = version ? (data.versions.find((v) => String(v.number) === version) ?? null) : data.current_version

  if (version && !selected) {
    return (
      <div className="dataset">
        <OntologyBreadcrumbs kind="external" current={breadcrumb} />
        <h1 className="page-title">Versión no encontrada</h1>
        <p className="muted">
          «{title}» no tiene la versión {version}.{' '}
          <Link to={externalOntologyRoute(data.slug)}>Ver la ficha de la ontología</Link>
        </p>
      </div>
    )
  }

  return (
    <div className="dataset">
      <OntologyBreadcrumbs kind="external" current={breadcrumb} />

      <ExternalOntologyActions ontology={data} onChanged={onChanged}>
        <OntologyHeader
          kind="external"
          status={data.status}
          versionTag={selected ? `${versionName(selected)}${selected.current ? ' · actual' : ''}` : null}
          title={title}
          prefix={data.prefix}
          namespace={data.namespace}
          uri={data.uri}
          turtleHref={selected ? rdfUrl(data.slug, selected, 'turtle') : null}
        />
      </ExternalOntologyActions>

      <div className="dataset__columns">
        <div className="dataset__main">
          <DescriptionPanel description={data.description} />
          <MetricsPanel
            metrics={selected?.metrics ?? null}
            profile={selected?.profile ?? null}
            consistency={selected?.consistency ?? null}
            documentation={selected?.documentation ?? null}
            hint={selected ? `calculadas en backend · versión ${selected.number}` : ''}
            empty={
              selected ? undefined : (
                <p className="muted">
                  Esta ontología externa todavía no se ha sustituido nunca: solo se describe por referencia y no tiene
                  métricas. Se calculan al subir su fichero completo.
                </p>
              )
            }
          />
          <VersioningSection data={data} selected={selected} />
        </div>

        <div className="dataset__side">
          <MetadataAside data={data} selected={selected} />
        </div>
      </div>
    </div>
  )
}

function VersioningSection({ data, selected }: { data: ExternalOntologyDetail; selected: ExternalVersionRead | null }) {
  return (
    <section aria-labelledby="h-ver" className="panel">
      <div className="panel__head">
        <h2 id="h-ver" className="panel__title">
          Versionado
        </h2>
        <span className="panel__hint mono">dcat:hasVersion · dcat:hasCurrentVersion</span>
      </div>
      {data.versions.length === 0 ? (
        <p className="muted">
          Todavía no tiene versiones. Cada sustitución genera una versión nueva y las anteriores no cambian.
        </p>
      ) : (
        <VersionHistory
          rows={data.versions.map((v) => ({
            key: v.uri,
            label: v.version_info ? `${v.number} · ${v.version_info}` : String(v.number),
            to: externalOntologyRoute(data.slug, v.current ? null : v.number),
            current: v.current,
            selected: selected?.number === v.number,
            date: formatDate(v.generated_at) ?? PLACEHOLDERS.date,
            note: v.notes,
            download: {
              href: rdfUrl(data.slug, v, 'turtle'),
              label: 'Descargar RDF',
              hiddenSuffix: `de la versión ${v.number} (Turtle)`,
            },
          }))}
        />
      )}
    </section>
  )
}

/** Metadatos de la referencia y de la versión que se muestra [PROPUESTA: el prototipo no dibuja esta ficha]. */
function MetadataAside({ data, selected }: { data: ExternalOntologyDetail; selected: ExternalVersionRead | null }) {
  return (
    <aside aria-labelledby="h-meta" className="panel">
      <h2 id="h-meta" className="panel__title">
        Metadatos
      </h2>
      <dl className="fields">
        <div>
          <dt className="mono">vann:preferredNamespacePrefix</dt>
          <dd className="mono">{data.prefix ?? NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">vann:preferredNamespaceUri</dt>
          <dd className="mono small">{data.namespace ?? NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">dct:publisher</dt>
          <dd>{data.publisher ?? NOT_STATED}</dd>
        </div>
        <div>
          <dt className="mono">owl:versionInfo</dt>
          <dd className="mono">{(selected ? selected.version_info : data.version) ?? NOT_STATED}</dd>
        </div>
        {selected && (
          <>
            <div>
              <dt className="mono">URI de la versión</dt>
              <dd className="mono small">{selected.uri}</dd>
            </div>
            <div>
              <dt className="mono">Serializaciones</dt>
              <dd className="pills">
                {RDF_SERIALIZATIONS.map((s) => (
                  <a key={s.format} className="pill pill--brand pill--link" href={rdfUrl(data.slug, selected, s.format)} download>
                    {s.label}
                  </a>
                ))}
              </dd>
            </div>
          </>
        )}
      </dl>
    </aside>
  )
}
