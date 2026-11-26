import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from 'react'

export interface MenuItem<T extends string> {
  id: T
  label: string
}

interface PublishMenuProps<T extends string> {
  /** Texto del botón (del prototipo: «Publicar recurso»). */
  label: string
  items: MenuItem<T>[]
  onSelect: (id: T) => void
  /** Clases del botón que abre el menú. */
  className?: string
  /** Referencia al botón, para devolverle el foco al cerrar un formulario abierto desde el menú. */
  buttonRef?: RefObject<HTMLButtonElement | null>
}

/**
 * Botón con menú (patrón «menu button» de WAI-ARIA): el botón lleva
 * `aria-haspopup` y `aria-expanded`; el menú se abre con clic, Intro,
 * Espacio o las flechas; las flechas, Inicio y Fin recorren las opciones;
 * Escape lo cierra y devuelve el foco al botón; Tab o un clic fuera lo
 * cierran. El prototipo tiene el botón «Publicar recurso», pero no detalla
 * el menú: este diseño es [PROPUESTA].
 */
export function PublishMenu<T extends string>({ label, items, onSelect, className, buttonRef }: PublishMenuProps<T>) {
  const id = useId()
  const [open, setOpen] = useState(false)
  // Opción que recibe el foco al abrir (-1: la última).
  const [initial, setInitial] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const ownButton = useRef<HTMLButtonElement>(null)
  const button = buttonRef ?? ownButton
  const menu = useRef<HTMLUListElement>(null)

  function options(): HTMLButtonElement[] {
    return [...(menu.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])]
  }

  useEffect(() => {
    if (!open) return
    const all = options()
    all.at(initial === -1 ? -1 : initial)?.focus()
    function handlePointer(event: MouseEvent) {
      if (root.current && !root.current.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    return () => document.removeEventListener('mousedown', handlePointer)
  }, [open, initial])

  function openAt(index: number) {
    setInitial(index)
    setOpen(true)
  }

  function close(focusButton: boolean) {
    setOpen(false)
    if (focusButton) button.current?.focus()
  }

  function handleButtonKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      openAt(0)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      openAt(-1)
    }
  }

  function handleMenuKey(event: KeyboardEvent<HTMLUListElement>) {
    const all = options()
    const current = all.indexOf(document.activeElement as HTMLButtonElement)
    let next: number
    switch (event.key) {
      case 'ArrowDown':
        next = (current + 1) % all.length
        break
      case 'ArrowUp':
        next = (current - 1 + all.length) % all.length
        break
      case 'Home':
        next = 0
        break
      case 'End':
        next = all.length - 1
        break
      case 'Escape':
        event.preventDefault()
        event.stopPropagation()
        close(true)
        return
      case 'Tab':
        close(false)
        return
      default:
        return
    }
    event.preventDefault()
    all[next]?.focus()
  }

  return (
    <div ref={root} className="menu">
      <button
        ref={button}
        type="button"
        id={`${id}-button`}
        className={className}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? `${id}-menu` : undefined}
        onClick={() => (open ? close(false) : openAt(0))}
        onKeyDown={handleButtonKey}
      >
        {label}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          aria-hidden="true"
          focusable="false"
          className="menu__chevron"
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {open && (
        <ul ref={menu} id={`${id}-menu`} role="menu" aria-labelledby={`${id}-button`} className="menu__list" onKeyDown={handleMenuKey}>
          {items.map((item) => (
            <li key={item.id} role="none">
              <button
                type="button"
                role="menuitem"
                tabIndex={-1}
                className="menu__item"
                onClick={() => {
                  setOpen(false)
                  onSelect(item.id)
                }}
              >
                {item.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
