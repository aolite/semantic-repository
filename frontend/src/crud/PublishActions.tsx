import type { ReactNode } from 'react'
import type { CatalogSummary } from '../api'
import { usePublishActions } from './usePublishActions'

interface PublishActionsProps {
  /** Catálogos para elegir dónde se publica (los del filtro de la pantalla). */
  catalogs: CatalogSummary[]
  catalogsLoading: boolean
  /** Cabecera de la pantalla: los botones van a su derecha. */
  children: ReactNode
}

/**
 * Cabecera de la pantalla Catálogo con los botones «Importar SKOS» y
 * «Publicar recurso» a su derecha (prototipo; decisión 50 d) y, debajo, el
 * formulario que abren. La lógica está en `usePublishActions`, que también
 * usa la ficha de un catálogo con el catálogo fijado.
 */
export function PublishActions({ catalogs, catalogsLoading, children }: PublishActionsProps) {
  const { buttons, panels } = usePublishActions({ catalogs, catalogsLoading })
  return (
    <>
      <div className="crud-header">
        <div className="crud-header__text">{children}</div>
        {buttons}
      </div>
      {panels}
    </>
  )
}
