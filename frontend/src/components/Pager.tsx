import { Link } from 'react-router'
import { catalogSearch } from '../catalog/urlState'

/**
 * Paginación de los datasets (no está en el prototipo). Son enlaces con la
 * página en la URL (`?pagina=`), así que se pueden abrir en otra pestaña o
 * compartir. Conserva el resto de parámetros.
 */
export function Pager({ params, page, totalPages }: { params: URLSearchParams; page: number; totalPages: number }) {
  const previous = Math.min(page - 1, totalPages)
  return (
    <nav aria-label="Paginación" className="pager">
      {page > 1 && (
        <Link to={{ search: catalogSearch(params, { page: previous }) }} className="button button--secondary" rel="prev">
          Anterior
        </Link>
      )}
      <span className="pager__status">
        Página {page} de {totalPages}
      </span>
      {page < totalPages && (
        <Link to={{ search: catalogSearch(params, { page: page + 1 }) }} className="button button--secondary" rel="next">
          Siguiente
        </Link>
      )}
    </nav>
  )
}
