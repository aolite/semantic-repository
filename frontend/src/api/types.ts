/**
 * Tipos de la API.
 *
 * Copiados a mano del contrato `backend/openapi.json` (versión 0.1.0). Si el
 * contrato cambia, hay que actualizarlos aquí. Cada tipo indica el esquema
 * de `components.schemas` del que sale.
 */

/** Esquema `Role`: roles con cuenta. El lector es anónimo y no tiene token. */
export type Role = 'miembro' | 'editor' | 'admin'

/** Esquema `Token`: respuesta de `POST /auth/token` (OAuth2 password flow). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  /** Validez del token en segundos. */
  expires_in: number
  role: Role
}

/** Esquema `UserRead`: respuesta de `GET /auth/me`. */
export interface CurrentUser {
  /** UUID. */
  id: string
  username: string
  role: Role
  is_active: boolean
  /** Fecha y hora ISO 8601. */
  created_at: string
  /** Fecha y hora ISO 8601. */
  updated_at: string
}

/** Esquema `HealthStatus`: respuesta de `GET /health`. */
export interface HealthResponse {
  status: 'ok'
}
