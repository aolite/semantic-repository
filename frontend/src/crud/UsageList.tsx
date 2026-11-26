import { Link } from 'react-router'
import type { UsageRef } from '../api'
import { compactIri } from '../vocab/labels'
import { resourceRouteFromUri } from '../vocab/routes'
import { shortUri } from './publish'

/** Máximo de recursos que se listan en un error (el resto se resume). */
const MAX_ITEMS = 20

const USAGE_RESOURCE: Record<UsageRef['resource'], string> = {
  dataset: 'Versión de dataset',
  ontology: 'Versión de ontología',
  scheme: 'Concepto de otro esquema',
}

function UriLink({ uri }: { uri: string }) {
  const to = resourceRouteFromUri(uri)
  return to ? (
    <Link to={to} className="mono">
      {shortUri(uri)}
    </Link>
  ) : (
    <span className="mono">{shortUri(uri)}</span>
  )
}

function Rest({ total }: { total: number }) {
  return total > MAX_ITEMS ? <li>Y {total - MAX_ITEMS} más.</li> : null
}

/** Lista de URIs de recursos (409 `catalog_not_empty`), enlazadas a su ficha cuando siguen el patrón. */
export function ResourceList({ uris, label }: { uris: string[]; label: string }) {
  if (uris.length === 0) return null
  return (
    <ul className="form__issues" aria-label={label}>
      {uris.slice(0, MAX_ITEMS).map((uri) => (
        <li key={uri}>
          <UriLink uri={uri} />
        </li>
      ))}
      <Rest total={uris.length} />
    </ul>
  )
}

/**
 * Usos que impiden dar de baja un esquema o una ontología (409 `in_use`,
 * decisión 50): quién lo usa, con qué propiedad y qué usa.
 */
export function UsageList({ usedBy }: { usedBy: UsageRef[] }) {
  if (usedBy.length === 0) return null
  return (
    <ul className="form__issues" aria-label="Recursos que lo usan">
      {usedBy.slice(0, MAX_ITEMS).map((u, i) => (
        <li key={`${u.uri}-${u.via ?? ''}-${u.target}-${i}`}>
          {USAGE_RESOURCE[u.resource] ?? 'Recurso'} <UriLink uri={u.uri} />
          {' · '}
          <span className="mono">{u.via ? compactIri(u.via) : 'usa el término'}</span>{' → '}
          <span className="mono">{shortUri(u.target)}</span>
        </li>
      ))}
      <Rest total={usedBy.length} />
    </ul>
  )
}
