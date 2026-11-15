import { Outlet, useLocation } from 'react-router'
import { ErrorBoundary } from './ErrorBoundary'
import { Sidebar } from './Sidebar'

export function Layout() {
  const { pathname } = useLocation()
  return (
    <div className="layout">
      <Sidebar />
      <main className="layout__main">
        {/* Un error de renderizado en una pantalla no deja la página en blanco; al cambiar de ruta se reinicia. */}
        <ErrorBoundary key={pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  )
}
