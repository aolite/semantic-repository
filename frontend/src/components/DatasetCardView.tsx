import { Link } from 'react-router'
import type { DatasetCard } from '../api'
import { accessLabel, formatsLine, themeLabel } from '../catalog/labels'
import { datasetRoute } from '../crud/navigation'
import { fairWidth } from '../dataset/fair'
import { DomainTag, SyntheticTag, TypeTag } from './Tags'

/** Tarjeta de dataset del prototipo (pantallas Catálogo y ficha de catálogo). */
export function DatasetCardView({ item }: { item: DatasetCard }) {
  const access = accessLabel(item.access_rights)
  const formats = formatsLine(item.formats, item.current_version)
  const hasFair = item.fair_total !== null && item.fair_total !== undefined
  return (
    <article className="card">
      <div className="card__tags">
        <TypeTag>dcat:Dataset</TypeTag>
        {item.domain && <DomainTag slug={item.domain.slug} />}
        {item.synthetic && <SyntheticTag />}
        {access && <span className="card__access">{access}</span>}
      </div>
      <Link to={datasetRoute(item.slug)} className="card__title">
        {item.title ?? item.slug}
      </Link>
      {item.description && <p className="card__desc">{item.description}</p>}
      {item.themes.length > 0 && (
        <ul className="card__themes" aria-label="Temas">
          {item.themes.map((theme) => (
            <li key={theme.uri} className="theme-pill">
              {themeLabel(theme)}
            </li>
          ))}
        </ul>
      )}
      {(formats || hasFair) && (
        <div className="card__footer">
          {formats && <span className="mono card__formats">{formats}</span>}
          {hasFair && (
            <span className="card__fair">
              <span className="card__fair-label">FAIR {item.fair_total}</span>
              <span className="card__fair-bar" aria-hidden="true">
                <span className="card__fair-fill" style={{ width: fairWidth(item.fair_total ?? null) }} />
              </span>
            </span>
          )}
        </div>
      )}
    </article>
  )
}
