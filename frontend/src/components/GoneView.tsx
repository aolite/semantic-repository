import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { GoneResponse } from '../api'
import { lastSegment, PLACEHOLDERS } from '../catalog/labels'
import { fairDate } from '../dataset/fair'
import { TypeTag } from './Tags'

interface GoneText {
  type: string
  heading: string
  text: string
  back: { to: string; label: string }
  /** Sección intermedia de las migas de pan. */
  section: { to: string; label: string } | null
}

const TEXTS: Record<GoneResponse['resource'], GoneText> = {
  catalog: {
    type: 'dcat:Catalog',
    heading: 'Catálogo dado de baja',
    text: 'Este catálogo se dio de baja: ya no aparece en los listados ni en las consultas SPARQL.',
    back: { to: '/catalogos', label: 'Ver los catálogos' },
    section: { to: '/catalogos', label: 'Catálogos' },
  },
  dataset: {
    type: 'dcat:Dataset',
    heading: 'Dataset dado de baja',
    text: 'Este dataset se dio de baja: ya no aparece en los listados ni en las consultas SPARQL, y sus ficheros se han eliminado.',
    back: { to: '/', label: 'Volver al catálogo' },
    section: null,
  },
  scheme: {
    type: 'skos:ConceptScheme',
    heading: 'Esquema dado de baja',
    text: 'Este esquema se dio de baja con todos sus conceptos: ya no aparece en los listados ni en las consultas SPARQL, y las URIs de sus conceptos responden que se dio de baja.',
    back: { to: '/vocabularios', label: 'Volver a Vocabularios' },
    section: { to: '/vocabularios', label: 'Vocabularios' },
  },
  ontology: {
    type: 'owl:Ontology',
    heading: 'Ontología dada de baja',
    text: 'Esta ontología se dio de baja con todas sus versiones: ya no aparece en los listados ni en las consultas SPARQL, y las URIs de sus versiones responden que se dio de baja.',
    back: { to: '/vocabularios', label: 'Volver a Vocabularios' },
    section: { to: '/vocabularios', label: 'Vocabularios' },
  },
}

/**
 * Ficha mínima de un recurso dado de baja (410 Gone): catálogo o dataset
 * (decisión 49), esquema SKOS u ontología (decisión 50). Título, URI y fecha
 * de baja de la lápida, en lugar de un error genérico. Sin fecha se muestra
 * el placeholder `[FECHA]`. Los conceptos y las versiones de ontología
 * responden 410 por arrastre con la lápida de su esquema u ontología:
 * `note` explica qué se pidió.
 */
export function GoneView({ gone, note }: { gone: GoneResponse; note?: ReactNode }) {
  const text = TEXTS[gone.resource] ?? TEXTS.dataset
  const title = gone.title ?? lastSegment(gone.uri)
  const withdrawnLabel = gone.resource === 'ontology' ? 'Dada de baja' : 'Dado de baja'
  return (
    <div className="dataset">
      <nav aria-label="Migas de pan" className="breadcrumbs">
        <Link to="/">Catálogo</Link>
        {text.section && (
          <>
            <span aria-hidden="true">/</span>
            <Link to={text.section.to}>{text.section.label}</Link>
          </>
        )}
        <span aria-hidden="true">/</span>
        <span aria-current="page">{withdrawnLabel}</span>
      </nav>

      <header className="dataset__header">
        <div className="dataset__tags">
          <TypeTag>{text.type}</TypeTag>
          <span className="tag tag--withdrawn">{withdrawnLabel}</span>
        </div>
        <h1 className="page-title dataset__title">{title}</h1>
        <p className="mono dataset__uri">{gone.uri}</p>
      </header>

      <section aria-labelledby="h-baja" className="panel gone">
        <h2 id="h-baja" className="panel__title">
          {text.heading}
        </h2>
        <dl className="fields fields--grid">
          <div>
            <dt className="mono">prov:invalidatedAtTime</dt>
            <dd className="strong">
              {gone.withdrawn_at ? (
                <time dateTime={gone.withdrawn_at}>{fairDate(gone.withdrawn_at)}</time>
              ) : (
                PLACEHOLDERS.date
              )}
            </dd>
          </div>
          <div>
            <dt className="mono">adms:status</dt>
            <dd>Withdrawn</dd>
          </div>
        </dl>
        {note && <p className="panel__text">{note}</p>}
        <p className="panel__text">{text.text}</p>
        <p>
          <Link to={text.back.to}>{text.back.label}</Link>
        </p>
      </section>
    </div>
  )
}
