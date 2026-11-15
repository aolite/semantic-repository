import type { DomainSlug, SchemeKind, VocabularyKind, VocabularyStatus } from '../api'
import { domainStyle } from '../catalog/labels'
import { kindStyle, statusStyle } from '../vocab/labels'

/** Etiqueta del tipo RDF del recurso (p. ej. `dcat:Dataset`). */
export function TypeTag({ children }: { children: string }) {
  return <span className="tag tag--type mono">{children}</span>
}

/** Etiqueta de dominio con los colores del prototipo (un slug desconocido se muestra tal cual). */
export function DomainTag({ slug }: { slug: DomainSlug }) {
  const domain = domainStyle(slug)
  return (
    <span className="tag tag--domain" style={{ background: domain.tagBg, color: domain.tagFg }}>
      {domain.label}
    </span>
  )
}

/**
 * Marca de contenido sintético (decisión del responsable). No está en el
 * prototipo: usa el estilo de las etiquetas neutras con borde discontinuo.
 * En datasets dice «Dataset sintético»; en ontologías y esquemas, «Sintético».
 */
export function SyntheticTag({ label = 'Dataset sintético' }: { label?: string }) {
  return <span className="tag tag--synthetic">{label}</span>
}

/**
 * Tipo de vocabulario («Ontología propia», «SKOS de dominio»…) con los colores
 * del prototipo; «Esquema auxiliar» con estilo neutro. Un valor desconocido
 * se muestra tal cual.
 */
export function KindTag({ kind }: { kind: VocabularyKind | SchemeKind }) {
  const style = kindStyle(kind)
  return (
    <span className="tag" style={{ background: style.tagBg, color: style.tagFg }}>
      {style.label}
    </span>
  )
}

/** Estado: Publicada, Borrador o Referenciada. */
export function StatusTag({ status, pill = false }: { status: VocabularyStatus; pill?: boolean }) {
  const style = statusStyle(status)
  return <span className={`tag ${pill ? 'tag--pill ' : ''}${style.className}`}>{style.label}</span>
}
