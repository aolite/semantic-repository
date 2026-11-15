import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { ConceptNode } from '../api'
import { normalizeText } from '../vocab/labels'

/**
 * Árbol de conceptos de un esquema con el patrón «tree» de WAI-ARIA:
 * `role="tree"`, `treeitem` con `aria-expanded`, `aria-selected` y
 * `aria-level`, foco itinerante (un solo elemento con `tabIndex=0`) y
 * teclado: flechas arriba y abajo, derecha (expandir o bajar al primer hijo),
 * izquierda (contraer o subir al padre), Inicio, Fin, e Intro o Espacio para
 * seleccionar el concepto.
 *
 * Un concepto puede aparecer bajo varios padres (polijerarquía): cada
 * aparición se identifica por su ruta de URIs.
 */

interface ConceptTreeProps {
  nodes: ConceptNode[]
  /** Slug del concepto seleccionado. */
  selected: string | null
  onSelect: (slug: string) => void
  /** Etiqueta accesible del árbol. */
  label: string
}

interface VisibleItem {
  key: string
  node: ConceptNode
  level: number
  parentKey: string | null
  hasChildren: boolean
}

const SEP = '\u0000'

function nodeLabel(node: ConceptNode): string {
  return node.label ?? node.slug ?? node.uri
}

/** Poda el árbol: quedan los nodos que coinciden con el filtro y sus antepasados. */
function filterNodes(nodes: ConceptNode[], needle: string): ConceptNode[] {
  if (!needle) return nodes
  const result: ConceptNode[] = []
  for (const node of nodes) {
    const children = filterNodes(node.children, needle)
    const matches = normalizeText(`${node.label ?? ''} ${node.slug ?? ''}`).includes(needle)
    if (matches || children.length > 0) result.push({ ...node, children: matches ? node.children : children })
  }
  return result
}

/** Claves de las apariciones de `slug` y de sus antepasados. */
function ancestorKeys(nodes: ConceptNode[], slug: string | null, parent: string | null = null, acc = new Set<string>()) {
  if (!slug) return acc
  for (const node of nodes) {
    const key = parent ? `${parent}${SEP}${node.uri}` : node.uri
    if (node.slug === slug && parent) {
      const parts = parent.split(SEP)
      parts.forEach((_, i) => acc.add(parts.slice(0, i + 1).join(SEP)))
    }
    ancestorKeys(node.children, slug, key, acc)
  }
  return acc
}

function flatten(
  nodes: ConceptNode[],
  isExpanded: (key: string) => boolean,
  level = 1,
  parentKey: string | null = null,
  out: VisibleItem[] = [],
): VisibleItem[] {
  for (const node of nodes) {
    const key = parentKey ? `${parentKey}${SEP}${node.uri}` : node.uri
    const hasChildren = node.children.length > 0
    out.push({ key, node, level, parentKey, hasChildren })
    if (hasChildren && isExpanded(key)) flatten(node.children, isExpanded, level + 1, key, out)
  }
  return out
}

