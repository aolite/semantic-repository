/**
 * Iconos SVG decorativos (siempre con `aria-hidden`): el texto del enlace
 * que los acompaña ya da el nombre accesible.
 */

interface IconProps {
  size?: number
}

const common = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.6,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  'aria-hidden': true,
  focusable: false,
}

/** Logo de la marca: tres nodos unidos (prototipo, pantalla Catálogo). */
export function LogoIcon({ size = 34 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" {...common} stroke="#FFFFFF">
      <circle cx="8" cy="9" r="4" />
      <circle cx="26" cy="9" r="4" />
      <circle cx="17" cy="26" r="4" />
      <path d="M12 9h10M10 12.5l5 10M24 12.5l-5 10" />
    </svg>
  )
}

export function CatalogIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" {...common}>
      <rect x="3" y="3" width="6" height="6" rx="1" />
      <rect x="11" y="3" width="6" height="6" rx="1" />
      <rect x="3" y="11" width="6" height="6" rx="1" />
      <rect x="11" y="11" width="6" height="6" rx="1" />
    </svg>
  )
}

export function VocabularyIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" {...common}>
      <circle cx="5" cy="5" r="2" />
      <circle cx="13" cy="10" r="2" />
      <circle cx="13" cy="16" r="2" />
      <path d="M5 7v9h6M5 10h6" />
    </svg>
  )
}

export function SparqlIcon({ size = 18 }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" {...common}>
      <rect x="2.5" y="3.5" width="15" height="13" rx="2" />
      <path d="M6 8l2.5 2L6 12M10.5 12.5H14" />
    </svg>
  )
}
