/** Aviso que viaja en el `state` de la navegación (ver `components/Notice.tsx`). */
export interface NoticeState {
  notice: string
}

export function noticeState(notice: string): NoticeState {
  return { notice }
}

export function noticeFromState(state: unknown): string | null {
  if (state && typeof state === 'object' && 'notice' in state && typeof state.notice === 'string') {
    return state.notice
  }
  return null
}

/** Ruta del frontend de la ficha de un dataset. */
export function datasetRoute(slug: string): string {
  return `/datasets/${encodeURIComponent(slug)}`
}

/** Ruta del frontend de la ficha de un catálogo (destino del 303 de `catalogo/{slug}`). */
export function catalogRoute(slug: string): string {
  return `/catalogos/${encodeURIComponent(slug)}`
}
