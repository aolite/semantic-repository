import { apiRequest } from './client'
import type { CurrentUser, TokenResponse } from './types'

/** `POST /auth/token` con formulario OAuth2 password (form-urlencoded). */
export function requestToken(username: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams({ grant_type: 'password', username, password })
  return apiRequest<TokenResponse>('/auth/token', {
    method: 'POST',
    body,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
}

/** `GET /auth/me` con el token Bearer. */
export function fetchCurrentUser(token: string): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/auth/me', { token })
}
