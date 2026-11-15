import type { DomainSlug } from '../api'
import { DOMAINS } from '../catalog/labels'

/** Etiqueta del tipo RDF del recurso (p. ej. `dcat:Dataset`). */
export function TypeTag({ children }: { children: string }) {
  return <span className="tag tag--type mono">{children}</span>
}

/** Etiqueta de dominio con los colores del prototipo. */
export function DomainTag({ slug }: { slug: DomainSlug }) {
  const domain = DOMAINS[slug]
  return (
    <span className="tag tag--domain" style={{ background: domain.tagBg, color: domain.tagFg }}>
      {domain.label}
    </span>
  )
}

/**
 * Marca «Dataset sintético» (decisión del responsable para G2). No está en el
 * prototipo: usa el estilo de las etiquetas neutras con borde discontinuo.
 */
export function SyntheticTag() {
  return <span className="tag tag--synthetic">Dataset sintético</span>
}
