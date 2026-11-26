import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { CatalogDetailPage } from './pages/CatalogDetailPage'
import { CatalogPage } from './pages/CatalogPage'
import { CatalogsPage } from './pages/CatalogsPage'
import { DatasetPage } from './pages/DatasetPage'
import { ExternalOntologyPage } from './pages/ExternalOntologyPage'
import { LoginPage } from './pages/LoginPage'
import { OntologyPage } from './pages/OntologyPage'
import { SparqlPage } from './pages/SparqlPage'
import { SkosPage } from './pages/SkosPage'
import { VocabulariesPage } from './pages/VocabulariesPage'

/** Rutas de la aplicación. El router lo aporta `main.tsx` (o la prueba). */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<CatalogPage />} />
        {/* Catálogos (decisión 49). El backend redirige aquí (303) desde `catalogo/{slug}`. */}
        <Route path="catalogos" element={<CatalogsPage />} />
        <Route path="catalogos/:slug" element={<CatalogDetailPage />} />
        {/* El backend redirige aquí (303) desde la URI persistente; `?version=` para versiones antiguas. */}
        <Route path="datasets/:slug" element={<DatasetPage />} />
        <Route path="vocabularios" element={<VocabulariesPage />} />
        {/* Navegador SKOS (303 desde `vocab/…`), con `?concepto=`. Los corporativos van bajo `corp/`. */}
        <Route path="vocabularios/corp/:slug" element={<SkosPage corp />} />
        <Route path="vocabularios/:slug" element={<SkosPage corp={false} />} />
        {/* Ficha de ontología (303 desde `onto/…`), con `?version=`. */}
        <Route path="ontologias/:slug" element={<OntologyPage />} />
        {/* Ficha de una ontología externa (decisión 51): 303 desde `onto/externas/{slug}[/{n}]`, con `?version=`. */}
        <Route path="ontologias/externas/:slug" element={<ExternalOntologyPage />} />
        <Route path="sparql" element={<SparqlPage />} />
        <Route path="login" element={<LoginPage />} />
      </Route>
    </Routes>
  )
}
