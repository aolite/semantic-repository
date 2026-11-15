import { Link } from 'react-router'
import type { VocabularyCard } from '../api'
import { metricsLine, prefixLabel, versionLabel } from '../vocab/labels'
import { vocabularyHref } from '../vocab/routes'
import { DomainTag, KindTag, StatusTag, SyntheticTag, TypeTag } from './Tags'

/**
 * Tarjeta de una ontología o un esquema SKOS (pantalla Vocabularios y
 * ontologías). La usa también el Catálogo con el mismo estilo que las de
 * datasets.
 */
export function VocabularyCardView({ item }: { item: VocabularyCard }) {
  const { href, external } = vocabularyHref(item)
  const title = item.title ?? item.prefix ?? item.uri
  const prefix = prefixLabel(item.prefix)
  return (
    <article className="card">
      <div className="card__tags">
        <TypeTag>{item.rdf_type}</TypeTag>
        <KindTag kind={item.kind} />
        {item.domain && <DomainTag slug={item.domain.slug} />}
        {item.synthetic && <SyntheticTag label="Sintético" />}
        <span className="card__status">
          <StatusTag status={item.status} pill />
        </span>
      </div>
      {external ? (
        <a href={href} className="card__title" rel="noopener noreferrer">
          {title} <span aria-hidden="true">↗</span>{' '}
          <span className="visually-hidden">(IRI oficial, sitio externo)</span>
        </a>
      ) : (
        <Link to={href} className="card__title">
          {title}
        </Link>
      )}
      {(prefix || item.namespace) && (
        <span className="mono card__ns">
          {prefix && <span className="card__prefix">{prefix}</span>} {item.namespace}
        </span>
      )}
      {item.description && <p className="card__desc">{item.description}</p>}
      <div className="card__footer mono card__formats">
        <span>{metricsLine(item)}</span>
        <span>{versionLabel(item.version)}</span>
      </div>
    </article>
  )
}
