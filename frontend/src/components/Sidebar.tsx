import { Link, NavLink, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { ROLE_LABELS } from '../auth/roles'
import { DOMAINS, DOMAIN_SLUGS } from '../catalog/labels'
import { getSparqlEndpointUrl } from '../config'
import { KIND_ORDER, KINDS } from '../vocab/labels'
import { schemeRoute } from '../vocab/routes'
import { CatalogIcon, LogoIcon, SparqlIcon, VocabularyIcon } from './icons'

/** Prefijos de las pantallas de vocabularios (navegador SKOS y ficha de ontología). */
const VOCAB_SECTION = ['/vocabularios/', '/ontologias/']

const NAV_LINKS: { to: string; label: string; Icon: typeof CatalogIcon; section?: string[] }[] = [
  { to: '/', label: 'Catálogo', Icon: CatalogIcon, section: ['/datasets/', '/catalogos'] },
  { to: '/vocabularios', label: 'Vocabularios', Icon: VocabularyIcon, section: VOCAB_SECTION },
  { to: '/sparql', label: 'Consulta SPARQL', Icon: SparqlIcon },
]

/**
 * Esquemas de conceptos por dominio, con el nombre y el color del prototipo.
 * Cada uno enlaza al esquema de dominio con su mismo slug (`vocab/it`,
 * `vocab/ot`, `vocab/pqc`, `vocab/ia`, según `semantic/uris.md`).
 */
const CONCEPT_SCHEMES = DOMAIN_SLUGS.map((slug) => ({
  slug,
  label: DOMAINS[slug].label,
  color: DOMAINS[slug].swatch,
}))

export function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  // En las pantallas de vocabularios la navegación muestra «Tipos de vocabulario», como el prototipo.
  const inVocabSection = pathname === '/vocabularios' || VOCAB_SECTION.some((prefix) => pathname.startsWith(prefix))

  function handleLogout() {
    logout()
    navigate('/')
  }

  return (
    <nav aria-label="Principal" className="sidebar">
      <div className="sidebar__brand">
        <LogoIcon />
        <div>
          <p className="sidebar__title">Repositorio semántico</p>
          <p className="sidebar__subtitle">Eurecat · Unidad IT&amp;OT Security</p>
        </div>
      </div>

      <ul className="sidebar__links">
        {NAV_LINKS.map(({ to, label, Icon, section }) => {
          // Dentro de la sección (p. ej. una ficha de dataset) el enlace se marca
          // como activo, como en el prototipo, con aria-current="true".
          const inSection = section?.some((prefix) => pathname.startsWith(prefix)) ?? false
          return (
            <li key={to}>
              {inSection ? (
                <Link to={to} className="sidebar__link" aria-current="true">
                  <Icon />
                  <span>{label}</span>
                </Link>
              ) : (
                <NavLink to={to} end className="sidebar__link">
                  <Icon />
                  <span>{label}</span>
                </NavLink>
              )}
            </li>
          )
        })}
      </ul>

      {inVocabSection ? (
        <section className="sidebar__section" aria-labelledby="sidebar-kinds">
          <h2 id="sidebar-kinds" className="sidebar__label">
            Tipos de vocabulario
          </h2>
          <ul className="sidebar__schemes">
            {KIND_ORDER.map((kind) => (
              <li key={kind} className="sidebar__scheme-item">
                <span className="sidebar__swatch" style={{ background: KINDS[kind].swatch }} aria-hidden="true" />
                {KINDS[kind].short}
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <section className="sidebar__section" aria-labelledby="sidebar-schemes">
          <h2 id="sidebar-schemes" className="sidebar__label">
            Esquemas de conceptos
          </h2>
          <ul className="sidebar__schemes">
            {CONCEPT_SCHEMES.map(({ slug, label, color }) => (
              <li key={slug}>
                <Link to={schemeRoute(slug, false)} className="sidebar__scheme-link">
                  <span className="sidebar__swatch" style={{ background: color }} aria-hidden="true" />
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="sidebar__section" aria-labelledby="sidebar-session">
        <h2 id="sidebar-session" className="sidebar__label">
          Sesión
        </h2>
        {user ? (
          <div className="sidebar__session">
            <p className="sidebar__user">
              <span className="sidebar__username">{user.username}</span>
              <span className="sidebar__role">{ROLE_LABELS[user.role] ?? user.role}</span>
            </p>
            <button type="button" className="button button--ghost" onClick={handleLogout}>
              Cerrar sesión
            </button>
          </div>
        ) : (
          <Link to="/login" className="button button--ghost">
            Iniciar sesión
          </Link>
        )}
      </section>

      <footer className="sidebar__footer">
        <p>DCAT-AP 3 · SKOS · PROV-O</p>
        <p className="mono sidebar__endpoint">{getSparqlEndpointUrl()}</p>
      </footer>
    </nav>
  )
}