export function ConceptTree({ nodes, selected, onSelect, label }: ConceptTreeProps) {
  const [filter, setFilter] = useState('')
  // Por defecto se ven los conceptos de primer nivel abiertos (como el prototipo)
  // y la rama del concepto seleccionado.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set([...nodes.map((n) => n.uri), ...ancestorKeys(nodes, selected)]),
  )
  const [prevSelected, setPrevSelected] = useState(selected)
  const [focusedKey, setFocusedKey] = useState<string | null>(null)
  const itemRefs = useRef(new Map<string, HTMLLIElement>())
  const pendingFocus = useRef(false)

  // Si la selección cambia desde fuera (un enlace broader o related), se abre su rama.
  if (prevSelected !== selected) {
    setPrevSelected(selected)
    const keys = ancestorKeys(nodes, selected)
    if ([...keys].some((k) => !expanded.has(k))) setExpanded(new Set([...expanded, ...keys]))
  }

  const needle = normalizeText(filter.trim())
  const filtered = useMemo(() => filterNodes(nodes, needle), [nodes, needle])
  // Al filtrar se abren todas las ramas que quedan.
  const visible = useMemo(
    () => flatten(filtered, needle ? () => true : (key) => expanded.has(key)),
    [filtered, needle, expanded],
  )
  const visibleByKey = useMemo(() => new Map(visible.map((item) => [item.key, item])), [visible])

  const tabStop =
    (focusedKey !== null && visibleByKey.has(focusedKey) ? focusedKey : undefined) ??
    visible.find((item) => item.node.slug !== null && item.node.slug === selected)?.key ??
    visible[0]?.key ??
    null

  useEffect(() => {
    if (!pendingFocus.current || !tabStop) return
    pendingFocus.current = false
    itemRefs.current.get(tabStop)?.focus()
  }, [tabStop])

  function moveFocus(key: string) {
    pendingFocus.current = true
    setFocusedKey(key)
  }

  function toggle(key: string, open?: boolean) {
    setExpanded((prev) => {
      const next = new Set(prev)
      const willOpen = open ?? !next.has(key)
      if (willOpen) next.add(key)
      else next.delete(key)
      return next
    })
  }

  function select(item: VisibleItem) {
    setFocusedKey(item.key)
    if (item.node.slug) onSelect(item.node.slug)
  }

  const isOpen = (item: VisibleItem) => item.hasChildren && (needle !== '' || expanded.has(item.key))

  function handleKeyDown(event: KeyboardEvent<HTMLUListElement>) {
    const index = visible.findIndex((item) => item.key === tabStop)
    if (index === -1) return
    const item = visible[index]
    let handled = true
    switch (event.key) {
      case 'ArrowDown':
        if (index < visible.length - 1) moveFocus(visible[index + 1].key)
        break
      case 'ArrowUp':
        if (index > 0) moveFocus(visible[index - 1].key)
        break
      case 'ArrowRight':
        if (item.hasChildren && !isOpen(item)) toggle(item.key, true)
        else if (item.hasChildren) moveFocus(visible[index + 1].key)
        break
      case 'ArrowLeft':
        if (isOpen(item) && !needle) toggle(item.key, false)
        else if (item.parentKey) moveFocus(item.parentKey)
        break
      case 'Home':
        moveFocus(visible[0].key)
        break
      case 'End':
        moveFocus(visible[visible.length - 1].key)
        break
      case 'Enter':
      case ' ':
        select(item)
        break
      default:
        handled = false
    }
    if (handled) {
      event.preventDefault()
      event.stopPropagation()
    }
  }

  function renderLevel(levelNodes: ConceptNode[], level: number, parentKey: string | null) {
    return levelNodes.map((node) => {
      const key = parentKey ? `${parentKey}${SEP}${node.uri}` : node.uri
      const item = visibleByKey.get(key)
      if (!item) return null
      const open = isOpen(item)
      const isSelected = node.slug !== null && node.slug === selected
      return (
        <li
          key={key}
          ref={(el) => {
            if (el) itemRefs.current.set(key, el)
            else itemRefs.current.delete(key)
          }}
          role="treeitem"
          aria-level={level}
          aria-expanded={item.hasChildren ? open : undefined}
          aria-selected={isSelected}
          aria-label={nodeLabel(node)}
          tabIndex={key === tabStop ? 0 : -1}
          className="tree__item"
          onFocus={(e) => {
            if (e.target === e.currentTarget) setFocusedKey(key)
          }}
        >
          <div
            className={`tree__row${isSelected ? ' tree__row--selected' : ''}`}
            style={{ paddingLeft: `${(level - 1) * 22}px` }}
            onClick={() => select(item)}
          >
            {item.hasChildren ? (
              <span
                className={`tree__toggle${open ? ' tree__toggle--open' : ''}`}
                aria-hidden="true"
                onClick={(e) => {
                  e.stopPropagation()
                  setFocusedKey(key)
                  if (!needle) toggle(key)
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" focusable="false">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </span>
            ) : (
              <span className="tree__spacer" aria-hidden="true" />
            )}
            <span className={item.hasChildren && level === 1 ? 'tree__label tree__label--group' : 'tree__label'}>
              {nodeLabel(node)}
            </span>
          </div>
          {open && (
            <ul role="group" className="tree__group">
              {renderLevel(node.children, level + 1, key)}
            </ul>
          )}
        </li>
      )
    })
  }

  return (
    <>
      <label htmlFor="filtro-conceptos" className="catalog__search-label">
        Filtrar conceptos
      </label>
      <input
        id="filtro-conceptos"
        type="search"
        className="input"
        placeholder="prefLabel o altLabel"
        maxLength={200}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      {visible.length > 0 ? (
        <ul role="tree" aria-label={label} className="tree" onKeyDown={handleKeyDown}>
          {renderLevel(filtered, 1, null)}
        </ul>
      ) : (
        <p className="muted">{nodes.length === 0 ? 'Este esquema no tiene conceptos cargados todavía.' : 'Ningún concepto coincide con el filtro.'}</p>
      )}
    </>
  )
}
