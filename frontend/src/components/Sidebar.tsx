import { Link, NavLink, useNavigate } from 'react-router'
import { useAuth } from '../auth/useAuth'
import { ROLE_LABELS } from '../auth/roles'
import { getSparqlEndpointUrl } from '../config'
import { CatalogIcon, LogoIcon, SparqlIcon, VocabularyIcon } from './icons'

const NAV_LINKS = [
  { to: '/', label: 'Catálogo', Icon: CatalogIcon },
  { to: '/vocabularios', label: 'Vocabularios', Icon: VocabularyIcon },
  { to: '/sparql', label: 'Consulta SPARQL', Icon: SparqlIcon },
]

/**
 * Esquemas de conceptos por dominio, con el color del prototipo.
 * Provisional: en la fase 3 la lista vendrá de la API (los colores siguen
 * siendo del diseño).
 */
const CONCEPT_SCHEMES = [
  { label: 'Seguridad IT', color: 'var(--domain-it)' },
  { label: 'OT / ICS', color: 'var(--domain-ot)' },
  { label: 'PQC e identidad', color: 'var(--domain-pqc)' },
  { label: 'IA adversaria', color: 'var(--domain-ai)' },
]

export function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

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
        {NAV_LINKS.map(({ to, label, Icon }) => (
          <li key={to}>
            <NavLink to={to} end className="sidebar__link">
              <Icon />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>

      <section className="sidebar__section" aria-labelledby="sidebar-schemes">
        <h2 id="sidebar-schemes" className="sidebar__label">
          Esquemas de conceptos
        </h2>
        <ul className="sidebar__schemes">
          {CONCEPT_SCHEMES.map(({ label, color }) => (
            <li key={label}>
              <span className="sidebar__swatch" style={{ background: color }} aria-hidden="true" />
              {label}
            </li>
          ))}
        </ul>
      </section>

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
