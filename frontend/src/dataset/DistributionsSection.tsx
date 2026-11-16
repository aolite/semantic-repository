import { useState } from 'react'
import { Link, useLocation } from 'react-router'
import { ApiError, apiHref, requestDownloadLink, type DistributionRead } from '../api'
import { useAuth } from '../auth/useAuth'
import { accessLabel, lastSegment, NOT_STATED } from '../catalog/labels'
import { startDownload } from '../lib/startDownload'
import { DOWNLOAD_TEXT } from './download'

interface SectionProps {
  slug: string
  /** `dcat:version` de la versión mostrada (hace falta para pedir el enlace firmado). */
  version: string | null
  distributions: DistributionRead[]
}

/**
 * Distribuciones de la versión con su acción según `download` (decisión 40):
 * «Descargar» (`open`, o `authenticated` con sesión), «Iniciar sesión para
 * descargar» (`authenticated` sin sesión) o el texto de solo metadatos.
 * El `id` permite la redirección `…#distribuciones` del backend.
 */
export function DistributionsSection({ slug, version, distributions }: SectionProps) {
  return (
    <section id="distribuciones" aria-labelledby="h-dist" className="panel">
      <div className="panel__head">
        <h2 id="h-dist" className="panel__title">
          Distribuciones
        </h2>
        <span className="panel__hint mono">dcat:distribution</span>
      </div>
      {distributions.length === 0 ? (
        <p className="muted">Esta versión no declara distribuciones.</p>
      ) : (
        <div className="table-wrap">
          <table className="table table--stack">
            <thead>
              <tr>
                <th scope="col">Distribución</th>
                <th scope="col">dcat:mediaType</th>
                <th scope="col">Acceso</th>
                <th scope="col" className="table__action">
                  <span className="visually-hidden">Acción</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {distributions.map((d) => {
                const name = d.title ?? lastSegment(d.uri)
                return (
                  <tr key={d.uri}>
                    <th scope="row" data-label="Distribución">
                      {name}
                    </th>
                    <td data-label="dcat:mediaType" className="mono">
                      {d.media_type ?? NOT_STATED}
                    </td>
                    <td data-label="Acceso">{accessLabel(d.access_rights) ?? NOT_STATED}</td>
                    <td className="table__action">
                      <DistributionAction distribution={d} name={name} slug={slug} version={version} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

interface ActionProps {
  distribution: DistributionRead
  name: string
  slug: string
  version: string | null
}

function DistributionAction({ distribution: d, name, slug, version }: ActionProps) {
  const { token } = useAuth()
  const location = useLocation()

  if (d.download === 'open' && d.download_url) {
    return (
      <a href={apiHref(d.download_url)} className="action-link" aria-label={`Descargar ${name}`}>
        Descargar
      </a>
    )
  }

  if (d.download === 'authenticated' && version) {
    if (!token) {
      // El login vuelve a esta ficha (misma versión) al terminar.
      return (
        <Link
          to="/login"
          state={{ from: `${location.pathname}${location.search}` }}
          className="action-link"
          aria-label={`Iniciar sesión para descargar ${name}`}
        >
          Iniciar sesión para descargar
        </Link>
      )
    }
    return <AuthenticatedDownload name={name} slug={slug} version={version} dist={lastSegment(d.uri)} token={token} />
  }

  if (d.download === 'metadata_only') {
    return <span className="action-note">{DOWNLOAD_TEXT.metadataOnly}</span>
  }

  return <span className="action-note">{DOWNLOAD_TEXT.unavailable}</span>
}

function downloadError(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return DOWNLOAD_TEXT.expired
  if (error instanceof ApiError && error.status === 403) return DOWNLOAD_TEXT.forbidden
  return DOWNLOAD_TEXT.failed
}

interface AuthenticatedDownloadProps {
  name: string
  slug: string
  version: string
  dist: string
  token: string
}

/**
 * Descarga restringida con sesión: pide un enlace firmado de vida corta
 * (`POST …/download-link`) y lo abre, para no poner el JWT en la URL.
 */
function AuthenticatedDownload({ name, slug, version, dist, token }: AuthenticatedDownloadProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleClick() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const link = await requestDownloadLink(slug, version, dist, token)
      startDownload(apiHref(link.url))
    } catch (err) {
      setError(downloadError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <span className="action-stack">
      {/* Sin `disabled` mientras se pide el enlace, para no perder el foco: se ignoran los clics repetidos. */}
      <button
        type="button"
        className="action-link action-link--button"
        onClick={handleClick}
        aria-busy={busy || undefined}
        aria-label={`Descargar ${name}`}
      >
        Descargar
      </button>
      {error && (
        <span role="alert" className="action-error">
          {error}
        </span>
      )}
    </span>
  )
}
