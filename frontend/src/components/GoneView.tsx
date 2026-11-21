import { Link } from 'react-router'
import type { GoneResponse } from '../api'
import { lastSegment, PLACEHOLDERS } from '../catalog/labels'
import { fairDate } from '../dataset/fair'
import { TypeTag } from './Tags'

/**
 * Ficha mínima de un catálogo o un dataset dado de baja (410 Gone, decisión
 * 49): título, URI y fecha de baja de la lápida, en lugar de un error
 * genérico. Sin fecha se muestra el placeholder `[FECHA]`.
 */
export function GoneView({ gone }: { gone: GoneResponse }) {
  const isCatalog = gone.resource === 'catalog'
  const title = gone.title ?? lastSegment(gone.uri)
  return (
    <div className="dataset">
      <nav aria-label="Migas de pan" className="breadcrumbs">
        <Link to="/">Catálogo</Link>
        {isCatalog && (
          <>
            <span aria-hidden="true">/</span>
            <Link to="/catalogos">Catálogos</Link>
          </>
        )}
        <span aria-hidden="true">/</span>
        <span aria-current="page">Dado de baja</span>
      </nav>

      <header className="dataset__header">
        <div className="dataset__tags">
          <TypeTag>{isCatalog ? 'dcat:Catalog' : 'dcat:Dataset'}</TypeTag>
          <span className="tag tag--withdrawn">Dado de baja</span>
        </div>
        <h1 className="page-title dataset__title">{title}</h1>
        <p className="mono dataset__uri">{gone.uri}</p>
      </header>

      <section aria-labelledby="h-baja" className="panel gone">
        <h2 id="h-baja" className="panel__title">
          {isCatalog ? 'Catálogo dado de baja' : 'Dataset dado de baja'}
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
        <p className="panel__text">
          {isCatalog
            ? 'Este catálogo se dio de baja: ya no aparece en los listados ni en las consultas SPARQL.'
            : 'Este dataset se dio de baja: ya no aparece en los listados ni en las consultas SPARQL, y sus ficheros se han eliminado.'}
        </p>
        <p>
          <Link to={isCatalog ? '/catalogos' : '/'}>{isCatalog ? 'Ver los catálogos' : 'Volver al catálogo'}</Link>
        </p>
      </section>
    </div>
  )
}
