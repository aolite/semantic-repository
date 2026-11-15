import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { CatalogPage } from './pages/CatalogPage'
import { DatasetPage } from './pages/DatasetPage'
import { LoginPage } from './pages/LoginPage'
import { PlaceholderPage } from './pages/PlaceholderPage'

/** Rutas de la aplicación. El router lo aporta `main.tsx` (o la prueba). */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CatalogPage />} />
        {/* El backend redirige aquí (303) desde la URI persistente; `?version=` para versiones antiguas. */}
        <Route path="datasets/:slug" element={<DatasetPage />} />
        <Route path="vocabularios" element={<PlaceholderPage title="Vocabularios" phase={3} />} />
        <Route path="sparql" element={<PlaceholderPage title="Consulta SPARQL" phase={4} />} />
        <Route path="login" element={<LoginPage />} />
      </Route>
    </Routes>
  )
}
