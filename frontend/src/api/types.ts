/**
 * Tipos provisionales de la API.
 *
 * Se escriben a mano a partir del contrato acordado en la fase 1 mientras no
 * exista `backend/openapi.json`. Cuando se publique, este fichero se sustituye
 * por los tipos generados desde el OpenAPI.
 */

/** Roles autenticados. El lector es anónimo y no tiene token. */
export type Role = 'miembro' | 'editor' | 'admin'

/** Respuesta de `POST /auth/token` (OAuth2 password flow). */
export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
}

/**
 * Respuesta de `GET /auth/me`.
 * Supuesto: incluye al menos `username` y `role`; el resto de campos se ignora.
 */
export interface CurrentUser {
  username: string
  role: Role
}

/** Respuesta de `GET /health`. Supuesto: un objeto JSON con `status`. */
export interface HealthResponse {
  status: string
}
